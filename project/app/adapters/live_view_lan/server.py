"""Dedicated TLS/MJPEG surface for Daily Supervisor live observation.

It deliberately shares only device-identity and assertion verification code
with ``browser_local``.  It never widens that loopback adapter.
"""
from __future__ import annotations

import asyncio
import html
import json
import ssl
import threading
import time
from urllib.error import URLError
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web
from loguru import logger

from app.adapters.browser_local.auth import AuthenticationError, BrowserSessionManager
from app.adapters.browser_local.identity import DeviceIdentityStore
from app.core.ports.live_view_port import LiveViewPort

_MAX_WS_MESSAGE = 16 * 1024
_BOUNDARY = b"watcher-live-frame"


class LiveViewLanAdapter(LiveViewPort):
    """Operator-only, token-gated viewer server; media never crosses IPC/JSON."""

    def __init__(self, settings, api_layer) -> None:
        self._settings = settings
        self._api = api_layer
        self._identity = DeviceIdentityStore(settings.browser_local_data_dir).load_or_create()
        self._sessions = BrowserSessionManager(
            identity=self._identity,
            issuer=settings.live_view_issuer,
            audience=settings.live_view_audience,
            issuer_kid=settings.live_view_issuer_kid,
            station_id=settings.live_view_station_id,
            issuer_public_key_file=settings.live_view_issuer_public_key_file,
            required_scope="live:read",
        )
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._stop_event: asyncio.Event | None = None
        self._ready = threading.Event()
        self._start_error: Exception | None = None
        self._running = False
        self._viewers = 0
        self._viewer_lock = threading.Lock()
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    @property
    def enrollment_payload(self) -> dict[str, str]:
        return self._identity.enrollment_payload()

    def start(self) -> bool:
        if self._running:
            return True
        if not self._settings.live_view_enabled:
            return False
        try:
            self._validate()
        except Exception as exc:  # fail closed; recording remains independent
            logger.error("[live-view] not started: {}", exc)
            return False
        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="live-view-lan", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=8)
        started = self._start_error is None and self._running
        if started:
            self._start_heartbeat()
        return started

    def stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._heartbeat_stop.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=5)
        self._heartbeat_thread = None
        self._running = False

    def _validate(self) -> None:
        if not self._settings.live_view_origin.startswith("https://"):
            raise ValueError("LIVE_VIEW_ORIGIN must be the managed HTTPS LAN origin")
        if not self._settings.live_view_parent_origin.startswith("https://"):
            raise ValueError("LIVE_VIEW_PARENT_ORIGIN must use HTTPS")
        if self._settings.live_view_max_viewers < 1:
            raise ValueError("LIVE_VIEW_MAX_VIEWERS must be positive")
        if not Path(self._settings.live_view_cert_file).is_file() or not Path(self._settings.live_view_key_file).is_file():
            raise ValueError("LIVE_VIEW_CERT_FILE and LIVE_VIEW_KEY_FILE are required")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as exc:  # noqa: BLE001
            self._start_error = exc
            logger.exception("[live-view] server failed")
        finally:
            self._running = False
            self._ready.set()
            self._loop.close()
            self._loop = None

    async def _serve(self) -> None:
        app = web.Application(middlewares=[self._headers, self._errors])
        app.add_routes([
            web.get("/embed", self._embed), web.get("/embed.js", self._js),
            web.get("/embed.css", self._css), web.get("/api/v1/health", self._health),
            web.get("/api/v1/monitors", self._monitors), web.get("/stream/{capability}", self._stream),
            web.get("/events", self._events),
        ])
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self._settings.live_view_cert_file, self._settings.live_view_key_file)
        await web.TCPSite(self._runner, self._settings.live_view_bind_host, self._settings.live_view_port, ssl_context=context).start()
        self._stop_event = asyncio.Event()
        self._running = True
        self._ready.set()
        logger.info("[live-view] listening at {}", self._settings.live_view_origin)
        await self._stop_event.wait()
        await self._runner.cleanup()

    def _start_heartbeat(self) -> None:
        if not self._settings.live_view_heartbeat_url:
            logger.warning("[live-view] heartbeat disabled: LIVE_VIEW_HEARTBEAT_URL is not configured")
            return
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="live-view-heartbeat", daemon=True
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self) -> None:
        interval = max(10, self._settings.live_view_heartbeat_seconds)
        while not self._heartbeat_stop.is_set():
            self._send_heartbeat()
            self._heartbeat_stop.wait(interval)

    def _send_heartbeat(self) -> None:
        try:
            monitors = tuple(sorted(monitor.index for monitor in self._api.recording.get_monitors()))
            recording_state = "recording" if any(
                (self._settings.segment_dir / f"m{index}" / "preview.jpg").is_file()
                for index in monitors
            ) else "starting"
            health = "ok" if monitors else "degraded"
            timestamp = int(time.time())
            payload = {
                "device_id": self._identity.device_id,
                "timestamp": timestamp,
                "live_origin": self._settings.live_view_origin,
                "recording_state": recording_state,
                "health": health,
                "monitor_indexes": list(monitors),
                "signature": self._identity.sign_live_heartbeat(
                    timestamp=timestamp,
                    live_origin=self._settings.live_view_origin,
                    recording_state=recording_state,
                    health=health,
                    monitors=monitors,
                ),
            }
            request = Request(
                self._settings.live_view_heartbeat_url,
                data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                headers={"Content-Type": "application/json", "Cache-Control": "no-store"},
                method="POST",
            )
            with urlopen(request, timeout=5) as response:  # noqa: S310 -- configured HTTPS endpoint
                if response.status != 200:
                    raise OSError(f"unexpected status {response.status}")
        except (OSError, URLError, ValueError) as exc:
            logger.warning("[live-view] heartbeat failed: {}", exc)

    @web.middleware
    async def _headers(self, _request: web.Request, handler):
        response = await handler(_request)
        response.headers.update({
            "Content-Security-Policy": f"default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors {self._settings.live_view_parent_origin}; connect-src 'self' {self._settings.live_view_origin.replace('https:', 'wss:')}; img-src 'self'; style-src 'self'; script-src 'self'; form-action 'none'",
            "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        })
        return response

    @web.middleware
    async def _errors(self, request: web.Request, handler):
        try:
            return await handler(request)
        except AuthenticationError:
            return web.json_response({"error": "unauthorized"}, status=401)
        except web.HTTPException:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[live-view] request failed {}", request.path)
            return web.json_response({"error": "internal error"}, status=500)

    async def _embed(self, _request: web.Request) -> web.Response:
        return web.Response(text=_HTML.replace("__PARENT__", html.escape(self._settings.live_view_parent_origin, quote=True)), content_type="text/html")

    async def _js(self, _request: web.Request) -> web.Response:
        return web.Response(text=_JS, content_type="text/javascript")

    async def _css(self, _request: web.Request) -> web.Response:
        return web.Response(text=_CSS, content_type="text/css")

    async def _health(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "device_id": self._sessions.device_id})

    def _bearer(self, request: web.Request):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer":
            raise AuthenticationError("missing bearer")
        return self._sessions.require_session(token)

    async def _monitors(self, request: web.Request) -> web.Response:
        session = self._bearer(request)
        monitors = []
        for monitor in self._api.recording.get_monitors():
            if session.monitor_index != monitor.index:
                continue
            path = self._settings.segment_dir / f"m{monitor.index}" / "preview.jpg"
            if path.is_file():
                cap = self._sessions.issue_capability(session, path, "preview")
                monitors.append({"index": monitor.index, "name": monitor.name, "stream_url": f"/stream/{cap}"})
        return web.json_response({"monitors": monitors})

    async def _stream(self, request: web.Request) -> web.StreamResponse:
        capability = self._sessions.require_capability(request.match_info["capability"], "preview")
        with self._viewer_lock:
            if self._viewers >= self._settings.live_view_max_viewers:
                raise web.HTTPTooManyRequests(text="viewer limit reached")
            self._viewers += 1
        response = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=watcher-live-frame", "Cache-Control": "no-store"})
        await response.prepare(request)
        try:
            while True:
                self._sessions.require_capability(request.match_info["capability"], "preview")
                try:
                    frame = capability.target.read_bytes()
                except OSError:
                    await asyncio.sleep(0.1)
                    continue
                if frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9"):
                    await response.write(b"--" + _BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                await asyncio.sleep(0.1)
        except (ConnectionResetError, asyncio.CancelledError, AuthenticationError):
            pass
        finally:
            with self._viewer_lock:
                self._viewers = max(0, self._viewers - 1)
        return response

    async def _events(self, request: web.Request) -> web.WebSocketResponse:
        if request.headers.get("Origin") != self._settings.live_view_origin:
            raise web.HTTPForbidden(text="invalid websocket origin")
        ws = web.WebSocketResponse(max_msg_size=_MAX_WS_MESSAGE, heartbeat=20)
        await ws.prepare(request)
        try:
            first = await asyncio.wait_for(ws.receive_json(), timeout=5)
            if not isinstance(first, dict) or first.get("type") != "auth":
                raise AuthenticationError("first websocket message must authenticate")
            session = self._sessions.open_session(str(first.get("assertion", "")))
            await ws.send_json({"type": "authenticated", "session": session.token, "expires_in": 300})
            async for message in ws:
                if message.type == WSMsgType.TEXT and message.data == '{"type":"ping"}':
                    self._sessions.require_session(session.token)
                    await ws.send_json({"type": "pong"})
                elif message.type == WSMsgType.TEXT:
                    await ws.close(code=1008, message=b"read-only websocket")
        except (AuthenticationError, asyncio.TimeoutError):
            await ws.close(code=1008, message=b"authentication rejected")
        return ws


_HTML = """<!doctype html><html><head><meta charset=\"utf-8\"><link rel=\"stylesheet\" href=\"/embed.css\"></head><body data-parent-origin=\"__PARENT__\"><p id=\"status\" role=\"status\"></p><div id=\"monitors\"></div><script src=\"/embed.js\"></script></body></html>"""
_CSS = "body{margin:0;background:#101827;color:#e5e7eb;font:14px system-ui;padding:10px}.tile{margin:0}.tile img{width:100%;display:block;background:#000}.tile strong{display:block;padding:6px}"
_JS = """(()=>{const parent= document.body.dataset.parentOrigin,status=document.getElementById('status'),root=document.getElementById('monitors');let ws,session;function begin(assertion){if(ws)ws.close();ws=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/events');ws.onopen=()=>ws.send(JSON.stringify({type:'auth',assertion}));ws.onmessage=async e=>{const m=JSON.parse(e.data);if(m.type!=='authenticated')return;session=m.session;const r=await fetch('/api/v1/monitors',{headers:{Authorization:'Bearer '+session},cache:'no-store'});if(!r.ok){status.textContent='No se pudieron abrir los monitores.';return}const d=await r.json();root.replaceChildren(...d.monitors.map(x=>{const a=document.createElement('article'),l=document.createElement('strong'),i=document.createElement('img');a.className='tile';l.textContent=x.name;i.alt=x.name;i.src=x.stream_url;a.append(l,i);return a}));};ws.onclose=()=>{if(!session)status.textContent='Sesión rechazada o vencida.'};}window.addEventListener('message',e=>{if(e.source!==window.parent||e.origin!==parent||!e.data||e.data.type!=='watcher:session'||typeof e.data.assertion!=='string')return;session=null;begin(e.data.assertion)});window.parent.postMessage({type:'watcher:ready'},parent)})();"""
