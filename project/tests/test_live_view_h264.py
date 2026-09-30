"""H.264 live feed: Annex B parsing, command building, sharing and fallback."""
from __future__ import annotations

import asyncio
import queue
import shutil
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from app.adapters.live_view_lan import h264_feed as hf
from app.adapters.live_view_lan.h264_feed import (
    AnnexBParser, FeedConfig, H264Hub, H264Subscriber, MonitorSpec, build_command, parse_resolution,
)

SPS = b"\x67\x4d\x40\x1f\xaa\xbb"
PPS = b"\x68\xee\x3c\x80"
AUD = b"\x09\x10"


def idr(tag=b"i"):
    return b"\x65\x88\x84" + tag * 12


def pframe(tag=b"p"):
    return b"\x41\x9a\x24" + tag * 6


def annexb(*nals: bytes, four=True) -> bytes:
    sc = b"\x00\x00\x00\x01" if four else b"\x00\x00\x01"
    return b"".join(sc + n for n in nals)


# ── parser ─────────────────────────────────────────────────────────────────────

def test_parser_groups_headers_with_the_key_frame_and_reports_the_codec():
    parser = AnnexBParser()
    units = parser.feed(annexb(SPS, PPS, idr(), pframe(), AUD))
    assert [u.key for u in units] == [True, False]
    assert units[0].data == annexb(SPS, PPS, idr())
    assert units[1].data == annexb(pframe())
    assert parser.codec == "avc1.4d401f"


def test_parser_waits_for_the_next_start_code_before_emitting():
    parser = AnnexBParser()
    assert parser.feed(annexb(SPS, PPS, idr())) == []
    assert len(parser.feed(annexb(AUD))) == 1


def test_parser_is_chunking_independent_and_accepts_three_byte_start_codes():
    stream = annexb(SPS, PPS, idr(), pframe(b"a"), pframe(b"b"), AUD, four=False)
    whole = AnnexBParser().feed(stream)
    parser, bytewise = AnnexBParser(), []
    for i in range(len(stream)):
        bytewise += parser.feed(stream[i:i + 1])
    assert bytewise == whole and len(whole) == 3


def test_parser_reinserts_cached_headers_in_front_of_a_bare_idr():
    parser = AnnexBParser()
    parser.feed(annexb(SPS, PPS, idr(), AUD))
    units = parser.feed(annexb(pframe(), idr(b"j"), AUD))
    key = next(u for u in units if u.key)
    assert key.data == annexb(SPS, PPS, idr(b"j"))


def test_parser_flags_multi_slice_streams():
    parser = AnnexBParser()
    parser.feed(annexb(SPS, PPS, idr(), b"\x41\x1a\x24" + b"s" * 4, AUD))  # second slice: first_mb != 0
    assert parser.multi_slice


# ── command building ───────────────────────────────────────────────────────────

CFG = FeedConfig(ffmpeg="ffmpeg.exe", fps=24, width=1280, kbps=3000)
SPEC = MonitorSpec(index=2, x=-1920, y=-1080, width=1920, height=1080)


def test_ddagrab_command_streams_annexb_h264_to_stdout():
    cmd = build_command(CFG, SPEC, "ddagrab", "h264_amf", ["-quality", "speed"])
    joined = " ".join(cmd)
    assert "ddagrab=output_idx=2:framerate=24:draw_mouse=0,hwdownload,format=bgra,scale=1280:-2,format=yuv420p[v]" in joined
    assert cmd[-3:] == ["-f", "h264", "pipe:1"]
    assert "-usage ultralowlatency" in joined and "-g 24" in joined and "-b:v 3000k" in joined


def test_x264_command_is_single_slice_and_b_frame_free():
    joined = " ".join(build_command(CFG, SPEC, "ddagrab", "libx264", ["-preset", "ultrafast", "-tune", "zerolatency"]))
    assert "slices=1:sliced-threads=0" in joined and "-bf 0" in joined and "-maxrate 3000k" in joined


def test_qsv_gets_nv12_and_gdigrab_uses_the_monitor_geometry():
    assert "format=nv12" in " ".join(build_command(CFG, SPEC, "ddagrab", "h264_qsv", []))
    cmd = build_command(CFG, SPEC, "gdigrab", "libx264", [])
    assert cmd[cmd.index("-offset_x") + 1] == "-1920" and cmd[cmd.index("-video_size") + 1] == "1920x1080"


