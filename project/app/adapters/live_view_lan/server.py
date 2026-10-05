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
from contextlib import suppress
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, WSMsgType, web
from loguru import logger

from app.adapters.browser_local.auth import AuthenticationError, BrowserSessionManager
from app.adapters.browser_local.identity import DeviceIdentityStore
from app.adapters.live_view_lan.h264_feed import (
    KIND_DELTA, KIND_JPEG, KIND_KEY, FeedConfig, H264Hub, H264Subscriber, MonitorSpec,
    default_candidates, parse_resolution,
)
from app.core.ports.live_view_port import LiveViewPort

_MAX_WS_MESSAGE = 16 * 1024
_BOUNDARY = b"watcher-live-frame"
# Poll the preview file's stat (cheap) and only read/send a JPEG when it changed.
_FRAME_POLL_SECONDS = 0.1
# Resend an unchanged frame this often so a static screen still proves liveness.
_KEEPALIVE_SECONDS = 5.0
# How often the WebSocket pump re-reads the monitor list (hot-plugged displays).
_MONITOR_REFRESH_SECONDS = 5.0
# A subscribe may name the monitors it wants (Daily opens one iframe per screen).
_MAX_REQUESTED_MONITORS = 16


def _requested_monitors(command: dict) -> "set[int] | None":
    """Monitors a ``subscribe`` asked for, or None for every monitor (also on bad input)."""
    raw = command.get("monitors")
    if not isinstance(raw, list) or not 0 < len(raw) <= _MAX_REQUESTED_MONITORS:
        return None
    if not all(type(i) is int and 0 <= i < 256 for i in raw):
        return None
    return set(raw)


# Pending H.264 items per viewer before it is considered too slow and resyncs.
_VIDEO_QUEUE = 240


