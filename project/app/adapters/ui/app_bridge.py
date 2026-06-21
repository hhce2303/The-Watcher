from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from loguru import logger

from PySide6.QtCore import QObject, QTimer, Property, Signal, Slot

from app.core.recording_service.service import RecordingService
from app.core.recording_service.models import MonitorInfo
from app.core.monitor_detection.service import MonitorDetectionService
from app.core.event_service import EventService
from app.core.player.player_service import PlayerService
from app.adapters.ui.log_handler import emitter as log_emitter
from app.adapters.ui.screenshot_provider import MonitorScreenshotProvider
from app.core.ports.request_port import ClipRequest, RequestPort
from app.core.ports.user_config_port import UserConfigPort


def _fmt_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes //= 1024
    return f"{size_bytes:.0f} TB"


class AppBridge(QObject):
    """
    Single Python ↔ QML contract.

    Architectural role
    ------------------
    The UI *observes* service state — it does not drive it.

    - Monitor list comes from MonitorDetectionService (not from the adapter directly).
    - toggleMonitor() changes *clip selection* only — it never starts/stops recording.
    - Recording state is polled from RecordingService every second.
    - New/removed monitors are pushed in from the detection service via a
      thread-safe signal bridge so Qt's main thread always owns QML state.
    """

    # ── Change notifications (QML-facing) ─────────────────────────────
    isRecordingChanged     = Signal()
    recordSecChanged       = Signal()
    monitorsChanged        = Signal()
    clipsChanged           = Signal()
    eventCountChanged      = Signal()
    currentClipPathChanged = Signal()
    currentClipInfoChanged = Signal()
    previewRevisionChanged = Signal()

    # ── One-way signals to QML ────────────────────────────────────────
    recordingFailed   = Signal(str)
    clipFailed        = Signal(str)
    logMessage        = Signal(str)
    requestShowWindow = Signal()

    # ── Request system ────────────────────────────────────────────────
    # IT: new incoming request arrived from a Supervisor
    requestReceived        = Signal()
    # Supervisor: a previously sent request changed status
    requestStatusChanged   = Signal(str, str)   # (id, status)

    # ── Private thread-bridge signals ─────────────────────────────────
    _monitors_from_service = Signal(object)   # List[MonitorInfo] — detection thread → main

    def __init__(
        self,
        recording_service:  RecordingService,
        event_service:      EventService,
        detection_service:  MonitorDetectionService,
        player_service:     PlayerService,
        clips_dir:          Path,
        user_config_port:   UserConfigPort | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)

        self._recording_service = recording_service
        self._event_service     = event_service
        self._detection_service = detection_service
        self._player_service    = player_service
        self._clips_dir         = clips_dir
        self._user_config_port  = user_config_port

        # QVideoSink registry — populated by registerVideoSink() called from QML.
        self._video_sinks: dict[int, object] = {}

        # Preview JPEG paths written by the recorder (filter_complex split).
        # Polled every 500 ms to push fresh frames to VideoSinks.
        self._preview_paths: dict[int, Path] = {}
        self._preview_mtimes: dict[int, float] = {}

        # Preview poll timer (reads JPEG files written by the recorder)
        self._preview_poll_timer = QTimer(self)
        self._preview_poll_timer.setInterval(500)   # 500 ms ≈ 2 fps
        self._preview_poll_timer.timeout.connect(self._poll_preview_files)
        self._preview_poll_timer.start()

        # Backing state
        self._is_recording:    bool  = False
        self._record_sec:      int   = 0
        self._event_count:     int   = 0
        self._current_clip_path: str = ""
        self._current_clip_info: dict = {}
        self._preview_revision: int  = 0

        # Monitor state — seeded from detection service (already ran detect_now())
        # and from the persisted clip-selection so the UI matches what
        # RecordingService was initialised with in main.py (survives restart).
        self._all_monitors: List[MonitorInfo] = detection_service.get_monitors()
        saved_fps: set[str] = set()
        if user_config_port is not None:
            try:
                saved_fps = set(user_config_port.load().selected_monitor_fingerprints)
            except Exception:  # noqa: BLE001
                logger.warning("Failed to load saved monitor selection.")
        self._selected_fingerprints: set[str] = saved_fps
        self._sync_selection()

        # Thread-bridge: detection thread → Qt main thread
        self._monitors_from_service.connect(self._apply_monitors_from_service)

        # Request system (populated by main.py via set_request_system())
        self._request_adapter: RequestPort | None = None
        self._request_server  = None   # ClipRequestServer (IT role)
        self._request_client  = None   # ClipRequestClient (Supervisor role)
        self._slc_storage_host: str = ""

        # Clip list
        self._clips: list[dict] = []
        self.refreshClips()

        # Image provider — frames pushed by MonitorPreviewService
        self.screenshot_provider = MonitorScreenshotProvider()

        # Forward loguru → QML
        log_emitter.log_record.connect(self.logMessage)

        # 1 s polling timer (recording state)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    # ── Detection service callback (called from detection thread) ─────

    def on_monitors_updated(self, monitors: List[MonitorInfo]) -> None:
        """Called by MonitorDetectionService on any monitor change.

        Runs on the detection service thread — marshals to Qt main thread
        via the queued signal bridge before touching QML-visible state.
        """
        self._monitors_from_service.emit(monitors)

    def _apply_monitors_from_service(self, monitors: object) -> None:
        """Runs in Qt main thread — safe to update QML-visible properties."""
        monitor_list: List[MonitorInfo] = list(monitors)  # type: ignore[arg-type]
        self._all_monitors = monitor_list
        self._sync_selection()
        self.monitorsChanged.emit()
        logger.debug(
            "AppBridge: monitor list refreshed from detection service ({} monitors).",
            len(monitor_list),
        )

    # ── Internal helpers ──────────────────────────────────────────────

    def _sync_selection(self) -> None:
        """Keep clip-selection fingerprints valid against the current monitor list."""
        valid_fps = {m.fingerprint for m in self._all_monitors}
        self._selected_fingerprints &= valid_fps
        if not self._selected_fingerprints and self._all_monitors:
            primary = next((m for m in self._all_monitors if m.is_primary), None)
            self._selected_fingerprints = {
                (primary or self._all_monitors[0]).fingerprint
            }

    def _apply_clip_selection(self) -> None:
        selected = [
            m for m in self._all_monitors
            if m.fingerprint in self._selected_fingerprints
        ]
        if selected:
            self._recording_service.change_monitors(selected)

    def _persist_selection(self) -> None:
        """Persist the clip-selection to user_config.json so it survives restart.

        Load → mutate → save (the same single-source-of-truth pattern as
        SettingsBridge) to avoid clobbering other persisted preferences.
        """
        if self._user_config_port is None:
            return
        try:
            cfg = self._user_config_port.load()
            cfg.selected_monitor_fingerprints = sorted(self._selected_fingerprints)
            self._user_config_port.save(cfg)
            logger.debug(
                "Persisted monitor selection: {}", cfg.selected_monitor_fingerprints
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to persist monitor selection.")

    def _poll(self) -> None:
        recording = self._recording_service.is_recording()
        if recording != self._is_recording:
            self._is_recording = recording
            self.isRecordingChanged.emit()
        if recording:
            new_sec = int(self._recording_service.total_stored_duration_seconds())
            if new_sec != self._record_sec:
                self._record_sec = new_sec
                self.recordSecChanged.emit()

    def on_preview_frame(self, monitor_idx: int, jpeg_bytes: bytes) -> None:
        """No-op — preview now comes from the file poll timer, not callbacks."""
        pass

    @Slot(int, 'QObject*')
    def registerVideoSink(self, monitor_idx: int, sink: object) -> None:
        """Called from QML VideoOutput.Component.onCompleted to register the sink."""
        self._video_sinks[monitor_idx] = sink
        logger.debug("Preview VideoSink registered for monitor idx={}.", monitor_idx)

    def set_preview_paths(self, paths: dict) -> None:
        """Called from main.py with the JPEG paths written by the recorder."""
        self._preview_paths = {int(k): Path(v) for k, v in paths.items()}
        logger.info("Preview paths set: {}", {k: str(v) for k, v in self._preview_paths.items()})

    def _poll_preview_files(self) -> None:
        """Read recorder-written preview JPEGs and push to VideoSinks.

        Called by QTimer every 500 ms on the Qt main thread.
        The recorder writes preview.jpg at 2 fps via filter_complex split —
        the SAME FFmpeg process as the recording, so no double-capture and
        no screen flickering.
        """
        from PySide6.QtGui import QImage          # noqa: PLC0415
        from PySide6.QtMultimedia import QVideoFrame  # noqa: PLC0415

        for monitor_idx, path in self._preview_paths.items():
            try:
                if not path.exists():
                    continue
                mtime = path.stat().st_mtime
                if mtime == self._preview_mtimes.get(monitor_idx):
                    continue  # file unchanged since last poll — skip
                self._preview_mtimes[monitor_idx] = mtime

                img = QImage(str(path))
                if img.isNull():
                    continue

                sink = self._video_sinks.get(monitor_idx)
                if sink is not None:
                    sink.setVideoFrame(QVideoFrame(img))
            except Exception:
                pass  # tolerate transient file-lock during FFmpeg write

    # ── Old preview-frame callback (kept for backward compat, no-op now) ──
    def on_preview_frame(self, monitor_idx: int, jpeg_bytes: bytes) -> None:
        pass  # preview now comes from file poll, not from a callback

    # ── Properties (QML-facing) ───────────────────────────────────────

    @Property(bool, notify=isRecordingChanged)
    def isRecording(self) -> bool:
        return self._is_recording

    @Property(int, notify=recordSecChanged)
    def recordSec(self) -> int:
        return self._record_sec

    @Property('QVariantList', notify=monitorsChanged)
    def monitors(self) -> list:
        from PySide6.QtGui import QGuiApplication  # noqa: PLC0415
        qt_screens = QGuiApplication.screens()

        def _qt_idx(mon_x: int, mon_y: int) -> int:
            for i, s in enumerate(qt_screens):
                g = s.geometry()
                if abs(g.x() - mon_x) < 8 and abs(g.y() - mon_y) < 8:
                    return i
            return -1

        result = []
        for m in self._all_monitors:
            qt_idx = _qt_idx(m.x, m.y)
            result.append({
                'name':        m.display_name,
                'deviceName':  m.name,
                'qtIdx':       qt_idx,
                'res':         f'{m.width}×{m.height}',
                'active':      m.fingerprint in self._selected_fingerprints,
                'fingerprint': m.fingerprint,
                'idx':         m.index,
                'x':           m.x,
                'y':           m.y,
            })
        return result

    @Property('QVariantList', notify=clipsChanged)
    def clips(self) -> list:
        return self._clips

    @Property(int, notify=eventCountChanged)
    def eventCount(self) -> int:
        return self._event_count

    @Property(str, notify=currentClipPathChanged)
    def currentClipPath(self) -> str:
        return self._current_clip_path

    @Property('QVariantMap', notify=currentClipInfoChanged)
    def currentClipInfo(self) -> dict:
        return self._current_clip_info

    @Property(int, notify=previewRevisionChanged)
    def previewRevision(self) -> int:
        return self._preview_revision

    # ── Slots (QML → Python) ──────────────────────────────────────────

    @Slot()
    def triggerEvent(self) -> None:
        accepted = self._event_service.trigger_manual_event()
        if accepted:
            self._event_count += 1
            self.eventCountChanged.emit()
            logger.info("Manual event accepted.")
        else:
            logger.info("Manual event rejected — cooldown active.")

    @Slot(str)
    def toggleMonitor(self, fingerprint: str) -> None:
        """Toggle clip-selection for a monitor. Does NOT affect recording."""
        if fingerprint in self._selected_fingerprints:
            if len(self._selected_fingerprints) > 1:
                self._selected_fingerprints.discard(fingerprint)
            else:
                return  # always keep ≥1 selected
        else:
            self._selected_fingerprints.add(fingerprint)
        self._apply_clip_selection()
        self._persist_selection()
        self.monitorsChanged.emit()

    @Slot()
    def refreshClips(self) -> None:
        clips = []
        if self._clips_dir.exists():
            files = sorted(
                self._clips_dir.glob('*.mp4'),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for f in files[:100]:
                is_event = '_event' in f.stem
                mtime    = datetime.fromtimestamp(f.stat().st_mtime)
                today    = datetime.now().date()
                yesterday = today.replace(day=today.day - 1) if today.day > 1 else today
                if mtime.date() == today:
                    date_label = 'Hoy'
                elif mtime.date() == yesterday:
                    date_label = 'Ayer'
                else:
                    date_label = (
                        mtime.strftime('%-d %b')
                        if os.name != 'nt'
                        else mtime.strftime('%#d %b')
                    )
                size_mb = f.stat().st_size / (1024 * 1024)
                clips.append({
                    'clipName': f.name,
                    'path':     str(f),
                    'dur':      f'{size_mb:.0f} MB',
                    'date':     date_label,
                    'isEvent':  is_event,
                })
        self._clips = clips
        self.clipsChanged.emit()

    @Slot(str, result=str)
    def mediaUrl(self, path: str) -> str:
        """Convert a local or UNC file path to a proper media URL.

        Uses QUrl.fromLocalFile which correctly handles UNC paths:
          \\\\server\\share\\file.mkv  →  file://server/share/file.mkv
          C:\\path\\file.mp4           →  file:///C:/path/file.mp4
        """
        from PySide6.QtCore import QUrl  # noqa: PLC0415
        return QUrl.fromLocalFile(path).toString()

    @Slot(str)
    def loadClip(self, path: str) -> None:
        if not path:
            self._current_clip_path = ""
            self.currentClipPathChanged.emit()
            return
        p = Path(path)
        # For network UNC paths, skip exists() check (may be slow / require auth)
        # The player will surface an error if the file is unreachable.
        is_unc = path.startswith("\\\\") or path.startswith("//")
        if not is_unc and not p.exists():
            return
        self._current_clip_path = str(p)
        self.currentClipPathChanged.emit()
        try:
            info = self._player_service.load(p)
            self._current_clip_info = {
                'resolution': f'{info.width}×{info.height}' if info else '',
                'codec':      info.codec if info else '',
                'fps':        str(info.fps) if info else '',
                'bitrate':    f'{info.bitrate_kbps} kbps' if info else '',
            }
        except Exception:
            self._current_clip_info = {}
        self.currentClipInfoChanged.emit()

    # UNC servers that have already been authenticated this session
    _unc_authenticated: set[str] = set()

    def _unc_connect(self, server: str) -> None:
        """Authenticate a UNC server via IPC$ using stored NAS credentials.

        ``\\server\\IPC$`` is the standard Windows null-session endpoint used
        to authenticate all subsequent access to that server.
        The password is NEVER logged.
        """
        import subprocess  # noqa: PLC0415
        from app.infrastructure.config import get_settings  # noqa: PLC0415
        settings = get_settings()
        if not settings.nas_username:
            logger.debug("No NAS_USERNAME configured — skipping net use for {}", server)
            return
        try:
            ipc = f"{server}\\IPC$"
            cmd = [
                "net", "use", ipc,
                f"/user:{settings.nas_username}",
                settings.nas_password,
                "/persistent:no",
            ]
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                logger.info("ClipBrowser: authenticated {} as '{}'.", server, settings.nas_username)
            else:
                err = result.stderr.decode("utf-8", errors="replace").strip()
                logger.warning("ClipBrowser: net use {} failed (rc={}) — {}",
                               ipc, result.returncode, err[:300])
        except Exception:
            logger.exception("ClipBrowser: error connecting to {}.", server)

    def _list_unc_server(self, server: str) -> list:
        """Enumerate shares on a UNC server using 'net view'.

        Windows does NOT allow os.scandir on a bare server path (\\\\server).
        'net view \\\\server' is the correct API for listing available shares.
        Hidden shares (ending in $) are excluded.
        """
        import subprocess  # noqa: PLC0415
        try:
            result = subprocess.run(
                ["net", "view", server],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                err = result.stderr.decode("utf-8", errors="replace").strip()
                logger.warning("ClipBrowser: net view {} failed — {}", server, err[:200])
                return []

            shares: list[dict] = []
            in_list = False
            for line in result.stdout.decode("utf-8", errors="replace").splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("---"):
                    in_list = True
                    continue
                if not in_list:
                    continue
                # First word of the line is the share name
                parts = stripped.split()
                if not parts:
                    continue
                share_name = parts[0]
                if share_name.endswith("$"):
                    continue  # skip hidden/admin shares
                shares.append({
                    "name":     share_name,
                    "path":     f"{server}\\{share_name}",
                    "isDir":    True,
                    "modified": "",
                    "size":     "",
                    "ext":      "",
                })
            logger.info("ClipBrowser: {} shares found on {}", len(shares), server)
            return shares
        except Exception:
            logger.exception("ClipBrowser: error enumerating shares on {}.", server)
            return []

    @Slot(str, result='QVariantList')
    def listDirectory(self, path: str) -> list:
        """Browse any directory and return its contents for the ClipBrowser.

        Handles UNC paths (\\\\Server\\Share), local paths, and the special
        tokens 'LOCAL_CLIPS' / 'LOCAL_RAW' that resolve to the app's own
        clip directories.  Returns an empty list on permission errors.

        For UNC paths, calls ``net use`` with NAS_USERNAME / NAS_PASSWORD
        from the environment if the server hasn't been authenticated yet
        this session.
        """
        import os          # noqa: PLC0415
        import subprocess  # noqa: PLC0415

        resolved = path
        if path == "LOCAL_CLIPS":
            resolved = str(self._clips_dir)
        elif path == "LOCAL_RAW":
            resolved = str(self._clips_dir.parent / "clips_raw")

        # Authenticate UNC paths + handle server-root enumeration
        if resolved.startswith("\\\\") or resolved.startswith("//"):
            normed = resolved.replace("/", "\\").rstrip("\\")
            # parts[0] = server name, parts[1] = share (if any)
            parts  = normed.lstrip("\\").split("\\")
            server = f"\\\\{parts[0]}" if parts else ""

            if server:
                if server not in AppBridge._unc_authenticated:
                    self._unc_connect(server)
                    AppBridge._unc_authenticated.add(server)

                # Bare server path (no share) — enumerate shares via net view
                if len(parts) <= 1:
                    return self._list_unc_server(server)

        result: list[dict] = []
        try:
            with os.scandir(resolved) as it:
                entries = sorted(it, key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
                for entry in entries:
                    if entry.name.startswith("$") or entry.name.startswith("."):
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                        stat   = entry.stat(follow_symlinks=False)
                        mtime  = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).astimezone()
                        size_b = 0 if is_dir else stat.st_size
                        ext    = "" if is_dir else os.path.splitext(entry.name)[1].lstrip(".").upper()
                        result.append({
                            "name":     entry.name,
                            "path":     entry.path,
                            "isDir":    is_dir,
                            "modified": mtime.strftime("%m/%d/%Y  %I:%M %p"),
                            "size":     _fmt_size(size_b) if size_b else "",
                            "ext":      ext,
                        })
                    except OSError:
                        pass
        except (OSError, PermissionError) as exc:
            logger.warning("ClipBrowser: cannot list '{}': {}", resolved, exc)
        return result

    @Slot()
    def identifyMonitors(self) -> None:
        """Request an immediate monitor refresh from the detection service."""
        monitors = self._detection_service.get_monitors()
        self._apply_monitors_from_service(monitors)

    # ── External callbacks ────────────────────────────────────────────

    def notify_recording_failed(self, msg: str) -> None:
        self.recordingFailed.emit(msg)

    def notify_clip_failed(self, msg: str) -> None:
        self.clipFailed.emit(msg)

    # ── Request system wiring (called from main.py) ───────────────────

    def set_request_system(
        self,
        adapter: RequestPort,
        slc_storage_host: str,
        server=None,   # ClipRequestServer | None
        client=None,   # ClipRequestClient | None
    ) -> None:
        """Wire request infrastructure injected by main.py.

        Call AFTER the QML engine is loaded so Qt signals work correctly.
        ``server`` is provided for the IT role; ``client`` for Supervisor.
        """
        self._request_adapter = adapter
        self._slc_storage_host = slc_storage_host

        if server is not None:
            self._request_server = server
            server.requestReceived.connect(self._on_request_received)

        if client is not None:
            self._request_client = client
            client.statusReceived.connect(
                lambda rid, st: self._on_status_received(rid, st)
            )

    def _on_request_received(self, req_id: str) -> None:
        if self._request_adapter is not None:
            self._request_adapter.update_status(req_id, "pending")
        self.requestReceived.emit()

    def _on_status_received(self, req_id: str, status: str) -> None:
        if self._request_adapter is not None:
            self._request_adapter.update_status(req_id, status)
        self.requestStatusChanged.emit(req_id, status)

    # ── Supervisor slots ──────────────────────────────────────────────

    @Slot(result='QVariantList')
    def listStorages(self) -> list:
        """Return the 3 storage shares on SLC-Storage.

        Returns ``[{name, path, operatorCount}]`` — one item per share.
        Reuses the existing UNC authentication infrastructure.
        """
        host = self._slc_storage_host or r"\\SIG-SLC-Storage"
        shares = self._list_unc_server(host)
        result = []
        for share in shares:
            # Count operator folders without revealing their contents
            op_count = self._count_dirs(share["path"])
            result.append({
                "name":          share["name"],
                "path":          share["path"],
                "operatorCount": op_count,
            })
        return result

    @Slot(str, result='QVariantList')
    def listOperators(self, storage_path: str) -> list:
        """Return operator folder NAMES inside a single storage share.

        Security contract: returns only ``{name, storage}`` — no navigable
        path is included, preventing the Supervisor from drilling deeper.
        """
        import os  # noqa: PLC0415

        # Authenticate the UNC server if needed (reuses existing cache)
        if storage_path.startswith("\\\\") or storage_path.startswith("//"):
            normed = storage_path.replace("/", "\\").rstrip("\\")
            parts  = normed.lstrip("\\").split("\\")
            server = f"\\\\{parts[0]}" if parts else ""
            if server and server not in AppBridge._unc_authenticated:
                self._unc_connect(server)
                AppBridge._unc_authenticated.add(server)

        storage_name = storage_path.rstrip("\\").rstrip("/").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        result = []
        try:
            with os.scandir(storage_path) as it:
                for entry in sorted(it, key=lambda e: e.name.lower()):
                    if entry.name.startswith("$") or entry.name.startswith("."):
                        continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    result.append({
                        "name":    entry.name,
                        "storage": storage_name,
                        # No "path" field — Supervisor cannot navigate inside
                    })
        except (OSError, PermissionError) as exc:
            logger.warning("listOperators: cannot list '{}': {}", storage_path, exc)
        return result

    @Slot(result='QVariantList')
    def listAllOperators(self) -> list:
        """Return ALL operator names across every storage share, sorted by name.

        Each item: ``{name, storage}`` — the storage name is included so the
        request payload can carry the full context, but no navigable path is
        returned (Supervisor cannot drill into operator folders).
        """
        all_ops: list[dict] = []
        for storage in self.listStorages():
            ops = self.listOperators(storage["path"])
            all_ops.extend(ops)
        all_ops.sort(key=lambda x: x["name"].lower())
        return all_ops

    @Slot(str)
    def sendClipRequest(self, request_json: str) -> None:
        """Parse, persist, and send a clip request to all configured IT hosts.

        ``request_json`` must be a valid JSON string matching the ClipRequest
        schema.  Returns silently on error (the supervisor UI shows the local
        outbox, so failures are visible there).
        """
        import json  # noqa: PLC0415
        import socket  # noqa: PLC0415
        import uuid    # noqa: PLC0415
        from datetime import timezone as _tz  # noqa: PLC0415

        if self._request_adapter is None:
            logger.warning("sendClipRequest: request system not initialised.")
            return
        try:
            data = json.loads(request_json)
            data["id"]              = str(uuid.uuid4())
            data["created_at"]      = datetime.now(tz=_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            data["supervisor_host"] = socket.gethostname()
            data["status"]          = "pending"
            req = ClipRequest.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.exception("sendClipRequest: invalid request JSON.")
            return

        self._request_adapter.save(req)

        if self._request_client is not None:
            self._request_client.send_request(req)
        else:
            logger.warning("sendClipRequest: no WS client — request saved locally only.")

        logger.info("Clip request {} created: {} / {}", req.id, req.operator, req.start_time)

    @Slot(result='QVariantList')
    def getMyRequests(self) -> list:
        """Return all locally persisted requests (Supervisor outbox), newest first."""
        if self._request_adapter is None:
            return []
        return [r.to_dict() for r in self._request_adapter.load_all()]

    # ── IT slots ──────────────────────────────────────────────────────

    @Slot(result='QVariantList')
    def getInboxRequests(self) -> list:
        """Return all received requests (IT inbox), newest first."""
        if self._request_adapter is None:
            return []
        return [r.to_dict() for r in self._request_adapter.load_all()]

    @Slot(str, str)
    def updateRequestStatus(self, req_id: str, status: str) -> None:
        """Update request status on disk and broadcast via WebSocket to Supervisor."""
        if self._request_adapter is None:
            return
        self._request_adapter.update_status(req_id, status)
        if self._request_server is not None:
            self._request_server.send_status_update(req_id, status)
        self.requestReceived.emit()   # refresh inbox UI

    # ── Helpers ───────────────────────────────────────────────────────

    def _count_dirs(self, path: str) -> int:
        import os  # noqa: PLC0415
        try:
            with os.scandir(path) as it:
                return sum(
                    1 for e in it
                    if e.is_dir(follow_symlinks=False)
                    and not e.name.startswith("$")
                    and not e.name.startswith(".")
                )
        except (OSError, PermissionError):
            return 0
