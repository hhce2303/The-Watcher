"""On-demand H.264 screen feed for the LAN live view.

One FFmpeg process per monitor captures, encodes H.264 *once* and pipes Annex B
to stdout; every viewer of that monitor shares the same encode. The process only
runs while somebody is watching (plus a short grace so a reload or session
renewal does not restart it). It is independent of the recorder, so a stuck
live-view encode can never starve recording.

Wire format produced for the WebSocket is decided by the caller; this module
only yields access units. It assumes one slice per frame (``slices=1`` for
x264, the hardware encoders default to it).
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

from loguru import logger

KIND_JPEG, KIND_KEY, KIND_DELTA = 0, 1, 2

_START = b"\x00\x00\x01"
_NAL_SPS, _NAL_PPS, _NAL_IDR, _NAL_SLICE = 7, 8, 5, 1
_PREFIX_NALS = (6, 7, 8, 9)  # SEI, SPS, PPS, AUD travel with the next frame

_STARTUP_TIMEOUT = 8.0      # seconds to first access unit before trying the next candidate
_REUSE_GRACE = 10.0         # keep the encode alive this long after the last viewer leaves
_STATS_SECONDS = 30.0
_MAX_RESTARTS = 5
_RESTART_DELAY = 1.0


@dataclass(frozen=True)
class AccessUnit:
    key: bool
    data: bytes  # Annex B, start codes included; key units always carry SPS+PPS


class AnnexBParser:
    """Incrementally splits an Annex B byte stream into decodable access units."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._prefix: list[bytes] = []
        self._sps: Optional[bytes] = None
        self._pps: Optional[bytes] = None
        self.codec: Optional[str] = None  # "avc1.PPCCLL" once an SPS was seen
        self.multi_slice = False

    def feed(self, chunk: bytes) -> list[AccessUnit]:
        self._buf.extend(chunk)
        starts = self._start_positions()
        units: list[AccessUnit] = []
        # A NAL is complete only once the next start code is visible.
        for here, nxt in zip(starts, starts[1:]):
            nal = bytes(self._buf[here + 3:nxt]).rstrip(b"\x00")
            unit = self._on_nal(nal) if nal else None
            if unit is not None:
                units.append(unit)
        if starts:
            del self._buf[:starts[-1]]
        elif len(self._buf) > 4 * 1024 * 1024:  # garbage without start codes
            self._buf.clear()
        return units

    def _start_positions(self) -> list[int]:
        out, i, buf = [], 0, self._buf
        while True:
            i = buf.find(_START, i)
            if i < 0:
                return out
            out.append(i)
            i += 3

    def _on_nal(self, nal: bytes) -> Optional[AccessUnit]:
        kind = nal[0] & 0x1F
        if kind == _NAL_SPS:
            self._sps = nal
            if len(nal) >= 4:
                self.codec = f"avc1.{nal[1]:02x}{nal[2]:02x}{nal[3]:02x}"
        elif kind == _NAL_PPS:
            self._pps = nal
        if kind in _PREFIX_NALS:
            self._prefix.append(nal)
            return None
        if kind not in (_NAL_IDR, _NAL_SLICE):
            return None
        if len(nal) > 1 and not nal[1] & 0x80:  # first_mb_in_slice != 0
            self.multi_slice = True
        key = kind == _NAL_IDR
        nals = self._prefix
        self._prefix = []
        if key:
            kinds = {n[0] & 0x1F for n in nals}
            if _NAL_PPS not in kinds and self._pps:
                nals.insert(0, self._pps)
            if _NAL_SPS not in kinds and self._sps:
                nals.insert(0, self._sps)
        data = b"".join(b"\x00\x00\x00\x01" + n for n in [*nals, nal])
        return AccessUnit(key, data)


@dataclass(frozen=True)
class MonitorSpec:
    index: int
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class FeedConfig:
    ffmpeg: str
    fps: int = 24
    width: int = 1280
    kbps: int = 3000


