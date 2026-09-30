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