class _FrameGate:
    """Decides when the preview JPEG must be (re)sent to one viewer."""

    def __init__(self, keepalive_seconds: float) -> None:
        self._keepalive = keepalive_seconds
        self._sent_signature: tuple[int, int] | None = None
        self._sent_at = 0.0

    def should_send(self, signature: tuple[int, int], now: float) -> bool:
        return signature != self._sent_signature or now - self._sent_at >= self._keepalive

    def mark_sent(self, signature: tuple[int, int], now: float) -> None:
        self._sent_signature = signature
        self._sent_at = now


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
        # A viewer is an authenticated supervisor (assertion subject), not one
        # session or monitor stream. One supervisor may open every monitor.
        self._viewer_streams: dict[str, int] = {}
        self._viewer_lock = threading.Lock()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._hub: H264Hub | None = None

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
        return self._start_error is None and self._running

    def stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None
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
        self._hub = self._make_hub(asyncio.get_running_loop())
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._ready.set()
        logger.info("[live-view] listening at {}", self._settings.live_view_origin)
        await self._stop_event.wait()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._heartbeat_task
            self._heartbeat_task = None
        if self._hub is not None:
            self._hub.shutdown()
            self._hub = None
        await self._runner.cleanup()

    def _make_hub(self, loop: asyncio.AbstractEventLoop) -> H264Hub | None:
        if getattr(self._settings, "live_view_transport", "h264") != "h264":
            return None
        from app.adapters.ffmpeg import encoder_selector  # noqa: PLC0415
        from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg  # noqa: PLC0415

        cfg = FeedConfig(
            ffmpeg=resolve_ffmpeg(),
            fps=max(1, getattr(self._settings, "live_view_video_fps", 24)),
            width=max(320, getattr(self._settings, "live_view_video_width", 1280)),
            kbps=max(200, getattr(self._settings, "live_view_video_kbps", 3000)),
        )
        return H264Hub(loop, cfg, default_candidates(lambda: encoder_selector.get_encoder("h264", realtime=True)[0]))

    async def _heartbeat_loop(self) -> None:
        """Publish a signed, non-media status signal for Daily's roster."""
        if not self._settings.live_view_heartbeat_url:
            logger.warning("[live-view] heartbeat URL is not configured")
            return
        interval = max(10, self._settings.live_view_heartbeat_seconds)
        async with ClientSession() as client:
            while True:
                try:
                    state = self._api.recording.get_recording_state()
                    monitors = [m.index for m in self._api.recording.get_monitors()]
                    recording_state = "recording" if state.is_recording else "stopped"
                    timestamp = int(time.time())
                    canonical = ":".join((
                        self._identity.device_id, str(timestamp), self._settings.live_view_origin,
                        recording_state, "ok", ",".join(str(index) for index in monitors),
                    ))
                    payload = {
                        "device_id": self._identity.device_id, "timestamp": timestamp,
                        "live_origin": self._settings.live_view_origin, "recording_state": recording_state,
                        "health": "ok", "monitor_indexes": monitors,
                        "signature": self._identity.sign_live_heartbeat(canonical),
                    }
                    async with client.post(self._settings.live_view_heartbeat_url, json=payload, timeout=10) as response:
                        if response.status != 200:
                            detail = (await response.text())[:512]
                            logger.warning("[live-view] heartbeat rejected status={} detail={}", response.status, detail)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # daemon recording must survive transient Daily/LAN failures
                    logger.warning("[live-view] heartbeat failed: {}", exc)
                await asyncio.sleep(interval)

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

    def _claim_viewer(self, viewer: str) -> bool:
        """Take (or share) the slot of a supervisor identity; False when full."""
        with self._viewer_lock:
            if viewer not in self._viewer_streams and len(self._viewer_streams) >= self._settings.live_view_max_viewers:
                return False
            self._viewer_streams[viewer] = self._viewer_streams.get(viewer, 0) + 1
            return True

    def _release_viewer(self, viewer: str) -> None:
        with self._viewer_lock:
            remaining = self._viewer_streams.get(viewer, 1) - 1
            if remaining > 0:
                self._viewer_streams[viewer] = remaining
            else:
                self._viewer_streams.pop(viewer, None)

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
            path = self._settings.segment_dir / f"m{monitor.index}" / "preview.jpg"
            if path.is_file():
                cap = self._sessions.issue_capability(session, path, "preview")
                monitors.append({"index": monitor.index, "name": monitor.name, "stream_url": f"/stream/{cap}"})
        return web.json_response({"monitors": monitors})

    async def _stream(self, request: web.Request) -> web.StreamResponse:
        # The capability only authorises *opening* the stream (30 s TTL). Once
        # open, its life is bounded by the session (renewed by the embed page);
        # re-checking the capability per frame killed every stream after 30 s.
        capability = self._sessions.require_capability(request.match_info["capability"], "preview")
        # A viewer is a supervisor identity. Reloads, extra tabs and session
        # renewals each open a new session for the same supervisor and must
        # share one slot, otherwise stale sessions exhaust the limit.
        viewer = self._sessions.require_session(capability.session_token).subject
        if not self._claim_viewer(viewer):
            raise web.HTTPTooManyRequests(text="viewer limit reached")
        response = web.StreamResponse(headers={"Content-Type": "multipart/x-mixed-replace; boundary=watcher-live-frame", "Cache-Control": "no-store"})
        await response.prepare(request)
        gate = _FrameGate(_KEEPALIVE_SECONDS)
        try:
            while True:
                self._sessions.require_session(capability.session_token)
                try:
                    stat = capability.target.stat()
                    signature = (stat.st_mtime_ns, stat.st_size)
                    if gate.should_send(signature, time.monotonic()):
                        frame = capability.target.read_bytes()
                        if frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9"):
                            await response.write(b"--" + _BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                            gate.mark_sent(signature, time.monotonic())
                except OSError:
                    pass  # ffmpeg is mid-rewrite; retry on the next poll
                await asyncio.sleep(_FRAME_POLL_SECONDS)
        except AuthenticationError as exc:
            logger.info("[live-view] stream closed: {}", exc)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._release_viewer(viewer)
        return response

    async def _pump_frames(self, ws: web.WebSocketResponse, session_token: str, *,
                           out: "asyncio.Queue[tuple[str, Any]] | None" = None,
                           jpeg_monitors: "set[int] | None" = None,
                           only: "set[int] | None" = None) -> None:
        """Serve one viewer over its single WebSocket.

        Every binary frame is ``[kind][monitor index][payload]`` (kind 0 = JPEG,
        1/2 = H.264 key/delta access unit). JPEGs come from the recorder's
        preview files for ``jpeg_monitors`` (None = every monitor), only when
        they changed; H.264 and control messages arrive through ``out``.
        One connection per tab: browsers cap HTTP/1.1 at 6 per host, and one
        endless image stream per monitor starved other tabs.
        """
        gates: dict[int, _FrameGate] = {}
        paths: dict[int, Path] = {}
        refreshed = float("-inf")
        try:
            while not ws.closed:
                self._sessions.require_session(session_token)
                now = time.monotonic()
                if now - refreshed >= _MONITOR_REFRESH_SECONDS:
                    paths = {
                        m.index: self._settings.segment_dir / f"m{m.index}" / "preview.jpg"
                        for m in self._api.recording.get_monitors() if 0 <= m.index < 256
                    }
                    refreshed = now
                for index, path in paths.items():
                    if only is not None and index not in only:
                        continue
                    if jpeg_monitors is not None and index not in jpeg_monitors:
                        continue
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    signature = (stat.st_mtime_ns, stat.st_size)
                    gate = gates.setdefault(index, _FrameGate(_KEEPALIVE_SECONDS))
                    if not gate.should_send(signature, now):
                        continue
                    try:
                        frame = path.read_bytes()
                    except OSError:
                        continue  # ffmpeg is mid-rewrite; retry on the next poll
                    if frame.startswith(b"\xff\xd8") and frame.endswith(b"\xff\xd9"):
                        await ws.send_bytes(bytes((KIND_JPEG, index)) + frame)
                        gate.mark_sent(signature, time.monotonic())
                if out is None:
                    await asyncio.sleep(_FRAME_POLL_SECONDS)
                    continue
                try:
                    item = await asyncio.wait_for(out.get(), timeout=_FRAME_POLL_SECONDS)
                except asyncio.TimeoutError:
                    continue
                while True:
                    kind, payload = item
                    if kind == "json":
                        await ws.send_json(payload)
                    else:
                        await ws.send_bytes(payload)
                    if out.empty():
                        break
                    item = out.get_nowait()
        except AuthenticationError as exc:
            logger.info("[live-view] stream closed: {}", exc)
            await ws.close(code=1008, message=b"session expired")
        except ConnectionResetError:
            pass

    def _h264_subscribers(self, out: "asyncio.Queue[tuple[str, Any]]", jpeg_monitors: set[int],
                          only: "set[int] | None" = None) -> "list[tuple[int, H264Subscriber]]":
        """Subscribe one viewer to the shared H.264 feed of every monitor (or only ``only``)."""
        subs: list[tuple[int, H264Subscriber]] = []

        def put(item: tuple[str, Any]) -> None:
            try:
                out.put_nowait(item)
            except asyncio.QueueFull:  # viewer too slow: drop the backlog, resume at the next key frame
                while not out.empty():
                    out.get_nowait()
                for _, sub in subs:
                    sub.need_key = True

        def make(monitor_index: int) -> H264Subscriber:
            def on_config(i: int, codec: str) -> None:
                put(("json", {"type": "video_config", "monitor": i, "codec": codec}))

            def on_au(i: int, key: bool, data: bytes) -> None:
                put(("bin", bytes((KIND_KEY if key else KIND_DELTA, i)) + data))

            def on_failed(i: int) -> None:  # no encoder worked: serve this monitor as JPEG instead
                jpeg_monitors.add(i)
                put(("json", {"type": "video_config", "monitor": i, "codec": "mjpeg"}))

            return H264Subscriber(on_config, on_au, on_failed)

        for monitor in self._api.recording.get_monitors():
            if not 0 <= monitor.index < 256 or (only is not None and monitor.index not in only):
                continue
            width, height = parse_resolution(getattr(monitor, "resolution", ""))
            spec = MonitorSpec(monitor.index, getattr(monitor, "x", 0), getattr(monitor, "y", 0), width, height)
            sub = make(monitor.index)
            subs.append((monitor.index, sub))
            self._hub.subscribe(spec, sub)
        return subs

    async def _events(self, request: web.Request) -> web.WebSocketResponse:
        if request.headers.get("Origin") != self._settings.live_view_origin:
            raise web.HTTPForbidden(text="invalid websocket origin")
        ws = web.WebSocketResponse(max_msg_size=_MAX_WS_MESSAGE, heartbeat=20)
        await ws.prepare(request)
        pump: asyncio.Task[None] | None = None
        claimed: str | None = None
        subs: list[tuple[int, H264Subscriber]] = []
        try:
            first = await asyncio.wait_for(ws.receive_json(), timeout=5)
            if not isinstance(first, dict) or first.get("type") != "auth":
                raise AuthenticationError("first websocket message must authenticate")
            session = self._sessions.open_session(str(first.get("assertion", "")))
            await ws.send_json({"type": "authenticated", "session": session.token, "expires_in": 300})
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    command = json.loads(message.data)
                except ValueError:
                    command = None
                kind = command.get("type") if isinstance(command, dict) else None
                if kind == "ping":
                    self._sessions.require_session(session.token)
                    await ws.send_json({"type": "pong"})
                elif kind == "subscribe":
                    if pump is not None:
                        continue
                    self._sessions.require_session(session.token)
                    if not self._claim_viewer(session.subject):
                        await ws.send_json({"type": "error", "reason": "viewer limit reached"})
                        await ws.close(code=1013, message=b"viewer limit reached")
                        break
                    claimed = session.subject
                    out = jpeg_monitors = None
                    only = _requested_monitors(command)
                    if command.get("codec") == "h264" and self._hub is not None:
                        out, jpeg_monitors = asyncio.Queue(maxsize=_VIDEO_QUEUE), set()
                        subs = self._h264_subscribers(out, jpeg_monitors, only)
                    pump = asyncio.create_task(self._pump_frames(ws, session.token, out=out, jpeg_monitors=jpeg_monitors, only=only))
                else:
                    await ws.close(code=1008, message=b"read-only websocket")
        except (AuthenticationError, asyncio.TimeoutError) as exc:
            # Reason only — never the assertion itself.
            logger.warning("[live-view] session rejected: {}", exc or type(exc).__name__)
            await ws.close(code=1008, message=b"authentication rejected")
        finally:
            for index, sub in subs:
                self._hub.unsubscribe(index, sub)
            if pump is not None:
                pump.cancel()
                with suppress(asyncio.CancelledError):
                    await pump
            if claimed is not None:
                self._release_viewer(claimed)
        return ws


_HTML = """<!doctype html><html><head><meta charset=\"utf-8\"><link rel=\"stylesheet\" href=\"/embed.css\"></head><body data-parent-origin=\"__PARENT__\"><p id=\"status\" role=\"status\"></p><div id=\"monitors\"></div><script src=\"/embed.js\"></script></body></html>"""
_CSS = "body{margin:0;background:#101827;color:#e5e7eb;font:14px system-ui;padding:10px}.tile{margin:0}.tile canvas{width:100%;display:block;background:#000}.tile strong{display:block;padding:6px}html:has(body.single),body.single{height:100%;overflow:hidden}body.single{padding:0}body.single .tile strong{display:none}body.single .tile canvas{height:100vh;object-fit:contain}"
_JS = """(()=>{
const parent=document.body.dataset.parentOrigin,status=document.getElementById('status'),root=document.getElementById('monitors');
const canVideo=typeof VideoDecoder==='function'&&typeof EncodedVideoChunk==='function';
let ws,session,renew,jpeg=false;
const want=(()=>{const v=new URLSearchParams(location.search).get('monitor');return v!==null&&/^[0-9]{1,3}$/.test(v)&&Number(v)<256?Number(v):null})();
document.body.classList.toggle('single',want!==null);
function again(ms){clearTimeout(renew);renew=setTimeout(()=>window.parent.postMessage({type:'watcher:ready'},parent),ms)}
function begin(assertion){
if(ws)ws.close();clearTimeout(renew);
const mine=ws=new WebSocket((location.protocol==='https:'?'wss:':'ws:')+'//'+location.host+'/events'),tiles=new Map(),decs=new Map();
mine.binaryType='arraybuffer';
const draw=(c,src,w,h)=>{if(c.width!==w||c.height!==h){c.width=w;c.height=h}c.getContext('2d').drawImage(src,0,0)};
const fallback=()=>{if(mine!==ws||jpeg)return;jpeg=true;status.textContent='Video no disponible; usando imágenes.';again(0)};
function video(i,codec){
const c=tiles.get(i),old=decs.get(i);if(old&&old.d.state!=='closed')old.d.close();decs.delete(i);
if(!c||codec==='mjpeg')return;
const d=new VideoDecoder({output:f=>{draw(c,f,f.displayWidth,f.displayHeight);f.close()},error:fallback});
try{d.configure({codec,optimizeForLatency:true,avc:{format:'annexb'}})}catch(_){fallback();return}
decs.set(i,{d,n:0,synced:false})}
mine.onopen=()=>mine.send(JSON.stringify({type:'auth',assertion}));
mine.onmessage=async e=>{
if(typeof e.data!=='string'){
const b=new Uint8Array(e.data),k=b[0],i=b[1],c=tiles.get(i);if(!c||mine!==ws)return;
if(k===0){const n=c._n=(c._n||0)+1;createImageBitmap(new Blob([b.subarray(2)],{type:'image/jpeg'})).then(x=>{if(n>=(c._drawn||0)){c._drawn=n;draw(c,x,x.width,x.height)}x.close()},()=>{});return}
const s=decs.get(i);if(!s||s.d.state!=='configured')return;
if(k===1)s.synced=true;
if(s.d.decodeQueueSize>12&&k!==1)s.synced=false;
if(!s.synced)return;
try{s.d.decode(new EncodedVideoChunk({type:k===1?'key':'delta',timestamp:(s.n++)*41667,data:b.subarray(2)}))}catch(_){fallback()}
return}
const m=JSON.parse(e.data);
if(m.type==='video_config'){video(m.monitor,m.codec);return}
if(m.type==='error'){status.textContent=m.reason==='viewer limit reached'?'Límite de visores alcanzado.':'Error de supervisión.';return}
if(m.type!=='authenticated')return;
session=m.session;
const r=await fetch('/api/v1/monitors',{headers:{Authorization:'Bearer '+session},cache:'no-store'});
if(!r.ok){status.textContent='No se pudieron abrir los monitores.';again(5000);return}
const d=await r.json();status.textContent='';
const shown=want===null?d.monitors:d.monitors.filter(x=>x.index===want);
if(want!==null&&!shown.length)status.textContent='Pantalla no disponible.';
root.replaceChildren(...shown.map(x=>{const a=document.createElement('article'),l=document.createElement('strong'),c=document.createElement('canvas');a.className='tile';l.textContent=x.name;c.setAttribute('role','img');c.setAttribute('aria-label',x.name);tiles.set(x.index,c);a.append(l,c);return a}));
const only=want===null?{}:{monitors:[want]};
if(mine===ws)mine.send(JSON.stringify(jpeg||!canVideo?{type:'subscribe',...only}:{type:'subscribe',codec:'h264',...only}));
again(Math.max(10,(m.expires_in||300)-60)*1000)};
mine.onclose=()=>{if(!session&&ws===mine)status.textContent='Sesión rechazada o vencida.'}}
window.addEventListener('message',e=>{if(e.source!==window.parent||e.origin!==parent||!e.data||e.data.type!=='watcher:session'||typeof e.data.assertion!=='string')return;session=null;begin(e.data.assertion)});
window.parent.postMessage({type:'watcher:ready'},parent)})();"""