def _is_h264_encoder(name: str) -> bool:
    return name.startswith("h264_") or name == "libx264"


def encoder_args(encoder: str, fps: int, kbps: int, realtime_preset: list[str]) -> list[str]:
    """Low-latency, B-frame-free, 1 s GOP flags for ``encoder`` (h264 only)."""
    if not _is_h264_encoder(encoder):
        raise ValueError(f"not an H.264 encoder: {encoder}")
    args = ["-c:v", encoder, *realtime_preset, "-b:v", f"{kbps}k", "-g", str(fps)]
    if encoder == "h264_amf":
        args += ["-usage", "ultralowlatency"]
    elif encoder == "libx264":
        args += ["-maxrate", f"{kbps}k", "-bufsize", f"{max(1, kbps // 2)}k", "-bf", "0",
                 "-x264-params", "slices=1:sliced-threads=0"]
    else:
        args += ["-bf", "0"]
    return args


def build_command(cfg: FeedConfig, spec: MonitorSpec, backend: str, encoder: str,
                  realtime_preset: list[str]) -> list[str]:
    """FFmpeg argv that streams one monitor as Annex B H.264 to stdout."""
    pix = "nv12" if encoder.endswith("_qsv") else "yuv420p"
    tail = [*encoder_args(encoder, cfg.fps, cfg.kbps, realtime_preset), "-an", "-f", "h264", "pipe:1"]
    head = [cfg.ffmpeg, "-hide_banner", "-loglevel", "error"]
    if backend == "ddagrab":
        graph = (f"ddagrab=output_idx={max(0, spec.index)}:framerate={cfg.fps}:draw_mouse=0,"
                 f"hwdownload,format=bgra,scale={cfg.width}:-2,format={pix}[v]")
        return [*head, "-filter_complex", graph, "-map", "[v]", *tail]
    if backend == "gdigrab":
        if spec.width <= 0 or spec.height <= 0:
            raise ValueError("gdigrab needs the monitor geometry")
        return [*head, "-f", "gdigrab", "-framerate", str(cfg.fps), "-offset_x", str(spec.x),
                "-offset_y", str(spec.y), "-video_size", f"{spec.width}x{spec.height}",
                "-draw_mouse", "0", "-i", "desktop",
                "-vf", f"scale={cfg.width}:-2,format={pix}", *tail]
    raise ValueError(f"unknown capture backend: {backend}")


def parse_resolution(text: str) -> tuple[int, int]:
    match = re.search(r"(\d+)\D+(\d+)", text or "")
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


@dataclass(eq=False)
class H264Subscriber:
    """A viewer's view of one monitor feed. Callbacks run on the event-loop thread."""

    on_config: Callable[[int, str], None]
    on_au: Callable[[int, bool, bytes], None]
    on_failed: Callable[[int], None]
    need_key: bool = True  # decoding can only start at a key unit


def _spawn_ffmpeg(cmd: list[str]):
    from app.adapters.ffmpeg.process_guard import assign_to_job  # noqa: PLC0415

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assign_to_job(proc)
    return proc