def test_non_h264_encoders_and_unknown_backends_are_rejected():
    with pytest.raises(ValueError):
        build_command(CFG, SPEC, "ddagrab", "hevc_amf", [])
    with pytest.raises(ValueError):
        build_command(CFG, SPEC, "wgc", "libx264", [])
    with pytest.raises(ValueError):
        build_command(CFG, MonitorSpec(index=0), "gdigrab", "libx264", [])


def test_parse_resolution_accepts_the_dto_format():
    assert parse_resolution("1920×1080") == (1920, 1080)
    assert parse_resolution("1280x720") == (1280, 720)
    assert parse_resolution("") == (0, 0)


# ── hub: sharing, late join, reuse, fallback ───────────────────────────────────

class _FakeProc:
    def __init__(self) -> None:
        self._q: queue.Queue = queue.Queue()
        self.terminated = False
        self.stdout = SimpleNamespace(read=self._read)
        self.stderr = SimpleNamespace(readline=lambda: b"")

    def _read(self, _n):
        item = self._q.get(timeout=10)
        return b"" if item is None else item

    def push(self, *nals: bytes) -> None:
        self._q.put(annexb(*nals))

    def finish(self) -> None:
        self._q.put(None)

    def terminate(self) -> None:
        self.terminated = True
        self.finish()

    def kill(self) -> None:
        self.terminate()

    def wait(self, timeout=None) -> int:
        return 0


class _Spawner:
    def __init__(self, *behaviors) -> None:
        self.behaviors = list(behaviors)
        self.calls: list[tuple[list[str], _FakeProc]] = []

    def __call__(self, cmd):
        proc = _FakeProc()
        self.calls.append((cmd, proc))
        behavior = self.behaviors.pop(0) if self.behaviors else None
        if behavior:
            threading.Thread(target=behavior, args=(proc,), daemon=True).start()
        return proc


CANDIDATES = lambda: [  # noqa: E731
    ("ddagrab", "h264_amf", ["-quality", "speed"]),
    ("ddagrab", "libx264", ["-preset", "ultrafast"]),
    ("gdigrab", "libx264", ["-preset", "ultrafast"]),
]


class _Viewer:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.sub = H264Subscriber(
            on_config=lambda i, c: self.events.append(("cfg", c)),
            on_au=lambda i, k, d: self.events.append(("key" if k else "delta",)),
            on_failed=lambda i: self.events.append(("failed",)),
        )


async def _until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.01)


def _hub(spawner, grace=0.05):
    return H264Hub(asyncio.get_running_loop(), CFG, CANDIDATES, spawn=spawner, grace=grace)


def test_viewers_share_one_encode_and_late_joiners_wait_for_a_key_frame():
    spawner = _Spawner()

    async def scenario():
        hub, a, b = _hub(spawner), _Viewer(), _Viewer()
        hub.subscribe(SPEC, a.sub)
        await _until(lambda: spawner.calls)
        proc = spawner.calls[0][1]
        proc.push(SPS, PPS, idr(), pframe(b"1"), pframe(b"2"))
        await _until(lambda: len(a.events) >= 3)          # cfg, key, delta
        hub.subscribe(SPEC, b.sub)                         # joins mid-GOP
        assert b.events == [("cfg", "avc1.4d401f")], "config is replayed immediately"
        proc.push(pframe(b"3"), idr(b"j"), pframe(b"4"), AUD)
        await _until(lambda: len(b.events) >= 3)
        hub.shutdown()
        return a.events, b.events, len(spawner.calls)

    a, b, spawns = asyncio.run(scenario())
    assert spawns == 1, "one ffmpeg for two viewers"
    assert a == [("cfg", "avc1.4d401f"), ("key",), ("delta",), ("delta",), ("delta",), ("key",), ("delta",)]
    assert b == [("cfg", "avc1.4d401f"), ("key",), ("delta",)], "late viewer skips deltas before the next key frame"


def test_encode_stops_after_the_grace_period_and_restarts_on_demand():
    spawner = _Spawner()

    async def scenario():
        hub, viewer = _hub(spawner, grace=0.1), _Viewer()
        hub.subscribe(SPEC, viewer.sub)
        await _until(lambda: spawner.calls)
        first = spawner.calls[0][1]
        hub.unsubscribe(SPEC.index, viewer.sub)
        await asyncio.sleep(0.03)
        assert not first.terminated, "a quick reload must not restart the encoder"
        await _until(lambda: first.terminated)
        assert SPEC.index not in hub.feeds
        hub.subscribe(SPEC, viewer.sub)
        await _until(lambda: len(spawner.calls) == 2)
        hub.shutdown()

    asyncio.run(scenario())


