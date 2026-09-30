"""Live-view MJPEG stream: lifetime, bandwidth and rejection diagnostics.

Regression tests for the test-PC findings of 2026-09-29: every stream died ~30 s
after opening (capability TTL re-checked per frame) and the server re-sent the
same JPEG at 10 fps even when the preview had not changed.
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from app.adapters.browser_local.auth import AuthenticationError
from app.adapters.live_view_lan import server as live_server
from app.adapters.live_view_lan.server import LiveViewLanAdapter

_JPEG = b"\xff\xd8" + b"x" * 64 + b"\xff\xd9"
_BOUNDARY = b"--watcher-live-frame"


class _FakeSessions:
    """Capability is valid only until ``cap_valid`` flips; the session until ``session_valid``."""

    def __init__(self, target: Path) -> None:
        self.target = target
        self.cap_valid = True
        self.session_valid = True
        # capability token -> supervisor identity (default: one supervisor per capability)
        self.subjects: dict[str, str] = {}

    def require_capability(self, token, _kind):
        if not self.cap_valid:
            raise AuthenticationError("media capability expired")
        return SimpleNamespace(session_token=f"session-{token}", target=self.target)

    def require_session(self, session_token):
        if not self.session_valid:
            raise AuthenticationError("session expired")
        cap = session_token.removeprefix("session-")
        return SimpleNamespace(token=session_token, subject=self.subjects.get(cap, f"user-{cap}"))


def _adapter(target: Path) -> tuple[LiveViewLanAdapter, _FakeSessions]:
    adapter = object.__new__(LiveViewLanAdapter)
    sessions = _FakeSessions(target)
    adapter._sessions = sessions
    adapter._settings = SimpleNamespace(live_view_max_viewers=3)
    adapter._viewer_streams = {}
    adapter._viewer_lock = threading.Lock()
    return adapter, sessions


def _run(coro):
    return asyncio.run(coro)


async def _client(adapter) -> TestClient:
    app = web.Application()
    app.add_routes([web.get("/stream/{capability}", adapter._stream)])
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def _read_frames(resp, seconds: float) -> int:
    """Count multipart frames received within ``seconds``."""
    frames = 0
    buf = b""
    deadline = asyncio.get_running_loop().time() + seconds
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return frames
        try:
            chunk = await asyncio.wait_for(resp.content.readany(), timeout=remaining)
        except asyncio.TimeoutError:
            return frames
        if not chunk:
            return frames
        buf += chunk
        frames += buf.count(_BOUNDARY)
        buf = buf[buf.rfind(_BOUNDARY) + len(_BOUNDARY):] if _BOUNDARY in buf else buf[-len(_BOUNDARY):]


def test_stream_survives_capability_expiry(tmp_path, monkeypatch):
    """The capability only authorises *opening* the stream; the session bounds its life."""
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    target = tmp_path / "preview.jpg"
    target.write_bytes(_JPEG)
    adapter, sessions = _adapter(target)

    async def scenario() -> int:
        client = await _client(adapter)
        try:
            resp = await client.get("/stream/cap")
            assert resp.status == 200
            await _read_frames(resp, 0.15)
            sessions.cap_valid = False  # what the 30 s capability TTL used to do
            target.write_bytes(_JPEG + b"")  # touch → new signature
            import os, time
            os.utime(target, ns=(time.time_ns(), time.time_ns()))
            return await _read_frames(resp, 0.4)
        finally:
            await client.close()

    assert _run(scenario()) >= 1, "stream must keep delivering after the capability expired"


def test_stream_ends_when_session_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    target = tmp_path / "preview.jpg"
    target.write_bytes(_JPEG)
    adapter, sessions = _adapter(target)

    async def scenario() -> bool:
        client = await _client(adapter)
        try:
            resp = await client.get("/stream/cap")
            await _read_frames(resp, 0.1)
            sessions.session_valid = False
            await _read_frames(resp, 0.3)
            return resp.content.at_eof()
        finally:
            await client.close()

    assert _run(scenario()), "an expired session must terminate its streams"
    assert adapter._viewer_streams == {}, "viewer slot must be released"


def test_unchanged_preview_is_not_resent(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    monkeypatch.setattr(live_server, "_KEEPALIVE_SECONDS", 60.0)
    target = tmp_path / "preview.jpg"
    target.write_bytes(_JPEG)
    adapter, _ = _adapter(target)

    async def scenario() -> int:
        client = await _client(adapter)
        try:
            resp = await client.get("/stream/cap")
            return await _read_frames(resp, 0.5)  # ~50 polls, file never changes
        finally:
            await client.close()

    assert _run(scenario()) == 1, "static preview → exactly one frame, not one per poll"


def test_changed_preview_is_sent_again(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    monkeypatch.setattr(live_server, "_KEEPALIVE_SECONDS", 60.0)
    target = tmp_path / "preview.jpg"
    target.write_bytes(_JPEG)
    adapter, _ = _adapter(target)

    async def scenario() -> int:
        client = await _client(adapter)
        try:
            resp = await client.get("/stream/cap")
            first = await _read_frames(resp, 0.15)
            target.write_bytes(b"\xff\xd8" + b"y" * 100 + b"\xff\xd9")  # new size → new signature
            return first + await _read_frames(resp, 0.3)
        finally:
            await client.close()

    assert _run(scenario()) == 2


def test_keepalive_resends_a_static_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    monkeypatch.setattr(live_server, "_KEEPALIVE_SECONDS", 0.2)
    target = tmp_path / "preview.jpg"
    target.write_bytes(_JPEG)
    adapter, _ = _adapter(target)

    async def scenario() -> int:
        client = await _client(adapter)
        try:
            resp = await client.get("/stream/cap")
            return await _read_frames(resp, 0.7)
        finally:
            await client.close()

    frames = _run(scenario())
    assert 2 <= frames <= 5, f"expected a few keepalive frames, got {frames}"


def test_rejected_events_auth_is_logged_with_reason():
    """A rejected assertion must leave the reason (never the assertion) in the log."""
    messages: list[str] = []
    sink_id = live_server.logger.add(lambda m: messages.append(str(m)), level="WARNING")

    class _Sessions:
        def open_session(self, _assertion):
            raise AuthenticationError("assertion replay")

    adapter = object.__new__(LiveViewLanAdapter)
    adapter._sessions = _Sessions()
    adapter._settings = SimpleNamespace(live_view_origin="https://op.lan:8767")

    async def scenario():
        app = web.Application()
        app.add_routes([web.get("/events", adapter._events)])
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            ws = await client.ws_connect("/events", headers={"Origin": "https://op.lan:8767"})
            await ws.send_json({"type": "auth", "assertion": "SECRET.JWT.VALUE"})
            msg = await ws.receive(timeout=2)
            return msg
        finally:
            await client.close()

    try:
        _run(scenario())
    finally:
        live_server.logger.remove(sink_id)
    joined = "\n".join(messages)
    assert "assertion replay" in joined
    assert "SECRET.JWT.VALUE" not in joined


def test_embed_js_renews_session_and_reports_superseded_sockets():
    js = live_server._JS
    assert "watcher:ready" in js.split("window.addEventListener")[0], "iframe must re-request an assertion before the session ends"
    assert "setTimeout" in js
    assert "ws!==mine" in js.replace(" ", "") or "mine" in js, "a superseded socket must not show 'rejected'"


def test_one_supervisor_with_many_sessions_counts_as_one_viewer(tmp_path, monkeypatch):
    """Reloads/renewals create new sessions for the same supervisor; they share one slot."""
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    target = tmp_path / "preview.jpg"
    target.write_bytes(_JPEG)
    adapter, sessions = _adapter(target)
    sessions.subjects.update({"a2": "user-a", "a3": "user-a", "a4": "user-a", "a5": "user-a", "a": "user-a"})

    async def scenario() -> list[int]:
        client = await _client(adapter)
        try:
            statuses, resps = [], []
            for cap in ("a", "a2", "a3", "a4", "a5"):  # 5 sessions, 1 supervisor
                resp = await client.get(f"/stream/{cap}")
                statuses.append(resp.status)
                resps.append(resp)
            return statuses
        finally:
            await client.close()

    assert _run(scenario()) == [200] * 5


def test_fourth_distinct_supervisor_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    target = tmp_path / "preview.jpg"
    target.write_bytes(_JPEG)
    adapter, _ = _adapter(target)

    async def scenario() -> list[int]:
        client = await _client(adapter)
        try:
            statuses, resps = [], []
            for cap in ("u1", "u2", "u3", "u4"):
                resp = await client.get(f"/stream/{cap}")
                statuses.append(resp.status)
                resps.append(resp)
            return statuses
        finally:
            await client.close()

    assert _run(scenario()) == [200, 200, 200, 429]


def test_slot_is_released_promptly_when_the_client_disconnects(tmp_path, monkeypatch):
    """A static preview writes nothing; a dropped client must still free its slot."""
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    monkeypatch.setattr(live_server, "_KEEPALIVE_SECONDS", 60.0)
    target = tmp_path / "preview.jpg"
    target.write_bytes(_JPEG)
    adapter, _ = _adapter(target)

    async def scenario() -> dict:
        client = await _client(adapter)
        try:
            resp = await client.get("/stream/cap")
            await _read_frames(resp, 0.1)
            resp.close()  # browser navigated away / tab closed
            await asyncio.sleep(0.4)
            return dict(adapter._viewer_streams)
        finally:
            await client.close()

    assert _run(scenario()) == {}, "slot leaked although the client went away"


# ── Single-connection transport: every monitor over the /events WebSocket ──────
# Browsers cap HTTP/1.1 at 6 connections per host; one infinite <img> stream per
# monitor let 6 streams starve every other tab's iframe ("pending", no error).

from aiohttp import WSMsgType  # noqa: E402

_ORIGIN = "https://op.lan:8767"


class _WsSessions:
    def __init__(self) -> None:
        self.valid = True
        self._subjects: dict[str, str] = {}
        self._n = 0

    def open_session(self, assertion):
        if assertion.startswith("bad"):
            raise AuthenticationError("assertion replay")
        self._n += 1
        token = f"tok{self._n}"
        self._subjects[token] = assertion
        return SimpleNamespace(token=token, subject=assertion)

    def require_session(self, token):
        if not self.valid or token not in self._subjects:
            raise AuthenticationError("session expired")
        return SimpleNamespace(token=token, subject=self._subjects[token])


def _ws_adapter(tmp_path: Path, monitors=(0, 1)) -> tuple[LiveViewLanAdapter, _WsSessions]:
    adapter = object.__new__(LiveViewLanAdapter)
    sessions = _WsSessions()
    adapter._sessions = sessions
    adapter._settings = SimpleNamespace(live_view_origin=_ORIGIN, live_view_max_viewers=3, segment_dir=tmp_path)
    adapter._api = SimpleNamespace(recording=SimpleNamespace(
        get_monitors=lambda: [SimpleNamespace(index=i, name=f"D{i}") for i in monitors]))
    adapter._viewer_streams = {}
    adapter._viewer_lock = threading.Lock()
    adapter._hub = None
    for i in monitors:
        (tmp_path / f"m{i}").mkdir(exist_ok=True)
        (tmp_path / f"m{i}" / "preview.jpg").write_bytes(b"\xff\xd8" + bytes([i]) * 40 + b"\xff\xd9")
    return adapter, sessions


async def _ws_client(adapter) -> TestClient:
    app = web.Application()
    app.add_routes([web.get("/events", adapter._events)])
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def _subscribed(client, subject: str, codec: str | None = None):
    ws = await client.ws_connect("/events", headers={"Origin": _ORIGIN})
    await ws.send_json({"type": "auth", "assertion": subject})
    assert (await ws.receive_json(timeout=2))["type"] == "authenticated"
    await ws.send_json({"type": "subscribe", **({"codec": codec} if codec else {})})
    return ws


async def _binary_frames(ws, seconds: float) -> dict[int, int]:
    """index -> number of binary frames received within ``seconds``."""
    seen: dict[int, int] = {}
    deadline = asyncio.get_running_loop().time() + seconds
    while (left := deadline - asyncio.get_running_loop().time()) > 0:
        try:
            msg = await ws.receive(timeout=left)
        except asyncio.TimeoutError:
            break
        if msg.type == WSMsgType.BINARY:
            assert msg.data[0] == 0, "JPEG frames carry kind 0"
            assert msg.data[2:4] == b"\xff\xd8" and msg.data.endswith(b"\xff\xd9")
            seen[msg.data[1]] = seen.get(msg.data[1], 0) + 1
    return seen


def test_ws_pushes_every_monitor_once_over_one_connection(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    monkeypatch.setattr(live_server, "_KEEPALIVE_SECONDS", 60.0)
    adapter, _ = _ws_adapter(tmp_path, monitors=(0, 1, 2, 3))

    async def scenario():
        client = await _ws_client(adapter)
        try:
            ws = await _subscribed(client, "u1")
            return await _binary_frames(ws, 0.5)
        finally:
            await client.close()

    assert _run(scenario()) == {0: 1, 1: 1, 2: 1, 3: 1}, "one frame per monitor, none repeated while static"


def test_ws_resends_only_the_monitor_that_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    monkeypatch.setattr(live_server, "_KEEPALIVE_SECONDS", 60.0)
    adapter, _ = _ws_adapter(tmp_path)

    async def scenario():
        client = await _ws_client(adapter)
        try:
            ws = await _subscribed(client, "u1")
            await _binary_frames(ws, 0.2)
            (tmp_path / "m1" / "preview.jpg").write_bytes(b"\xff\xd8" + b"\x01" * 90 + b"\xff\xd9")
            return await _binary_frames(ws, 0.3)
        finally:
            await client.close()

    assert _run(scenario()) == {1: 1}


def test_ws_limits_distinct_supervisors_but_not_their_reconnects(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    adapter, _ = _ws_adapter(tmp_path)

    async def scenario():
        client = await _ws_client(adapter)
        try:
            socks = [await _subscribed(client, s) for s in ("u1", "u2", "u3", "u1")]  # u1 twice: one slot
            for w in socks:
                assert await _binary_frames(w, 0.15), "every admitted socket must receive frames"
            fourth = await _subscribed(client, "u4")
            msg = await fourth.receive_json(timeout=2)
            closed = await fourth.receive(timeout=2)
            return msg, closed.type
        finally:
            await client.close()

    msg, closed_type = _run(scenario())
    assert msg == {"type": "error", "reason": "viewer limit reached"}
    assert closed_type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED)


def test_ws_closes_and_frees_the_slot_when_the_session_expires(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    adapter, sessions = _ws_adapter(tmp_path)

    async def scenario():
        client = await _ws_client(adapter)
        try:
            ws = await _subscribed(client, "u1")
            await _binary_frames(ws, 0.1)
            sessions.valid = False
            while True:
                msg = await ws.receive(timeout=2)
                if msg.type in (WSMsgType.CLOSE, WSMsgType.CLOSING, WSMsgType.CLOSED):
                    break
            await asyncio.sleep(0.1)
            return dict(adapter._viewer_streams)
        finally:
            await client.close()

    assert _run(scenario()) == {}


def test_ws_slot_is_freed_when_the_client_disconnects(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    adapter, _ = _ws_adapter(tmp_path)

    async def scenario():
        client = await _ws_client(adapter)
        try:
            ws = await _subscribed(client, "u1")
            await _binary_frames(ws, 0.1)
            await ws.close()
            await asyncio.sleep(0.3)
            return dict(adapter._viewer_streams)
        finally:
            await client.close()

    assert _run(scenario()) == {}


def test_embed_js_uses_one_websocket_not_one_stream_per_monitor():
    js = live_server._JS
    assert "subscribe" in js and "arraybuffer" in js and "createImageBitmap" in js
    assert "VideoDecoder" in js and "EncodedVideoChunk" in js and "codec:'h264'" in js.replace(" ", "")
    assert "mjpeg" in js, "the page must be able to fall back to JPEG frames"
    assert "stream_url" not in js, "per-monitor <img> streams are what exhausted the 6-connection cap"


# ── H.264 over the same WebSocket ───────────────────────────────────────────────

import json  # noqa: E402
import time  # noqa: E402

from app.adapters.live_view_lan.h264_feed import H264Hub  # noqa: E402
from tests.test_live_view_h264 import AUD, CANDIDATES, CFG, PPS, SPS, _Spawner, idr, pframe  # noqa: E402


async def _collect(ws, count: int, timeout: float = 3.0) -> list:
    """First ``count`` messages as ("json", dict) or ("bin", kind, index, payload)."""
    out = []
    deadline = asyncio.get_running_loop().time() + timeout
    while len(out) < count:
        msg = await ws.receive(timeout=max(0.01, deadline - asyncio.get_running_loop().time()))
        if msg.type == WSMsgType.TEXT:
            out.append(("json", json.loads(msg.data)))
        elif msg.type == WSMsgType.BINARY:
            out.append(("bin", msg.data[0], msg.data[1], msg.data[2:]))
        else:
            break
    return out


def test_ws_h264_sends_config_then_key_then_delta_and_no_jpeg(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    adapter, _ = _ws_adapter(tmp_path, monitors=(0,))
    spawner = _Spawner(lambda p: (time.sleep(0.05), p.push(SPS, PPS, idr(), pframe(), AUD)))

    async def scenario():
        adapter._hub = H264Hub(asyncio.get_running_loop(), CFG, CANDIDATES, spawn=spawner, grace=0.05)
        client = await _ws_client(adapter)
        try:
            ws = await _subscribed(client, "u1", codec="h264")
            got = await _collect(ws, 3)
            await _binary_frames(ws, 0.2)  # nothing JPEG may follow
            return got
        finally:
            await client.close()

    cfg, key, delta = asyncio.run(scenario())
    assert cfg == ("json", {"type": "video_config", "monitor": 0, "codec": "avc1.4d401f"})
    assert key[:3] == ("bin", live_server.KIND_KEY, 0) and key[3].startswith(b"\x00\x00\x00\x01" + SPS)
    assert delta[:3] == ("bin", live_server.KIND_DELTA, 0)


def test_ws_falls_back_to_jpeg_when_no_encoder_works(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    monkeypatch.setattr(live_server, "_KEEPALIVE_SECONDS", 60.0)
    adapter, _ = _ws_adapter(tmp_path, monitors=(0, 1))
    spawner = _Spawner(*[lambda p: p.finish()] * 6)

    async def scenario():
        adapter._hub = H264Hub(asyncio.get_running_loop(), CFG, CANDIDATES, spawn=spawner, grace=0.05)
        client = await _ws_client(adapter)
        try:
            ws = await _subscribed(client, "u1", codec="h264")
            jsons, frames = [], {}
            deadline = asyncio.get_running_loop().time() + 3
            while (len(jsons) < 2 or len(frames) < 2) and asyncio.get_running_loop().time() < deadline:
                msg = await ws.receive(timeout=3)
                if msg.type == WSMsgType.TEXT:
                    jsons.append(json.loads(msg.data))
                elif msg.type == WSMsgType.BINARY:
                    frames[msg.data[1]] = msg.data[0]
            return jsons, frames
        finally:
            await client.close()

    jsons, frames = asyncio.run(scenario())
    assert sorted(j["monitor"] for j in jsons if j["codec"] == "mjpeg") == [0, 1]
    assert frames == {0: live_server.KIND_JPEG, 1: live_server.KIND_JPEG}


def test_ws_without_codec_keeps_serving_jpeg_even_when_a_hub_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    monkeypatch.setattr(live_server, "_KEEPALIVE_SECONDS", 60.0)
    adapter, _ = _ws_adapter(tmp_path)
    spawner = _Spawner()

    async def scenario():
        adapter._hub = H264Hub(asyncio.get_running_loop(), CFG, CANDIDATES, spawn=spawner, grace=0.05)
        client = await _ws_client(adapter)
        try:
            ws = await _subscribed(client, "u1")  # older page / no WebCodecs
            return await _binary_frames(ws, 0.3), len(spawner.calls)
        finally:
            await client.close()

    frames, spawned = asyncio.run(scenario())
    assert frames == {0: 1, 1: 1} and spawned == 0, "no encoder may start for a JPEG viewer"


def test_ws_h264_releases_the_encode_after_the_viewer_leaves(tmp_path, monkeypatch):
    monkeypatch.setattr(live_server, "_FRAME_POLL_SECONDS", 0.01)
    adapter, _ = _ws_adapter(tmp_path, monitors=(0,))
    spawner = _Spawner(lambda p: p.push(SPS, PPS, idr(), AUD))

    async def scenario():
        hub = adapter._hub = H264Hub(asyncio.get_running_loop(), CFG, CANDIDATES, spawn=spawner, grace=0.1)
        client = await _ws_client(adapter)
        try:
            ws = await _subscribed(client, "u1", codec="h264")
            await _collect(ws, 2)
            assert 0 in hub.feeds
            await ws.close()
            await asyncio.sleep(0.5)
            return dict(hub.feeds), spawner.calls[0][1].terminated
        finally:
            await client.close()

    feeds, terminated = asyncio.run(scenario())
    assert feeds == {} and terminated, "nobody watching → the encoder must stop"


def test_a_slow_viewer_drops_its_backlog_and_waits_for_the_next_key_frame():
    adapter = object.__new__(LiveViewLanAdapter)
    captured = []
    adapter._hub = SimpleNamespace(subscribe=lambda spec, sub: captured.append(sub))
    adapter._api = SimpleNamespace(recording=SimpleNamespace(get_monitors=lambda: [SimpleNamespace(index=0, name="D0")]))

    async def scenario():
        out: asyncio.Queue = asyncio.Queue(maxsize=2)
        subs = adapter._h264_subscribers(out, set())
        sub = subs[0][1]
        sub.on_au(0, True, b"k")
        sub.on_au(0, False, b"d1")
        sub.on_au(0, False, b"d2")  # queue full → backlog dropped
        return out.empty(), sub.need_key

    assert asyncio.run(scenario()) == (True, True)
