from __future__ import annotations
import sys
import os
import pathlib
# Ensure the app package is discoverable when running main.py directly
sys.path.append(str(pathlib.Path(__file__).parent.parent))

# Ensure Qt can find its platform plugins (dev venv and PyInstaller frozen builds)
try:
    import PySide6
    _pyside6_dir     = pathlib.Path(PySide6.__file__).parent
    _pyside6_plugins = _pyside6_dir / "plugins"
    _qt_platforms    = _pyside6_plugins / "platforms"

    # Python 3.8+ on Windows uses a restricted DLL search path.
    # Register the PySide6 root so that plugin DLLs (e.g. ffmpegmediaplugin.dll,
    # windowsmediaplugin.dll) can resolve their Qt6*.dll dependencies at load time.
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(_pyside6_dir))

    if _qt_platforms.exists():
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_qt_platforms))
    elif getattr(sys, "frozen", False):
        # PyInstaller may unpack PySide6 one level up inside _MEIPASS
        _frozen_plugins = pathlib.Path(sys._MEIPASS) / "PySide6" / "plugins" / "platforms"  # type: ignore[attr-defined]
        if _frozen_plugins.exists():
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(_frozen_plugins))

    # QT_PLUGIN_PATH must point to the *parent* of the multimedia/ sub-directory
    # so that Qt's plugin loader finds ffmpegmediaplugin / windowsmediaplugin.
    if _pyside6_plugins.exists():
        _cur = os.environ.get("QT_PLUGIN_PATH", "")
        _pp  = str(_pyside6_plugins)
        if _pp not in _cur:
            os.environ["QT_PLUGIN_PATH"] = _pp + (os.pathsep + _cur if _cur else "")
except ImportError:
    pass

import atexit
import os
import signal
import sys
import time
from typing import List

from loguru import logger
from pathlib import Path

from app.infrastructure.config import get_settings
from app.infrastructure.logging_setup import configure_logging
from app.core.recording_service.buffer_manager import BufferManager
from app.core.recording_service.clip_builder import ClipBuilder
from app.core.recording_service.models import MonitorInfo, Segment
from app.core.recording_service.monitor_worker import MonitorWorker
from app.core.recording_service.service import RecordingService
from app.core.event_service import EventService
from app.core.player.player_service import PlayerService
from app.core.role import (
    OPERATOR,
    SUPERVISOR,
    enforce_role,
    is_recording_role,
    should_autorecord_on_launch,
)
from app.adapters.ffmpeg import encoder_selector
from app.adapters.ffmpeg.recorder_adapter import FFmpegRecorderAdapter
from app.adapters.ffmpeg.trim_adapter import FFmpegTrimAdapter
from app.adapters.ffmpeg.timestamp_adapter import FFmpegTimestampAdapter
from app.adapters.ffmpeg.clip_inspector_adapter import FFprobeClipInspectorAdapter
from app.adapters.ffmpeg.mp4_converter_adapter import FFmpegMp4ConverterAdapter
from app.adapters.ffmpeg.hourly_recording_builder import HourlyRecordingBuilder
from app.adapters.ffmpeg.combined_clip_builder import CombinedClipBuilder
from app.adapters.ffmpeg.editor_export_adapter import FFmpegEditorExportAdapter
from app.adapters.native import make_segment_compiler
from app.adapters.storage.sqlite_event_store import SqliteEventStoreAdapter
from app.core.analytics.manual_event import analytic_event_from_context
from app.core.analytics.sidecar import write_sidecar
from app.adapters.filesystem.storage_adapter import FilesystemStorageAdapter
from app.adapters.filesystem.user_config_adapter import JsonUserConfigAdapter
from app.adapters.monitor.screeninfo_adapter import ScreeninfoMonitorAdapter
from app.adapters.ui import tray_icon as tray_module
from app.adapters.filesystem.request_adapter import JsonRequestAdapter
from app.core.recording_service.supervisor import RecorderSupervisor
from app.core.role import IT, SUPERVISOR
from app.core.disk_monitor import DiskSpaceMonitor
from app.core.monitor_detection.service import MonitorDetectionService
from app.core.recording_health.service import RecordingHealthService
# LivePreviewService removed — preview is now embedded in the recorder FFmpeg process