class H264Feed:
    """The encode for one monitor, shared by its subscribers."""

    def __init__(self, spec: MonitorSpec, cfg: FeedConfig, loop: asyncio.AbstractEventLoop,
                 candidates: Callable[[], list[tuple[str, str, list[str]]]], spawn=_spawn_ffmpeg) -> None:
        self.spec = spec
        self._cfg = cfg
        self._loop = loop
        self._candidates = candidates
        self._spawn = spawn
        self.subscribers: list[H264Subscriber] = []
        self.codec: Optional[str] = None
        self.failed = False
        self._stop = threading.Event()
        self._proc = None
        self._thread: Optional[threading.Thread] = None
        self._bytes = 0
        self._frames = 0
        self._stats_at = time.monotonic()

    # ── lifecycle (loop thread) ───────────────────────────────────────
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"live-h264-m{self.spec.index}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc is not None:
            for action in (proc.terminate, proc.kill):
                try:
                    action()
                    proc.wait(timeout=3)
                    break
                except Exception:  # noqa: BLE001
                    continue
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)

    # ── encode thread ─────────────────────────────────────────────────
    def _run(self) -> None:
        try:
            candidates = self._candidates()
        except Exception:  # noqa: BLE001
            logger.exception("[live-h264] m{} could not build encoder candidates", self.spec.index)
            candidates = []
        for backend, encoder, preset in candidates:
            if self._stop.is_set():
                return
            try:
                cmd = build_command(self._cfg, self.spec, backend, encoder, preset)
            except ValueError as exc:
                logger.info("[live-h264] m{} skip {}/{}: {}", self.spec.index, backend, encoder, exc)
                continue
            if self._attempt(backend, encoder, cmd):
                return  # stopped on purpose
        if not self._stop.is_set():
            logger.error("[live-h264] m{} no encoder candidate produced video", self.spec.index)
            self._loop.call_soon_threadsafe(self._fail)

    def _attempt(self, backend: str, encoder: str, cmd: list[str]) -> bool:
        """Run one candidate, restarting on crashes. True once stopped on purpose,
        False when the candidate never produced video (try the next one)."""
        restarts = 0
        while not self._stop.is_set():
            try:
                proc = self._spawn(cmd)
            except Exception:  # noqa: BLE001
                logger.exception("[live-h264] m{} spawn failed ({}/{})", self.spec.index, backend, encoder)
                return False
            self._proc = proc
            err: deque[str] = deque(maxlen=20)
            threading.Thread(target=self._drain_stderr, args=(proc, err), daemon=True).start()
            up = threading.Event()
            watchdog = threading.Timer(_STARTUP_TIMEOUT, lambda: None if up.is_set() else self._kill(proc))
            watchdog.daemon = True
            watchdog.start()
            started = time.monotonic()
            parser = AnnexBParser()
            announced: Optional[str] = None
            warned_slices = False
            try:
                while not self._stop.is_set():
                    chunk = proc.stdout.read(65536)
                    if not chunk:
                        break
                    for au in parser.feed(chunk):
                        if parser.multi_slice and not warned_slices:
                            warned_slices = True
                            logger.warning("[live-h264] m{} {}/{} emits multi-slice frames; "
                                           "the browser decoder will glitch", self.spec.index, backend, encoder)
                        if not up.is_set():
                            up.set()
                            logger.info("[live-h264] m{} streaming via {}/{}", self.spec.index, backend, encoder)
                        if parser.codec and parser.codec != announced:
                            announced = parser.codec
                            self._loop.call_soon_threadsafe(self._on_config, announced)
                        self._loop.call_soon_threadsafe(self._on_au, au)
                        self._count(len(au.data), backend, encoder)
            finally:
                watchdog.cancel()
                self._kill(proc)
            if self._stop.is_set():
                return True
            if not up.is_set():
                logger.warning("[live-h264] m{} {}/{} produced no video: {}", self.spec.index, backend, encoder,
                               " | ".join(err)[-400:] or "no stderr")
                return False
            if time.monotonic() - started > 30:
                restarts = 0
            restarts += 1
            if restarts > _MAX_RESTARTS:
                return False
            logger.warning("[live-h264] m{} encoder exited, restart {}/{}", self.spec.index, restarts, _MAX_RESTARTS)
            time.sleep(_RESTART_DELAY)
        return True

    @staticmethod
    def _kill(proc) -> None:
        for action in (proc.terminate, proc.kill):
            try:
                action()
                return
            except Exception:  # noqa: BLE001
                continue

    @staticmethod
    def _drain_stderr(proc, sink: deque) -> None:
        try:
            while True:
                line = proc.stderr.readline() if hasattr(proc.stderr, "readline") else proc.stderr.read(512)
                if not line:
                    return
                sink.append(line.decode("utf-8", "replace").strip() if isinstance(line, bytes) else str(line))
        except Exception:  # noqa: BLE001
            return

    def _count(self, size: int, backend: str, encoder: str) -> None:
        self._bytes += size
        self._frames += 1
        now = time.monotonic()
        if now - self._stats_at >= _STATS_SECONDS:
            span = now - self._stats_at
            logger.info("[live-h264] m{} {}/{}: {:.1f} fps {:.0f} kbit/s viewers={}", self.spec.index, backend,
                        encoder, self._frames / span, self._bytes * 8 / span / 1000, len(self.subscribers))
            self._bytes = self._frames = 0
            self._stats_at = now

    # ── loop-thread fan-out ───────────────────────────────────────────
    def _on_config(self, codec: str) -> None:
        self.codec = codec
        for sub in list(self.subscribers):
            sub.on_config(self.spec.index, codec)

    def _on_au(self, au: AccessUnit) -> None:
        for sub in list(self.subscribers):
            if sub.need_key and not au.key:
                continue
            if au.key:
                sub.need_key = False
            sub.on_au(self.spec.index, au.key, au.data)

    def _fail(self) -> None:
        self.failed = True
        for sub in list(self.subscribers):
            sub.on_failed(self.spec.index)


