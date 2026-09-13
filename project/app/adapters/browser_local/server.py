"""TLS loopback HTTP/WSS adapter for the Daily SIG Systems browser iframe.

It intentionally exposes a tiny read-only contract.  It doesn't import or
reuse ``IpcRouter``: the Tauri pipe remains a separate high-privilege channel.
"""
from __future__ import annotations

import asyncio
import html
import json
import ssl
import threading
from pathlib import Path
from typing import Any, Iterable

from aiohttp import WSMsgType, web
from loguru import logger

from app.adapters.browser_local.auth import AuthenticationError, BrowserSession, BrowserSessionManager
from app.adapters.browser_local.identity import DeviceIdentityStore
from app.core.api import dto

_LOOPBACK_HOSTS = ("127.0.0.1", "::1")
_MAX_WS_MESSAGE = 16 * 1024


class BrowserLocalAdapter:
    """Serve an enrolled browser UI over HTTPS/WSS on loopback only."""

    def __init__(self, settings, api_layer, *, clip_roots: Iterable[Path]) -> None:
        self._settings = settings
        self._api = api_layer
        # Keep the filesystem allowlist explicit at the composition root. The
        # browser adapter consumes facade DTOs but never treats ClipsApi's
        # private state as an implicit path authority.
        self._clip_roots = tuple(Path(root).resolve() for root in clip_roots)
        self._identity = DeviceIdentityStore(settings.browser_local_data_dir).load_or_create()
        self._sessions = BrowserSessionManager(
            identity=self._identity,
            issuer=settings.browser_local_issuer,
            audience=settings.browser_local_audience,
            issuer_kid=settings.browser_local_issuer_kid,
            station_id=settings.browser_local_station_id,
            issuer_public_key_file=settings.browser_local_issuer_public_key_file,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runner: web.AppRunner | None = None
        self._stop_event: asyncio.Event | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._running = False
        self._start_error: Exception | None = None
        self._clients: set[web.WebSocketResponse] = set()
        self._subscription = None

    @property
    def base_url(self) -> str:
        return f"https://localhost:{self._settings.browser_local_port}"

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def enrollment_payload(self) -> dict[str, str]:
        return self._identity.enrollment_payload()

    def start(self) -> bool:
        """Start non-blocking; disabled or incomplete configuration fails closed."""
        if self._running:
            return True
        if not self._settings.browser_local_enabled:
            logger.info("[browser-local] disabled (BROWSER_LOCAL_ENABLED is false).")
            return False
        try:
            self._validate_tls_config()
        except Exception as exc:  # noqa: BLE001 -- never leave a plaintext fallback
            logger.error("[browser-local] not started: {}", exc)
            return False

        self._ready.clear()
        self._start_error = None
        self._thread = threading.Thread(target=self._run, name="browser-local", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=8)
        if self._start_error is not None:
            logger.error("[browser-local] failed to start: {}", self._start_error)
            return False
        return self._running

    def stop(self) -> None:
        if self._subscription is not None:
            self._subscription.cancel()
            self._subscription = None
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
        self._running = False
        logger.info("[browser-local] stopped.")

    def _validate_tls_config(self) -> None:
        cert = Path(self._settings.browser_local_cert_file)
        key = Path(self._settings.browser_local_key_file)
        if not cert.is_file() or not key.is_file():
            raise ValueError("BROWSER_LOCAL_CERT_FILE and BROWSER_LOCAL_KEY_FILE must be readable files")
        if not self._settings.browser_local_parent_origin.startswith("https://"):
            raise ValueError("BROWSER_LOCAL_PARENT_ORIGIN must use HTTPS")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as exc:  # noqa: BLE001
            self._start_error = exc
            logger.exception("[browser-local] loop failed")
        finally:
            self._running = False
            self._ready.set()
            self._loop.close()
            self._loop = None

    async def _serve(self) -> None:
        app = web.Application(middlewares=[self._security_headers, self._error_boundary])
        app.add_routes(
            [
                web.get("/", self._root),
                web.get("/embed", self._embed),
                web.get("/embed.js", self._embed_js),
                web.get("/embed.css", self._embed_css),
                web.get("/api/v1/health", self._health),
                web.post("/api/v1/bootstrap/sign", self._sign_challenge),
                web.get("/api/v1/clips", self._list_clips),
                web.get("/api/v1/monitors", self._list_monitors),
                web.get("/media/{capability}", self._media),
                web.get("/preview/{capability}", self._preview),
                web.get("/events", self._events),
            ]
        )
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            certfile=self._settings.browser_local_cert_file,
            keyfile=self._settings.browser_local_key_file,
        )
        sites = [
            web.TCPSite(self._runner, host=host, port=self._settings.browser_local_port, ssl_context=context)
            for host in _LOOPBACK_HOSTS
        ]
        try:
            for site in sites:
                await site.start()
        except Exception:
            await self._runner.cleanup()
            raise

        self._subscription = self._api.bus.subscribe(
            (dto.ClipsChanged, dto.RecordingStateChanged, dto.MonitorsChanged), self._on_bus_event
        )
        self._stop_event = asyncio.Event()
        self._running = True
        logger.info("[browser-local] HTTPS/WSS listening at {}", self.base_url)
        self._ready.set()
        await self._stop_event.wait()
        for client in list(self._clients):
            await client.close(code=1001, message=b"server shutdown")
        await self._runner.cleanup()
        self._runner = None

    @web.middleware
    async def _security_headers(self, request: web.Request, handler):
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            # aiohttp carries redirect/4xx/5xx responses in an exception. Add
            # the policy before re-raising so it preserves normal exception
            # handling (returning it is deprecated by aiohttp).
            self._apply_security_headers(exc)
            raise
        self._apply_security_headers(response)
        return response

    def _apply_security_headers(self, response: web.StreamResponse) -> None:
        response.headers.update(
            {
                "Content-Security-Policy": self._csp(),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                "Cache-Control": "no-store",
            }
        )

    @web.middleware
    async def _error_boundary(self, request: web.Request, handler):
        if not self._is_loopback(request):
            return web.json_response({"error": "loopback only"}, status=403)
        try:
            return await handler(request)
        except AuthenticationError:
            return web.json_response({"error": "unauthorized"}, status=401)
        except web.HTTPException:
            raise
        except Exception:  # noqa: BLE001 -- avoid filesystem/config details in a browser response
            logger.exception("[browser-local] request failed {}", request.path)
            return web.json_response({"error": "internal error"}, status=500)

    def _csp(self) -> str:
        parent = self._settings.browser_local_parent_origin
        return (
            "default-src 'self'; base-uri 'none'; object-src 'none'; "
            f"frame-ancestors {parent}; "
            f"connect-src 'self' wss://localhost:{self._settings.browser_local_port}; "
            "img-src 'self' data:; media-src 'self'; style-src 'self'; script-src 'self'; "
            "form-action 'none'"
        )

    @staticmethod
    def _is_loopback(request: web.Request) -> bool:
        remote = request.remote or ""
        return remote in _LOOPBACK_HOSTS or remote.startswith("::ffff:127.0.0.1")

    async def _root(self, _request: web.Request) -> web.Response:
        raise web.HTTPFound("/embed")

    async def _embed(self, _request: web.Request) -> web.Response:
        parent = html.escape(self._settings.browser_local_parent_origin, quote=True)
        return web.Response(
            text=_EMBED_HTML.replace("__PARENT_ORIGIN__", parent),
            content_type="text/html",
            charset="utf-8",
        )

    async def _embed_js(self, _request: web.Request) -> web.Response:
        return web.Response(text=_EMBED_JS, content_type="text/javascript", charset="utf-8")

    async def _embed_css(self, _request: web.Request) -> web.Response:
        return web.Response(text=_EMBED_CSS, content_type="text/css", charset="utf-8")

    async def _health(self, _request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "device_id": self._sessions.device_id})

    async def _sign_challenge(self, request: web.Request) -> web.Response:
        # Only the child document served by this exact local origin can ask the
        # device to sign a Daily nonce. CORS alone is not authorization.
        if request.headers.get("Origin") != self.base_url:
            raise web.HTTPForbidden(text="invalid bootstrap origin")
        payload = await _json_body(request)
        nonce = payload.get("nonce")
        if not isinstance(nonce, str) or not _valid_nonce(nonce):
            raise web.HTTPBadRequest(text="nonce required")
        return web.json_response(
            {"device_id": self._sessions.device_id, "nonce": nonce, "signature": self._sessions.sign_bootstrap_challenge(nonce)}
        )

    async def _list_clips(self, request: web.Request) -> web.Response:
        session = self._require_bearer(request)
        result = []
        for item in self._api.clips.list_clips():
            path = Path(item.path)
            if not self._is_allowed_clip(path):
                continue
            cap = self._sessions.issue_capability(session, path, "media")
            result.append(
                {
                    "id": cap[:16],
                    "clip_name": item.clip_name,
                    "size_label": item.size_label,
                    "date_label": item.date_label,
                    "is_event": item.is_event,
                    "media_url": f"/media/{cap}",
                }
            )
        return web.json_response({"clips": result})

    async def _list_monitors(self, request: web.Request) -> web.Response:
        session = self._require_bearer(request)
        monitors = []
        for monitor in self._api.recording.get_monitors():
            preview = self._settings.segment_dir / f"m{monitor.index}" / "preview.jpg"
            if not preview.is_file():
                continue
            cap = self._sessions.issue_capability(session, preview, "preview")
            monitors.append(
                {
                    "name": monitor.name,
                    "index": monitor.index,
                    "resolution": monitor.resolution,
                    "preview_url": f"/preview/{cap}",
                }
            )
        return web.json_response({"monitors": monitors})

    async def _media(self, request: web.Request) -> web.StreamResponse:
        capability = self._sessions.require_capability(request.match_info["capability"], "media")
        path = capability.target.resolve()
        if not self._is_allowed_clip(path) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(
            path,
            headers={"Content-Type": "video/mp4", "Content-Disposition": "inline"},
        )

    async def _preview(self, request: web.Request) -> web.StreamResponse:
        capability = self._sessions.require_capability(request.match_info["capability"], "preview")
        path = capability.target.resolve()
        if not self._is_allowed_preview(path) or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"Content-Type": "image/jpeg"})

    async def _events(self, request: web.Request) -> web.WebSocketResponse:
        expected_origin = self.base_url
        if request.headers.get("Origin") != expected_origin:
            raise web.HTTPForbidden(text="invalid websocket origin")
        ws = web.WebSocketResponse(max_msg_size=_MAX_WS_MESSAGE, heartbeat=20)
        await ws.prepare(request)
        try:
            first = await asyncio.wait_for(ws.receive_json(), timeout=5)
            if not isinstance(first, dict) or first.get("type") != "auth":
                raise AuthenticationError("first websocket message must authenticate")
            session = self._sessions.open_session(str(first.get("assertion", "")))
            self._clients.add(ws)
            logger.info("[browser-local] websocket accepted device={}", self._sessions.device_id)
            await ws.send_json({"type": "authenticated", "session": session.token, "expires_in": 300})
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    # This surface has no browser commands. A ping is enough to
                    # keep the authenticated channel observable.
                    try:
                        payload = json.loads(message.data)
                    except json.JSONDecodeError:
                        await ws.close(code=1003, message=b"invalid json")
                        break
                    if payload.get("type") == "ping":
                        self._sessions.require_session(session.token)
                        await ws.send_json({"type": "pong"})
                    else:
                        await ws.close(code=1008, message=b"read-only websocket")
                        break
                elif message.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED):
                    break
        except AuthenticationError as exc:
            logger.warning("[browser-local] websocket rejected device={} reason={}", self._sessions.device_id, exc)
            await ws.close(code=1008, message=b"authentication rejected")
        except asyncio.TimeoutError:
            logger.warning("[browser-local] websocket rejected device={} reason=authentication_timeout", self._sessions.device_id)
            await ws.close(code=1008, message=b"authentication rejected")
        finally:
            self._clients.discard(ws)
        return ws

    def _require_bearer(self, request: web.Request) -> BrowserSession:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer":
            raise AuthenticationError("missing bearer")
        return self._sessions.require_session(token)

    def _is_allowed_clip(self, path: Path) -> bool:
        return path.suffix.lower() == ".mp4" and _inside_any(path, self._clip_roots)

    def _is_allowed_preview(self, path: Path) -> bool:
        return path.name == "preview.jpg" and _inside_any(path, [self._settings.segment_dir])

    def _on_bus_event(self, _event: Any) -> None:
        if self._loop is None or not self._clients:
            return
        # Core events such as ClipsChanged include DTOs containing internal
        # paths. The browser surface needs only invalidation; forwarding the
        # event shape would leak those paths and couple this contract to IPC.
        payload = {"type": "changed"}
        asyncio.run_coroutine_threadsafe(self._broadcast(payload), self._loop)

    async def _broadcast(self, payload: dict[str, Any]) -> None:
        for client in list(self._clients):
            if not client.closed:
                await client.send_json(payload)