def _build_worker(
    monitor: MonitorInfo,
    storage: FilesystemStorageAdapter,
    settings,
    builder: HourlyRecordingBuilder,
    preview_path: "Path | None" = None,
) -> MonitorWorker:
    """Factory: create a fully-wired MonitorWorker for one physical monitor."""
    segment_dir = settings.segment_dir / f"m{monitor.index}"

    def _on_segment_finalized(segment: Segment, _m=monitor) -> None:
        builder.on_segment_finalized(segment, _m.index)

    buffer = BufferManager(
        storage=storage,
        retention_count=max(1, (settings.retention_hours * 3600) // settings.segment_duration),
        on_segment_finalized=_on_segment_finalized,
    )

    supervisor = RecorderSupervisor(
        recorder=None,  # type: ignore[arg-type]
        storage=storage,
        segment_dir=segment_dir,
        max_restarts=settings.max_recorder_restarts,
    )

    recorder = FFmpegRecorderAdapter(
        segment_duration=settings.segment_duration,
        framerate=settings.capture_framerate,
        crf=settings.crf,
        width=settings.output_width,
        height=settings.output_height,
        capture_source=settings.capture_source,
        codec=settings.video_codec,
        on_segment_ready=buffer.register_segment,
        on_crash=supervisor.notify_crash,
        # Embedded preview: same FFmpeg process writes a JPEG at 2fps alongside
        # the recording. No separate screen-capture process = no screen flickering.
        preview_path=preview_path,
        preview_fps=2,
        preview_width=1280,
    )
    recorder.set_monitor(monitor)
    supervisor._recorder = recorder  # noqa: SLF001

    return MonitorWorker(
        monitor=monitor,
        recorder=recorder,
        buffer_manager=buffer,
        storage=storage,
        segment_dir=segment_dir,
        supervisor=supervisor,
    )


def _register_ffmpeg_cleanup() -> None:
    """Register an atexit hook that kills any child ffmpeg processes on exit.

    This is the last-resort safety net: the job objects (process_guard) handle
    forceful kills, while this handles the race window where a supervisor thread
    spawns a new FFmpeg process after recording_service.stop() returns.
    """
    import psutil  # noqa: PLC0415

    def _cleanup() -> None:
        try:
            me = psutil.Process(os.getpid())
            for child in me.children(recursive=True):
                if "ffmpeg" in child.name().lower():
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except Exception:  # noqa: BLE001
            pass

    atexit.register(_cleanup)


def _acquire_single_instance_lock() -> object:
    """Return a Windows named mutex that prevents a second instance from starting.

    Returns the mutex handle (must stay in scope for the life of the process).
    Exits if another instance already holds the mutex.

    Retries briefly on ERROR_ALREADY_EXISTS: a role change relaunches the app,
    spawning the replacement while the outgoing instance is still releasing the
    mutex.  That transient collision is expected, so we wait for the old handle
    to drop before deciding a genuine second instance is running.
    """
    import ctypes
    ERROR_ALREADY_EXISTS = 183
    deadline = time.monotonic() + 3.0
    while True:
        mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "TheWatcher_SingleInstance")
        if ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS:
            return mutex  # keep alive
        # We got a handle to the *existing* mutex; drop it before retrying.
        ctypes.windll.kernel32.CloseHandle(mutex)
        if time.monotonic() >= deadline:
            break
        time.sleep(0.2)

    import tkinter, tkinter.messagebox  # noqa: PLC0415
    try:
        root = tkinter.Tk(); root.withdraw()
        tkinter.messagebox.showerror(
            "The Watcher",
            "Another instance is already running.\nClose it before starting a new one.",
        )
        root.destroy()
    except Exception:
        pass
    sys.exit(1)


def _release_single_instance_lock(mutex: object) -> None:
    """Release and close the single-instance mutex.

    Called right before a relaunch so the replacement instance can acquire it.
    """
    try:
        import ctypes
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)
    except Exception:  # noqa: BLE001
        pass