@dataclass
class H264Hub:
    """Reference-counted feeds, one per monitor, created on the first viewer."""

    loop: asyncio.AbstractEventLoop
    cfg: FeedConfig
    candidates_for: Callable[[], list[tuple[str, str, list[str]]]]
    spawn: Callable = _spawn_ffmpeg
    grace: float = _REUSE_GRACE
    feeds: dict[int, H264Feed] = field(default_factory=dict)

    def subscribe(self, spec: MonitorSpec, sub: H264Subscriber) -> None:
        feed = self.feeds.get(spec.index)
        if feed is None or feed.failed:
            feed = H264Feed(spec, self.cfg, self.loop, self.candidates_for, self.spawn)
            self.feeds[spec.index] = feed
            feed.subscribers.append(sub)
            feed.start()
            return
        feed.subscribers.append(sub)
        if feed.codec:
            sub.on_config(spec.index, feed.codec)
        if feed.failed:
            sub.on_failed(spec.index)

    def unsubscribe(self, index: int, sub: H264Subscriber) -> None:
        feed = self.feeds.get(index)
        if feed is None or sub not in feed.subscribers:
            return
        feed.subscribers.remove(sub)
        if not feed.subscribers:
            self.loop.call_later(self.grace, self._reap, index, feed)

    def _reap(self, index: int, feed: H264Feed) -> None:
        if feed.subscribers or self.feeds.get(index) is not feed:
            return
        del self.feeds[index]
        threading.Thread(target=feed.stop, daemon=True).start()

    def shutdown(self) -> None:
        feeds, self.feeds = list(self.feeds.values()), {}
        for feed in feeds:
            feed.stop()


def default_candidates(ffmpeg_selected: Callable[[], str]) -> Callable[[], list[tuple[str, str, list[str]]]]:
    """Capture/encoder attempts in preference order: GPU-backed encoder first,
    libx264 as the guaranteed fallback; DXGI capture first, GDI as the last resort."""
    from app.adapters.ffmpeg import encoder_selector  # noqa: PLC0415

    def build() -> list[tuple[str, str, list[str]]]:
        selected = ffmpeg_selected()
        encoders = [selected] if _is_h264_encoder(selected) else []
        if "libx264" not in encoders:
            encoders.append("libx264")
        attempts = [("ddagrab", enc) for enc in encoders] + [("gdigrab", "libx264")]
        return [(b, e, encoder_selector.preset_flags(e, True)) for b, e in attempts]

    return build