def _inside_any(path: Path, roots: Iterable[Path]) -> bool:
    try:
        resolved = path.resolve()
        return any(resolved.is_relative_to(Path(root).resolve()) for root in roots)
    except (OSError, ValueError):
        return False


def _valid_nonce(value: str) -> bool:
    return 24 <= len(value) <= 256 and all(
        character.isascii() and (character.isalnum() or character in "-_") for character in value
    )


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except (json.JSONDecodeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    if not isinstance(value, dict):
        raise web.HTTPBadRequest(text="JSON object required")
    return value


_EMBED_HTML = """<!doctype html>
<html lang=\"es\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>The Watcher</title><link rel=\"stylesheet\" href=\"/embed.css\"></head>
<body data-parent-origin='__PARENT_ORIGIN__'><main><header><h1>The Watcher</h1><p id=\"status\">Conectando con SIG Daily…</p></header><section><h2>Preview en vivo</h2><div id=\"monitors\" class=\"grid\"></div></section><section><h2>Grabaciones</h2><div class=\"content\"><ul id=\"clips\"></ul><video id=\"player\" controls playsinline></video></div></section></main><script src=\"/embed.js\"></script></body></html>"""

_EMBED_CSS = """*{box-sizing:border-box}body{margin:0;background:#101827;color:#e5e7eb;font:14px system-ui,sans-serif}main{padding:16px}h1,h2,p{margin:0}header{margin-bottom:18px}h1{font-size:20px}h2{font-size:16px;margin:20px 0 8px}#status{color:#9ca3af;margin-top:4px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px}.tile,.content{background:#182234;border:1px solid #30415d;border-radius:8px;padding:10px}.tile img{display:block;width:100%;margin-top:6px;background:#090d15}.content{display:grid;grid-template-columns:minmax(180px,1fr) minmax(320px,2fr);gap:12px}ul{list-style:none;margin:0;padding:0;max-height:380px;overflow:auto}button{width:100%;text-align:left;background:transparent;border:0;border-bottom:1px solid #30415d;color:inherit;padding:9px;cursor:pointer}button:hover{background:#263750}video{width:100%;max-height:420px;background:#000}@media(max-width:640px){.content{grid-template-columns:1fr}}"""

_EMBED_JS = """(() => {
  const parentOrigin = document.body.dataset.parentOrigin;
  const status = document.getElementById('status');
  const clips = document.getElementById('clips');
  const monitors = document.getElementById('monitors');
  const player = document.getElementById('player');
  let session = null;
  let refreshTimer = null;
  let refreshTimeout = null;
  let socket = null;
  const setStatus = (message) => { status.textContent = message; };
  const api = async (path, options = {}) => {
    const headers = new Headers(options.headers || {});
    if (session) headers.set('Authorization', `Bearer ${session}`);
    const response = await fetch(path, {...options, headers, cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  };
  const render = async () => {
    const [clipData, monitorData] = await Promise.all([api('/api/v1/clips'), api('/api/v1/monitors')]);
    clips.replaceChildren(...clipData.clips.map((clip) => {
      const button = document.createElement('button');
      button.textContent = `${clip.clip_name} · ${clip.date_label} · ${clip.size_label}`;
      button.onclick = () => { player.src = clip.media_url; player.play().catch(() => {}); };
      const li = document.createElement('li'); li.append(button); return li;
    }));
    monitors.replaceChildren(...monitorData.monitors.map((monitor) => {
      const tile = document.createElement('article'); tile.className = 'tile';
      const label = document.createElement('strong'); label.textContent = `${monitor.name} (${monitor.resolution})`;
      const image = document.createElement('img'); image.alt = label.textContent; image.src = monitor.preview_url;
      tile.append(label, image); return tile;
    }));
  };
  const begin = async (assertion) => {
    if (socket) { socket.close(); socket = null; }
    session = null;
    clearInterval(refreshTimer); refreshTimer = null;
    clearTimeout(refreshTimeout); refreshTimeout = null;
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${location.host}/events`);
    socket = ws;
    ws.onopen = () => ws.send(JSON.stringify({type: 'auth', assertion}));
    ws.onmessage = async (event) => {
      const message = JSON.parse(event.data);
      if (message.type === 'authenticated') {
        session = message.session; setStatus('Conectado'); await render();
        clearInterval(refreshTimer); refreshTimer = setInterval(render, 5000);
        clearTimeout(refreshTimeout); refreshTimeout = setTimeout(() => window.parent.postMessage({type: 'watcher:refresh_required'}, parentOrigin), 240000);
      }
      if (message.type === 'changed' && session) render().catch(() => {});
    };
    ws.onclose = () => { if (socket === ws) { socket = null; if (!session) setStatus('Sesión local rechazada o vencida.'); } };
  };
  window.addEventListener('message', async (event) => {
    if (event.source !== window.parent || event.origin !== parentOrigin || !event.data || typeof event.data.type !== 'string') return;
    if (event.data.type === 'watcher:challenge' && typeof event.data.nonce === 'string') {
      try { const proof = await api('/api/v1/bootstrap/sign', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nonce:event.data.nonce})}); window.parent.postMessage({type:'watcher:proof', ...proof}, parentOrigin); }
      catch { setStatus('No se pudo firmar el enrolamiento local.'); }
    }
    if (event.data.type === 'watcher:session' && typeof event.data.assertion === 'string') begin(event.data.assertion);
  });
  fetch('/api/v1/health', {cache:'no-store'}).then((r) => r.json()).then((health) => window.parent.postMessage({type:'watcher:ready', device_id:health.device_id}, parentOrigin)).catch(() => setStatus('Daemon local no disponible.'));
})();"""