def main() -> None:
    _instance_lock = _acquire_single_instance_lock()
    # Set by the role-change relaunch callback; checked after app.exec() returns
    # so the existing teardown runs once before we spawn the replacement.
    _relaunch_flag = {"requested": False}
    _register_ffmpeg_cleanup()
    configure_logging()
    settings = get_settings()

    # ── User config (persisted preferences) ──────────────────────────
    user_config_port = JsonUserConfigAdapter()
    user_config = user_config_port.load()

    # Override clips_dir with user-chosen path if one was saved.
    clips_dir = (
        Path(user_config.clips_dir) if user_config.clips_dir else settings.clips_dir
    )

    # ── Role enforcement ──────────────────────────────────────────────
    # Applies per-role constraints (forced autorecord, autostart registry)
    # before any service is started.  enforce_role() mutates user_config
    # in-place but does NOT re-persist — autorecord/autostart for operator
    # are always overridden at startup without changing the stored value.
    from app.infrastructure import autostart as _autostart_mod  # noqa: PLC0415
    enforce_role(user_config.role, user_config, _autostart_mod)
    logger.info("Role: {}", user_config.role or "(not configured)")

    # ── Per-PC encoder selection ──────────────────────────────────────
    # driver: auto/nvidia/intel/amd/cpu (RTX machines can force NVENC).
    # codec:  user override of the .env VIDEO_CODEC default.
    # Mutating settings.video_codec here means every adapter built below
    # (recorder + clip builders) picks up the resolved codec uniformly.
    encoder_selector.set_preferences(driver=user_config.driver)
    if user_config.codec:
        settings.video_codec = user_config.codec.lower()
    logger.info(
        "Encoder config: driver={} codec={}", user_config.driver, settings.video_codec
    )

    logger.info("The Watcher starting...")
    logger.info(
        "Config: segment_dir={} clips_dir={} retention={}h segment_duration={}s",
        settings.segment_dir,
        clips_dir,
        settings.retention_hours,
        settings.segment_duration,
    )

    # ── Ensure output directories exist from the very first second ────
    # clips_dir is normally created lazily (on first clip build) which means
    # the folder wouldn't appear until an event is triggered.  Create it now
    # so the user can confirm the correct output location immediately.
    clips_dir.mkdir(parents=True, exist_ok=True)
    settings.segment_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output directories ready: segments={} | clips={}", settings.segment_dir, clips_dir)

    # ── Infrastructure ────────────────────────────────────────────────
    storage         = FilesystemStorageAdapter()
    monitor_adapter = ScreeninfoMonitorAdapter()

    # ── Phase 1: MonitorDetectionService — source of truth for monitors ──
    # detect_now() runs synchronously so we have confirmed monitors before
    # creating workers. start() then polls in background, auto-adding/removing
    # workers as monitors are connected or disconnected.
    detection_service = MonitorDetectionService(
        monitor_port=monitor_adapter,
        poll_interval_seconds=5.0,
    )
    all_monitors = detection_service.detect_now()
    # Only recording roles (operator / IT) need a monitor.  Supervisor and the
    # unconfigured first-run state launch without one (clips-only / role wizard).
    if not all_monitors and is_recording_role(user_config.role):
        logger.critical("No monitors detected — cannot start recording.")
        sys.exit(1)
    elif not all_monitors:
        logger.info("Non-recording role — no monitors required, skipping recording setup.")

    # ── Directory layout ──────────────────────────────────────────────
    # WatcherData/
    #   clips/          ← combined multi-monitor MP4 + timestamp overlay
    #   clips_raw/      ← individual per-monitor raw clips (one file per screen)
    #   segments/       ← rolling MPEG-TS segments (buffer, auto-pruned)
    raw_clips_dir = settings.raw_clips_dir
    raw_clips_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Directory layout: combined={} | raw={} | segments={}",
                clips_dir, raw_clips_dir, settings.segment_dir)

    # ── Recording stack (skipped for Supervisor role) ────────────────
    # Supervisor PCs only play back clips; they never capture screens.
    combined_builder: Optional[CombinedClipBuilder] = None
    per_monitor_builders: dict[int, HourlyRecordingBuilder] = {}
    workers: List[MonitorWorker] = []
    preview_paths: dict[int, Path] = {}
    recording_service: Optional[RecordingService] = None
    clip_builder: Optional[ClipBuilder] = None
    event_service: Optional[EventService] = None
    disk_monitor: Optional[DiskSpaceMonitor] = None
    health_service: Optional[RecordingHealthService] = None
    event_store: Optional[SqliteEventStoreAdapter] = None

    if is_recording_role(user_config.role):
        combined_builder = CombinedClipBuilder(
            raw_dir=raw_clips_dir,
            output_dir=clips_dir,
            monitor_count=len(all_monitors),
            timestamp_adapter=FFmpegTimestampAdapter(codec=settings.video_codec),
            codec=settings.video_codec,
            cell_width=settings.combined_cell_width,
            cell_height=settings.combined_cell_height,
            quality=settings.combined_quality,
        )

        def _make_builder(monitor: MonitorInfo) -> HourlyRecordingBuilder:
            b = HourlyRecordingBuilder(
                output_dir=raw_clips_dir,
                monitor_count=1,
                monitor_index=monitor.index,
                window_minutes=settings.clip_window_minutes,
                max_size_mb=settings.clip_max_size_mb,
                on_clip_ready=combined_builder.on_clip_ready,
                codec=settings.video_codec,
            )
            per_monitor_builders[monitor.index] = b
            return b

        for m in all_monitors:
            preview_path = settings.segment_dir / f"m{m.index}" / "preview.jpg"
            preview_paths[m.index] = preview_path
            workers.append(_build_worker(m, storage, settings, _make_builder(m), preview_path))
        for w in workers:
            w.segment_dir.mkdir(parents=True, exist_ok=True)

        recording_service = RecordingService(workers=workers)

        saved_fps = set(user_config.selected_monitor_fingerprints)
        initial_selection = [m for m in all_monitors if m.fingerprint in saved_fps]
        if not initial_selection:
            initial_selection = [
                next((m for m in all_monitors if m.is_primary), all_monitors[0])
            ]
        recording_service.change_monitors(initial_selection)

        clip_adapter = FFmpegTrimAdapter(codec=settings.video_codec)
        clip_builder = ClipBuilder(
            recording_service=recording_service,
            clip_adapter=clip_adapter,
            clips_dir=clips_dir,
            pre_seconds=settings.event_pre_seconds,
            post_seconds=settings.event_post_seconds,
            timestamp_adapter=FFmpegTimestampAdapter(codec=settings.video_codec),
        )

        # ── Event persistence (Fase 1) — manual events become queryable
        # AnalyticEvents + a per-clip sidecar so the editor can paint markers.
        event_store = SqliteEventStoreAdapter(settings.segment_dir.parent / "events.db")

        def _persist_manual_event(ctx, output_path) -> None:
            ev = analytic_event_from_context(ctx, output_path)
            event_store.add(ev)
            try:
                write_sidecar(output_path, [ev])
            except OSError:
                logger.warning("Could not write event sidecar for {}", output_path)

        event_service = EventService(
            clip_builder=clip_builder,
            post_seconds=settings.event_post_seconds,
            cooldown_seconds=settings.event_cooldown_seconds,
            retry_delay_seconds=settings.clip_retry_delay_seconds,
            on_clip_built=_persist_manual_event,
        )

        disk_monitor = DiskSpaceMonitor(
            segment_dir=settings.segment_dir,
            on_low_disk=recording_service.stop,
            warn_threshold_bytes=settings.disk_warn_bytes,
            stop_threshold_bytes=settings.disk_stop_bytes,
        )

        health_service = RecordingHealthService(
            recording_service=recording_service,
            poll_interval_seconds=30.0,
        )
    else:
        logger.info(
            "Non-recording role '{}' — recording stack not built.",
            user_config.role or "(not configured)",
        )

    # ── Phase 4: Preview paths (embedded in recorder, no separate process) ──
    # preview_paths already populated above in the worker-building loop.
    # AppBridge will poll these files every 500 ms from its QTimer.

    # ── Start recording ───────────────────────────────────────────────
    # Operator always records; IT only if its autorecord toggle is on;
    # supervisor / unconfigured never start here (and have no stack anyway).
    if recording_service is not None and should_autorecord_on_launch(
        user_config.role, user_config.autorecord
    ):
        recording_service.start()
        tray_module.set_recording_active(True)
    elif recording_service is not None:
        logger.info("Auto-record off for this role/config — buffer not started at launch.")
        tray_module.set_recording_active(False)
    else:
        tray_module.set_recording_active(False)
    if health_service is not None:
        health_service.start()
    if disk_monitor is not None:
        disk_monitor.start()
    detection_service.start()

    # ── Startup recovery: rebuild clips from existing segments ────────
    for w in workers:
        b = per_monitor_builders[w.monitor.index]
        all_segs = list(w.buffer.all_segments())
        if all_segs:
            logger.info(
                "Starting clip recovery for m{} — {} segment(s) in buffer.",
                w.monitor.index, len(all_segs),
            )
            b.recover_from_segments(all_segs)
        else:
            logger.info(
                "No existing segments for m{} — starting fresh.",
                w.monitor.index,
            )

    # ── Combined clip recovery ────────────────────────────────────────
    if combined_builder is not None:
        combined_builder.recover(backfill_hours=settings.retention_hours)

    def _shutdown(signum: int, frame: object) -> None:
        logger.info("Shutdown signal received (signal={}).", signum)
        tray_module.set_recording_active(False)
        if health_service is not None:
            health_service.stop()
        detection_service.stop()
        if disk_monitor is not None:
            disk_monitor.stop()
        if event_service is not None:
            event_service.stop()
        if recording_service is not None:
            recording_service.stop()
        for b in per_monitor_builders.values():
            b.shutdown()
        if combined_builder is not None:
            combined_builder.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Launch UI ─────────────────────────────────────────────────────
    from PySide6.QtWidgets import QApplication          # noqa: PLC0415
    from PySide6.QtQml import QQmlApplicationEngine     # noqa: PLC0415
    from PySide6.QtCore import QUrl, QTimer             # noqa: PLC0415
    from app.adapters.ui.app_bridge import AppBridge    # noqa: PLC0415
    from app.adapters.ui.settings_bridge import SettingsBridge  # noqa: PLC0415
    from app.adapters.ui.editor_bridge import EditorBridge  # noqa: PLC0415
    from app.adapters.ui.tray_icon import TrayIcon      # noqa: PLC0415

    app = QApplication(sys.argv)   # keep QApplication — QSystemTrayIcon requires it
    app.setQuitOnLastWindowClosed(False)

    # ── Player subsystem ──────────────────────────────────────────────
    inspector      = FFprobeClipInspectorAdapter()
    player_service = PlayerService(inspector=inspector)

    # ── Editor subsystem (Fase 0) — evidence-reel timeline + export ────
    # Rust segment engine when available, FFmpeg fallback otherwise (ADR-0006).
    segment_compiler = make_segment_compiler(codec=settings.video_codec)
    editor_export    = FFmpegEditorExportAdapter(segment_compiler)
    editor_bridge    = EditorBridge(
        export_port=editor_export, clips_dir=clips_dir, inspector=inspector
    )

    # ── Bridge objects ────────────────────────────────────────────────
    bridge = AppBridge(
        recording_service=recording_service,
        event_service=event_service,
        detection_service=detection_service,
        player_service=player_service,
        clips_dir=clips_dir,
        user_config_port=user_config_port,
    )
    # ── Wire detection → recording + UI (bridge is now in scope) ────────
    def _on_monitor_added(monitor: MonitorInfo) -> None:
        worker = _build_worker(monitor, storage, settings, _make_builder(monitor))
        worker.segment_dir.mkdir(parents=True, exist_ok=True)
        recording_service.add_worker(worker)
        worker.set_on_recording_failed(bridge.notify_recording_failed)

    # Hot-plug → recording callbacks only apply when a recording stack exists
    # (operator / IT).  Supervisor and unconfigured machines have no
    # recording_service; they only refresh the UI monitor list.
    if recording_service is not None:
        detection_service._on_monitor_added    = _on_monitor_added              # noqa: SLF001
        detection_service._on_monitor_removed  = recording_service.remove_worker  # noqa: SLF001
    detection_service._on_monitors_changed = bridge.on_monitors_updated  # noqa: SLF001
    settings_bridge = SettingsBridge(
        user_config_port=user_config_port,
        settings=settings,
    )

    # ── "Apply encoder now" callback ──────────────────────────────────
    # Called from a background thread when the user clicks "Aplicar ahora".
    # Stops the live recording, applies the new codec/driver to every recorder
    # adapter, then restarts. Takes ~2 s; must not touch Qt from this thread.
    def _restart_recording(codec: str, driver: str) -> None:
        if recording_service is None:
            return
        logger.info("Restarting recording: codec={} driver={}", codec, driver)
        was_running = recording_service.is_recording()
        recording_service.stop()
        # Apply encoder preference and clear the probe cache.
        encoder_selector.set_preferences(driver=driver)
        # Push the new codec to every recorder adapter so it takes effect
        # when start() is called below.  settings.video_codec is the live
        # value used by adapters not yet instantiated (e.g. hot-added monitors).
        settings.video_codec = codec
        for worker in list(recording_service._workers.values()):  # noqa: SLF001
            if hasattr(worker._recorder, "update_codec"):          # noqa: SLF001
                worker._recorder.update_codec(codec)               # noqa: SLF001
        if was_running:
            recording_service.start()
            tray_module.set_recording_active(True)
            logger.info("Recording restarted with codec={} driver={}.", codec, driver)
        else:
            logger.info("Recording was stopped — not restarting (autorecord=off).")

    settings_bridge.set_restart_callback(_restart_recording)

    # ── Role-change relaunch ──────────────────────────────────────────
    # The whole backend is wired at startup from the role, so a role change
    # (first-run wizard or an IT-initiated change) is applied by re-running
    # main() in a fresh process.  We flag the request and quit the event loop;
    # the post-exec teardown below stops everything once, then we spawn.
    # QTimer defers quit() so the QML slot that called setRole() returns first
    # and the config write flushes.
    def _request_relaunch() -> None:
        if _relaunch_flag["requested"]:
            return
        _relaunch_flag["requested"] = True
        logger.info("Role change — scheduling relaunch.")
        QTimer.singleShot(0, app.quit)

    settings_bridge.set_relaunch_callback(_request_relaunch)

    # ── Live autorecord toggle (IT) ───────────────────────────────────
    # IT records optionally: the stack is built but parked.  Toggling the
    # setting starts/stops the existing workers in-process (no restart).
    def _apply_autorecord(enabled: bool) -> None:
        if recording_service is None:
            return
        if enabled:
            recording_service.start()
            tray_module.set_recording_active(True)
            logger.info("Autorecord enabled — recording started.")
        else:
            recording_service.stop()
            tray_module.set_recording_active(False)
            logger.info("Autorecord disabled — recording stopped.")

    settings_bridge.set_autorecord_callback(_apply_autorecord)

    # ── QML engine ────────────────────────────────────────────────────
    engine = QQmlApplicationEngine()
    # Surface QML load/binding errors to the log. Without this, a failed
    # engine.load() only yields a generic "QML failed to load" with no cause —
    # critical for diagnosing frozen builds where stderr is unavailable.
    engine.warnings.connect(
        lambda warns: [logger.error("QML: {}", w.toString()) for w in warns]
    )
    ui_dir = Path(__file__).parent / "adapters" / "ui"
    # Add the PySide6 qml/ directory so QtQuick, QtQuick.Controls,
    # QtMultimedia, etc. are resolvable at runtime.
    try:
        import PySide6 as _PySide6
        _pyside6_qml = Path(_PySide6.__file__).parent / "qml"
        if _pyside6_qml.exists():
            engine.addImportPath(str(_pyside6_qml))
    except ImportError:
        pass
    engine.addImportPath(str(ui_dir))
    # GDI-based monitor screenshot provider — works on all monitors/GPUs
    engine.addImageProvider("monitor_preview", bridge.screenshot_provider)
    engine.rootContext().setContextProperty("AppBridge", bridge)
    engine.rootContext().setContextProperty("SettingsBridge", settings_bridge)
    engine.rootContext().setContextProperty("EditorBridge", editor_bridge)
    qml_path = ui_dir / "Main.qml"
    logger.info("Loading QML: {} (exists={})", qml_path, qml_path.exists())
    engine.load(QUrl.fromLocalFile(str(qml_path.resolve())))
    if not engine.rootObjects():
        logger.critical("QML failed to load — stopping recording and exiting.")
        tray_module.set_recording_active(False)
        if health_service is not None:
            health_service.stop()
        detection_service.stop()
        if disk_monitor is not None:
            disk_monitor.stop()
        if event_service is not None:
            event_service.stop()
        if recording_service is not None:
            recording_service.stop()
        for b in per_monitor_builders.values():
            b.shutdown()
        sys.exit(-1)

    # Wire failure callbacks through bridge signals
    for w in workers:
        w.set_on_recording_failed(bridge.notify_recording_failed)
    if event_service is not None:
        event_service._on_clip_failed = bridge.notify_clip_failed  # noqa: SLF001

    # ── Request system (IT server / Supervisor client) ────────────────
    # Both roles share the same JsonRequestAdapter (same filesystem schema).
    # IT starts a WS server; Supervisor starts a WS client.
    _req_adapter = JsonRequestAdapter()
    _req_server  = None
    _req_client  = None

    if user_config.role == IT:
        from app.adapters.ws.request_server import ClipRequestServer  # noqa: PLC0415
        _req_server = ClipRequestServer(
            port=settings.it_ws_port,
            request_adapter=_req_adapter,
            parent=app,
        )
        _req_server.start()

    elif user_config.role == SUPERVISOR:
        from app.adapters.ws.request_client import ClipRequestClient  # noqa: PLC0415
        _req_client = ClipRequestClient(
            hosts=user_config.it_ws_hosts,
            port=settings.it_ws_port,
            parent=app,
        )

    bridge.set_request_system(
        adapter=_req_adapter,
        slc_storage_host=settings.slc_storage_host,
        server=_req_server,
        client=_req_client,
    )

    if _req_client is not None:
        settings_bridge.itWsHostsChanged.connect(_req_client.set_hosts)

    # ── Phase 4: Tell AppBridge where to find the preview JPEGs ─────────
    bridge.set_preview_paths(preview_paths)

    tray = TrayIcon(
        show_fn=lambda: bridge.requestShowWindow.emit(),
        app=app,
        role=user_config.role,
    )  # noqa: F841

    logger.info("UI ready. Role: {}.", user_config.role or "not configured")

    exit_code = app.exec()

    tray_module.set_recording_active(False)
    if health_service is not None:
        health_service.stop()
    detection_service.stop()
    if disk_monitor is not None:
        disk_monitor.stop()
    if event_service is not None:
        event_service.stop()
    if recording_service is not None:
        recording_service.stop()
    for b in per_monitor_builders.values():
        b.shutdown()
    if combined_builder is not None:
        combined_builder.shutdown()
    if _req_server is not None:
        _req_server.stop()
    if _req_client is not None:
        _req_client.disconnect_all()

    if _relaunch_flag["requested"]:
        # The teardown above already stopped every service (including FFmpeg),
        # so we only need to free the single-instance mutex and spawn the
        # replacement, which re-runs main() with the new role.
        from app.infrastructure.relaunch import relaunch_and_exit  # noqa: PLC0415
        relaunch_and_exit(
            teardown=lambda: None,
            release_lock=lambda: _release_single_instance_lock(_instance_lock),
        )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