def test_resubscribing_within_the_grace_period_keeps_the_same_encode():
    spawner = _Spawner()

    async def scenario():
        hub, viewer = _hub(spawner, grace=0.15), _Viewer()
        hub.subscribe(SPEC, viewer.sub)
        await _until(lambda: spawner.calls)
        hub.unsubscribe(SPEC.index, viewer.sub)
        hub.subscribe(SPEC, viewer.sub)
        await asyncio.sleep(0.4)
        alive = not spawner.calls[0][1].terminated
        hub.shutdown()
        return alive, len(spawner.calls)

    assert asyncio.run(scenario()) == (True, 1)


def test_a_candidate_that_dies_without_video_falls_through_to_the_next(monkeypatch):
    spawner = _Spawner(lambda p: p.finish(), lambda p: (time.sleep(0.05), p.push(SPS, PPS, idr(), AUD)))

    async def scenario():
        hub, viewer = _hub(spawner), _Viewer()
        hub.subscribe(SPEC, viewer.sub)
        await _until(lambda: ("key",) in viewer.events)
        hub.shutdown()
        return [" ".join(c) for c, _ in spawner.calls]

    calls = asyncio.run(scenario())
    assert "h264_amf" in calls[0] and "libx264" in calls[1] and "ddagrab" in calls[1]


def test_a_hung_encoder_is_killed_by_the_startup_watchdog(monkeypatch):
    monkeypatch.setattr(hf, "_STARTUP_TIMEOUT", 0.2)
    spawner = _Spawner(None, lambda p: p.push(SPS, PPS, idr(), AUD))

    async def scenario():
        hub, viewer = _hub(spawner), _Viewer()
        hub.subscribe(SPEC, viewer.sub)
        await _until(lambda: ("key",) in viewer.events)
        hub.shutdown()
        return spawner.calls[0][1].terminated

    assert asyncio.run(scenario()), "the silent first encoder must be terminated"


def test_when_every_candidate_fails_subscribers_are_told_and_a_new_viewer_retries():
    spawner = _Spawner(*[lambda p: p.finish()] * 6)

    async def scenario():
        hub, viewer = _hub(spawner), _Viewer()
        hub.subscribe(SPEC, viewer.sub)
        await _until(lambda: ("failed",) in viewer.events)
        assert hub.feeds[SPEC.index].failed
        calls_before = len(spawner.calls)
        hub.subscribe(SPEC, _Viewer().sub)
        await _until(lambda: len(spawner.calls) > calls_before)
        hub.shutdown()
        return calls_before

    assert asyncio.run(scenario()) == 3, "all three candidates were tried"


def test_an_encoder_that_crashes_after_streaming_is_restarted(monkeypatch):
    monkeypatch.setattr(hf, "_RESTART_DELAY", 0.01)

    def crash_after_video(proc):
        proc.push(SPS, PPS, idr(), AUD)
        time.sleep(0.1)
        proc.finish()

    spawner = _Spawner(crash_after_video, lambda p: p.push(SPS, PPS, idr(b"k"), AUD))

    async def scenario():
        hub, viewer = _hub(spawner), _Viewer()
        hub.subscribe(SPEC, viewer.sub)
        await _until(lambda: len(spawner.calls) == 2)
        await _until(lambda: [e for e in viewer.events if e == ("key",)].__len__() >= 2)
        hub.shutdown()
        return [" ".join(c) for c, _ in spawner.calls]

    calls = asyncio.run(scenario())
    assert calls[0] == calls[1], "a crash restarts the same candidate"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_x264_output_is_one_access_unit_per_frame_with_a_key_frame_each_second():
    """Guards the x264 flags against the real encoder: -tune zerolatency turns on
    sliced-threads, which splits every frame into many slices unless disabled."""
    from app.adapters.ffmpeg import encoder_selector

    args = hf.encoder_args("libx264", 24, 3000, encoder_selector.preset_flags("libx264", True))
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=24",
           "-t", "3", "-vf", "format=yuv420p", *args, "-an", "-f", "h264", "pipe:1"]
    data = subprocess.run(cmd, capture_output=True, check=True, timeout=60).stdout
    parser = AnnexBParser()
    units = parser.feed(data + annexb(AUD))
    assert len(units) == 72, "72 frames in, 72 access units out"
    assert [i for i, u in enumerate(units) if u.key] == [0, 24, 48]
    assert not parser.multi_slice and parser.codec
    assert all(u.data[4] & 0x1F == 7 for u in units if u.key), "key frames carry SPS for late joiners"
