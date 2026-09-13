from __future__ import annotations
import sys
import pathlib
# Ensure the app package is discoverable when running main.py directly
sys.path.append(str(pathlib.Path(__file__).parent.parent))

import atexit
import os
import threading
import time
from typing import Callable, List, Optional

from loguru import logger
from pathlib import Path

from app.infrastructure.config import Settings, get_settings
from app.infrastructure.clip_migration import migrate_legacy_event_clips
from app.infrastructure.logging_setup import configure_logging, set_event_bus
from app.core.recording_service.models import MonitorInfo
from app.core.recording_service.service import RecordingService
from app.core.cloud_share_service import CloudShareService
from app.adapters.cloud.local_share_adapter import LocalShareAdapter
from app.core.player.player_service import PlayerService
from app.core.ports.segment_compiler_port import SegmentCompilerPort
from app.core.ports.user_config_port import UserConfig, UserConfigPort
from app.core.role import (
    IT,
    OPERATOR,
    SUPERVISOR,
    enforce_role,
    is_recording_role,
    should_autorecord_on_launch,
)
from app.adapters.ffmpeg import encoder_selector
from app.adapters.ffmpeg.clip_inspector_adapter import FFprobeClipInspectorAdapter
from app.adapters.ffmpeg.mp4_converter_adapter import FFmpegMp4ConverterAdapter
from app.adapters.ffmpeg.editor_export_adapter import FFmpegEditorExportAdapter
from app.adapters.native import make_segment_compiler
from app.adapters.filesystem.file_browser_adapter import WindowsFileBrowserAdapter
from app.core.api.bootstrap import ApiLayer, build_api_layer
from app.runtime.backend import RecordingBackend, build_recording_backend
from app.runtime.mode import DAEMON, resolve_mode
from app.infrastructure.proc_telemetry import get_telemetry
from app.adapters.filesystem.storage_adapter import FilesystemStorageAdapter
from app.adapters.filesystem.user_config_adapter import JsonUserConfigAdapter
from app.adapters.monitor.screeninfo_adapter import ScreeninfoMonitorAdapter
from app.adapters.filesystem.request_adapter import JsonRequestAdapter
from app.adapters.ws.request_server import ClipRequestServer
from app.adapters.ws.request_client import ClipRequestClient
from app.adapters.preview_server.mjpeg_server_adapter import MjpegPreviewServerAdapter
from app.adapters.browser_local import BrowserLocalAdapter
from app.adapters.live_view_lan import LiveViewLanAdapter
from app.core.monitor_detection.service import MonitorDetectionService
# LivePreviewService removed — preview is now embedded in the recorder FFmpeg process


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


def _acquire_single_instance_lock(operator_silent: bool = False) -> object:
    """Return a Windows named mutex that prevents a second instance from starting.

    Returns the mutex handle (must stay in scope for the life of the process).
    Exits if another instance already holds the mutex.

    Retries briefly on ERROR_ALREADY_EXISTS: a role change relaunches the app,
    spawning the replacement while the outgoing instance is still releasing the
    mutex.  That transient collision is expected, so we wait for the old handle
    to drop before deciding a genuine second instance is running.

    ``operator_silent`` (operator box): on contention, exit **0** with no dialog.
    The operator's restart watchdog (a Scheduled Task) relaunches on a non-zero
    result, so a benign collision must not read as a crash — otherwise the
    scheduler would spin-loop relaunching.  And a kiosk operator must never see
    a tkinter error box.
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

    if operator_silent:
        # Benign collision on an operator box: exit cleanly, no dialog, exit 0.
        logger.info("Another instance already running (operator) — exiting quietly.")
        sys.exit(0)

    # This exit was always deterministic (sys.exit(1) either way) — what was
    # missing was that it left zero trace, because configure_logging() hadn't
    # run yet when this fired. Log first, so the CRITICAL line lands even if
    # the dialog below can't render (no desktop/session, ImportError, etc.).
    logger.critical(
        "Single-instance mutex already held after 3s of retry (pid={}) — "
        "another Watcher process is already running; refusing to start a "
        "second one.",
        os.getpid(),
    )
    try:
        import tkinter, tkinter.messagebox  # noqa: PLC0415
        root = tkinter.Tk(); root.withdraw()
        tkinter.messagebox.showerror(
            "The Watcher",
            "Another instance is already running.\nClose it before starting a new one.",
        )
        root.destroy()
    except Exception:  # noqa: BLE001
        logger.warning(
            "Could not show the 'already running' dialog (no desktop/session?) "
            "— see the CRITICAL line above."
        )
    sys.exit(1)


def _peek_role() -> str:
    """Best-effort read of the persisted role BEFORE the single-instance lock.

    Needed so an operator box can suppress the contention dialog and exit 0.
    Cheap (one JSON read); any failure falls back to "" (non-operator behaviour).
    """
    try:
        from app.adapters.filesystem.user_config_adapter import JsonUserConfigAdapter  # noqa: PLC0415
        return JsonUserConfigAdapter().load().role or ""
    except Exception:  # noqa: BLE001
        return ""


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


def _warn_if_default_it_pin(settings) -> None:
    """Loud, visible warning only — NOT a behavior change.

    Removing the "1234" default outright would make unlock_it() compare
    against None forever (a silent, permanent lockout — no downstream
    None-check exists today); that tradeoff needs an explicit decision,
    tracked in TODOS.md.
    """
    if settings.it_pin == "1234":
        logger.warning(
            "SECURITY: IT_PIN is still the default value \"1234\" — change it "
            "before deploying to a fleet (see .env.example)."
        )


def _load_settings_and_compiler() -> tuple[Settings, SegmentCompilerPort]:
    """Load settings and build the shared segment compiler.

    Logging is configured separately, as the very first statement of main()
    — before the single-instance lock — so any early exit on that path is
    always recorded (see _acquire_single_instance_lock's docstring)."""
    settings = get_settings()
    # Rust segment engine when available, FFmpeg fallback otherwise (ADR-0006).
    # Constructed once here (not per-use) so build_recording_backend()'s clip
    # path (Track R2 M1, CLIP_ENGINE) and the editor's export path below share
    # the exact same engine instance.
    segment_compiler = make_segment_compiler(codec=settings.video_codec)
    return settings, segment_compiler


def _load_user_config_and_clips_dir(settings: Settings) -> tuple[UserConfigPort, UserConfig, Path]:
    """Load persisted user config and resolve the effective clips directory."""
    user_config_port = JsonUserConfigAdapter()
    user_config = user_config_port.load()
    # Override clips_dir with user-chosen path if one was saved.
    clips_dir = (
        Path(user_config.clips_dir) if user_config.clips_dir else settings.clips_dir
    )
    return user_config_port, user_config, clips_dir


def _enforce_role_and_configure_encoder(user_config: UserConfig, settings: Settings) -> None:
    """Apply role constraints (autorecord/autostart) and resolve the encoder.

    Mutates ``user_config`` and ``settings`` in place — same contract as the
    inline code this was extracted from.
    """
    # ── Role enforcement ──────────────────────────────────────────────
    # Applies per-role constraints (forced autorecord, autostart registry)
    # before any service is started.  enforce_role() mutates user_config
    # in-place but does NOT re-persist — autorecord/autostart for operator
    # are always overridden at startup without changing the stored value.
    from app.infrastructure import autostart as _autostart_mod  # noqa: PLC0415
    from app.infrastructure import scheduled_task as _scheduled_task_mod  # noqa: PLC0415
    # Operator: a Scheduled Task is the sole launcher (restart-on-failure);
    # returns "task" (registered) or "runkey" (degraded fallback). Non-operator
    # roles return None and we remove any stale watchdog left from a prior role.
    watchdog_status = enforce_role(
        user_config.role, user_config, _autostart_mod, _scheduled_task_mod
    )
    if user_config.role != OPERATOR:
        _scheduled_task_mod.remove_task()
    logger.info(
        "Role: {} | watchdog: {}",
        user_config.role or "(not configured)",
        watchdog_status or "n/a",
    )

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


def _prepare_directories(settings: Settings, clips_dir: Path) -> tuple[Path, Path]:
    """Ensure every output directory exists; return (raw_clips_dir, event_clips_dir).

    Also migrates any legacy event clips that used to be mixed into clips_dir.
    """
    # ── Ensure output directories exist from the very first second ────
    # clips_dir is normally created lazily (on first clip build) which means
    # the folder wouldn't appear until an event is triggered.  Create it now
    # so the user can confirm the correct output location immediately.
    clips_dir.mkdir(parents=True, exist_ok=True)
    settings.segment_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output directories ready: segments={} | clips={}", settings.segment_dir, clips_dir)

    # ── Directory layout ──────────────────────────────────────────────
    # WatcherData/
    #   clips/          ← combined multi-monitor MP4 + timestamp overlay
    #   clips_raw/      ← individual per-monitor raw clips (one file per screen)
    #   clips_events/   ← auto/manual event-triggered highlight clips
    #   segments/       ← rolling MPEG-TS segments (buffer, auto-pruned)
    raw_clips_dir = settings.raw_clips_dir
    raw_clips_dir.mkdir(parents=True, exist_ok=True)
    # Fixed on local disk — does NOT follow a user-relocated clips_dir (matches
    # raw_clips_dir's existing behavior).
    event_clips_dir = settings.event_clips_dir
    event_clips_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Directory layout: combined={} | raw={} | events={} | segments={}",
                clips_dir, raw_clips_dir, event_clips_dir, settings.segment_dir)

    # One-time cleanup: event clips used to be mixed into clips_dir — move any
    # already sitting there (plus their .events.json sidecars) into their own
    # folder. Idempotent, safe to run on every startup.
    migrate_legacy_event_clips(clips_dir, event_clips_dir)

    return raw_clips_dir, event_clips_dir


def _detect_monitors(user_config: UserConfig) -> tuple[MonitorDetectionService, List[MonitorInfo]]:
    """Build the monitor-detection service and run its synchronous first probe.

    Exits the process if a recording role has no monitors detected.
    """
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

    return detection_service, all_monitors


def _build_preview_server(
    user_config: UserConfig, settings: Settings
) -> Optional[MjpegPreviewServerAdapter]:
    """Construct (but do not start) the operator-only MJPEG preview server.

    Split from :func:`_start_recording_services` so the API layer can be wired
    against this instance before the (potentially slow) recording startup runs
    — see that function's docstring for why the two are no longer combined.
    """
    if user_config.role != OPERATOR:
        return None
    return MjpegPreviewServerAdapter(settings)


def _build_browser_local_adapter(
    user_config: UserConfig,
    settings: Settings,
    api: ApiLayer,
    clips_dir: Path,
    event_clips_dir: Path,
) -> Optional[BrowserLocalAdapter]:
    """Build the external browser adapter only for the Operator daemon.

    It is intentionally not part of the named-pipe router.  The adapter itself
    fails closed when its feature flag, TLS material, site binding, or issuer
    key are missing, which keeps ordinary desktop deployments unchanged.
    """
    if user_config.role != OPERATOR or not settings.browser_local_enabled:
        return None
    try:
        return BrowserLocalAdapter(settings, api)
    except Exception as exc:  # noqa: BLE001 -- recording must survive a bad browser configuration
        logger.error("[browser-local] unavailable: {}", exc)
        return None


def _build_live_view_adapter(
    user_config: UserConfig, settings: Settings, api: ApiLayer
) -> Optional[LiveViewLanAdapter]:
    """Build the remote LAN surface only for the always-on Operator daemon."""
    if user_config.role != OPERATOR or not settings.live_view_enabled:
        return None
    try:
        return LiveViewLanAdapter(settings, api)
    except Exception as exc:  # noqa: BLE001 -- never sacrifice recording for live view
        logger.error("[live-view] unavailable: {}", exc)
        return None
def _start_recording_services(
    backend: RecordingBackend,
    user_config: UserConfig,
    detection_service: MonitorDetectionService,
    settings: Settings,
    preview_server: Optional[MjpegPreviewServerAdapter],
    browser_local: Optional[BrowserLocalAdapter],
    live_view: Optional[LiveViewLanAdapter],
) -> None:
    """Start the operator preview server (if applicable) and every backend service.

    Runs on a background thread (see main()) rather than inline during startup:
    ``recording_service.start()`` spawns FFmpeg per monitor, and building that
    command synchronously probes the capture backend (ddagrab availability),
    the zero-copy filter chain, and the hardware encoder — each a subprocess
    call with an 8-12s timeout (recorder_adapter.py / encoder_selector.py), none
    cached across monitors. On a machine with a flaky/asleep GPU driver those
    probes can each burn their full timeout, so this used to block the named
    pipe from ever binding — the Tauri UI would sit "connecting..." for up to
    a minute or more with zero feedback, indistinguishable from a real hang.
    """
    # Preview JPEGs are written by the recorder itself (backend.preview_paths,
    # segments/m{idx}/preview.jpg) and served to the UI via the watcher://
    # custom protocol (src-tauri) — the frontend polls at ~2 fps (TD-5: never
    # over JSON invoke). Nothing in this process needs to forward the paths.
    if preview_server is not None:
        preview_server.start()
    if browser_local is not None:
        browser_local.start()
    if live_view is not None:
        live_view.start()

    # ── Start recording ───────────────────────────────────────────────
    # Operator always records; IT only if its autorecord toggle is on;
    # supervisor / unconfigured never start here (and have no stack anyway).
    recording_service = backend.recording_service
    if recording_service is not None and should_autorecord_on_launch(
        user_config.role, user_config.autorecord
    ):
        recording_service.start()
    elif recording_service is not None:
        logger.info("Auto-record off for this role/config — buffer not started at launch.")
    if backend.disk_monitor is not None:
        backend.disk_monitor.start()
    detection_service.start()
    if backend.auto_event_service is not None:
        backend.auto_event_service.start()
    if backend.batch_analyzer is not None:
        # NOTE: batch_analyzer and auto_event_service's live_service share the
        # same raw DetectorPort instance (backend.py) and each calls its own
        # start()/stop() on it. MockDetectorAdapter is idempotent either way;
        # OnnxDetectorAdapter.start() reloads the ONNX session on every call,
        # so a real model pays a double-load here. Harmless today (no model
        # configured by default) — revisit detector lifecycle ownership before
        # shipping ONNX_MODEL_PATH to a fleet.
        backend.batch_analyzer.start()
    # health_service.start() happens last, back in the caller (main()'s
    # background thread) — it must fire only once recording has actually been
    # attempted, so a first poll never reports a false "degraded" against a
    # recorder that simply hasn't been asked to start yet.


def _recover_startup_clips(backend: RecordingBackend, settings: Settings) -> None:
    """Rebuild clips from any segments already on disk (crash/restart recovery)."""
    # ── Startup recovery: rebuild clips from existing segments ────────
    for w in backend.workers:
        b = backend.per_monitor_builders[w.monitor.index]
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
    if backend.combined_builder is not None:
        backend.combined_builder.recover(backfill_hours=settings.retention_hours)


def _build_player_editor_services(
    segment_compiler: SegmentCompilerPort, settings: Settings
) -> tuple[FFprobeClipInspectorAdapter, PlayerService, FFmpegEditorExportAdapter, CloudShareService]:
    """Build the (Qt-free) player, editor export, and cloud-delivery services."""
    inspector = FFprobeClipInspectorAdapter()
    player_service = PlayerService(inspector=inspector)
    # segment_compiler was already constructed near the top of main() so
    # build_recording_backend()'s clip path could share the same instance.
    # reencode=True: frame-exact cuts + normalize every clip to one format, so
    # mixed-codec/resolution reels just work (evidence reel favors precision).
    editor_export = FFmpegEditorExportAdapter(
        segment_compiler, inspector=inspector, reencode=True
    )
    # Local adapter today (real folders under the OneDrive sync root, file:// links);
    # swap to OneDriveGraphAdapter once Azure AD creds exist — adapter-agnostic.
    cloud_share_service = CloudShareService(
        LocalShareAdapter(root=settings.onedrive_root)
    )
    return inspector, player_service, editor_export, cloud_share_service


def _build_api(
    *,
    detection_service: MonitorDetectionService,
    settings: Settings,
    user_config_port: UserConfigPort,
    backend: RecordingBackend,
    player_service: PlayerService,
    editor_export: FFmpegEditorExportAdapter,
    inspector: FFprobeClipInspectorAdapter,
    cloud_share_service: CloudShareService,
    clips_dir: Path,
    event_clips_dir: Path,
    preview_server: Optional[MjpegPreviewServerAdapter],
) -> ApiLayer:
    """Build and start the core/api Facade layer (F1, ADR-0009).

    One EventBus + the facades over every built service. The IPC channel
    (adapters/ipc) is the only input adapter over this layer now that QML
    is gone (F3). event_store doubles as the AuditPort so start/stop/
    unlock/setRole are audited on every path (ADR-0011); it is None on
    non-recording roles.
    """
    file_browser = WindowsFileBrowserAdapter(
        nas_username=settings.nas_username, nas_password=settings.nas_password
    )
    # H.264 fallback for the player when HEVC won't decode in WebView2 (TD-1).
    mp4_converter = FFmpegMp4ConverterAdapter(codec="h264")
    api = build_api_layer(
        detection_service=detection_service,
        settings=settings,
        user_config_port=user_config_port,
        audit_port=backend.event_store,
        recording_service=backend.recording_service,
        event_service=backend.event_service,
        player_service=player_service,
        export_port=editor_export,
        inspector=inspector,
        file_browser=file_browser,
        mp4_converter=mp4_converter,
        cloud_share_service=cloud_share_service,
        clips_dir=clips_dir,
        event_clips_dir=event_clips_dir,
        slc_storage_host=settings.slc_storage_host,
        onedrive_base_folder=settings.onedrive_base_folder,
        analytics_query=backend.analytics,
        preview_server=preview_server,
    )
    api.start()
    set_event_bus(api.bus)  # logs → LogMessage bus event (C3), replaces the Qt log panel sink
    return api


def _wire_request_system(
    user_config: UserConfig, settings: Settings, api: ApiLayer
) -> tuple[Optional[ClipRequestServer], Optional[ClipRequestClient]]:
    """Wire the IT server / Supervisor client request system (Qt-free, C1).

    Shared by every role/mode. Both roles share the same JsonRequestAdapter
    (same filesystem schema). Callbacks only touch the transport-agnostic
    facade, which publishes bus events the IPC-connected React UI subscribes to.
    """
    req_adapter = JsonRequestAdapter()
    req_server = None
    req_client = None

    if user_config.role == IT:
        req_server = ClipRequestServer(
            port=settings.it_ws_port,
            request_adapter=req_adapter,
            on_request_received=api.requests.on_request_received,
        )
        req_server.start()
    elif user_config.role == SUPERVISOR:
        req_client = ClipRequestClient(
            hosts=user_config.it_ws_hosts,
            port=settings.it_ws_port,
            on_status_received=api.requests.on_status_received,
        )

    api.requests.configure(
        request_port=req_adapter,
        slc_storage_host=settings.slc_storage_host,
        server=req_server,
        client=req_client,
    )
    return req_server, req_client


def _wire_failure_callbacks(
    backend: RecordingBackend, api: ApiLayer, *, is_operator_daemon: bool = False
) -> None:
    """Wire recording/clip failure + health callbacks to the facade (shared, C2).

    Previously only wired on the QML path — a headless daemon/sidecar had no
    way to surface a recorder crash or a failed clip build to the UI.

    Does NOT call ``health_service.start()`` — the poll loop is started by the
    caller (main()'s background recording-startup thread) only after recording
    has actually been attempted, so its first poll can't report a false
    "degraded" against a recorder that simply hasn't started yet.
    """
    for w in backend.workers:
        w.set_on_recording_failed(api.recording.on_recording_failed)
    if backend.event_service is not None:
        backend.event_service._on_clip_failed = api.recording.on_clip_failed  # noqa: SLF001
    if backend.health_service is not None:
        backend.health_service.set_callbacks(
            on_degraded=api.recording.on_recording_degraded,
            on_recovered=api.recording.on_recording_recovered,
        )
        if is_operator_daemon:
            backend.health_service._on_hang_timeout = _make_hang_timeout_cb()  # noqa: SLF001


def _make_hang_timeout_cb() -> Callable[[list], None]:
    """Operator-only: a background service (e.g. live-inference) has been dead
    past its grace period. Deliberately hard-exit with a non-zero code so the
    Scheduled Task watchdog (RestartOnFailure) revives a clean process within
    ~1 minute — reusing that already-proven mechanism instead of trying to
    self-heal a possibly-corrupted in-process state. Never wired for IT/
    Supervisor (sidecar, no Scheduled Task to bring it back).
    """

    def _on_hang_timeout(dead_services: list) -> None:
        logger.critical(
            "[runtime] background service(s) {} hung past grace period — "
            "exiting so the operator restart watchdog can recover.",
            ", ".join(dead_services),
        )
        os._exit(1)

    return _on_hang_timeout


def _make_restart_recording_cb(
    recording_service: Optional[RecordingService], settings: Settings
) -> Callable[[str, str], None]:
    """Build the "apply encoder now" callback (shared, C2).

    Stops the live recording, applies the new codec/driver to every recorder
    adapter, then restarts. Takes ~2 s; runs on a background thread (see
    SettingsApi.apply_encoder_now).
    """

    def _restart_recording(codec: str, driver: str) -> None:
        if recording_service is None:
            return
        logger.info("Restarting recording: codec={} driver={}", codec, driver)
        was_running = recording_service.is_recording()
        recording_service.stop()
        encoder_selector.set_preferences(driver=driver)
        # settings.video_codec is the live value used by adapters not yet
        # instantiated (e.g. hot-added monitors).
        settings.video_codec = codec
        for worker in list(recording_service._workers.values()):  # noqa: SLF001
            if hasattr(worker._recorder, "update_codec"):          # noqa: SLF001
                worker._recorder.update_codec(codec)               # noqa: SLF001
        if was_running:
            recording_service.start()
            logger.info("Recording restarted with codec={} driver={}.", codec, driver)
        else:
            logger.info("Recording was stopped — not restarting (autorecord=off).")

    return _restart_recording


def _make_autorecord_cb(recording_service: Optional[RecordingService]) -> Callable[[bool], None]:
    """Build the live autorecord-toggle callback (shared, C2).

    IT records optionally: the stack is built but parked.  Toggling the
    setting starts/stops the existing workers in-process (no restart).
    """

    def _apply_autorecord(enabled: bool) -> None:
        if recording_service is None:
            return
        if enabled:
            recording_service.start()
            logger.info("Autorecord enabled — recording started.")
        else:
            recording_service.stop()
            logger.info("Autorecord disabled — recording stopped.")

    return _apply_autorecord


def _make_stop_backend_cb(
    backend: RecordingBackend,
    detection_service: MonitorDetectionService,
    req_server: Optional[ClipRequestServer],
    req_client: Optional[ClipRequestClient],
    preview_server: Optional[MjpegPreviewServerAdapter],
    browser_local: Optional[BrowserLocalAdapter],
    live_view: Optional[LiveViewLanAdapter],
) -> Callable[[], None]:
    """Build the full-backend teardown callback (stops FFmpeg, no orphans — TD-3)."""

    def _stop_backend() -> None:
        if backend.auto_event_service is not None:
            backend.auto_event_service.stop()
        if backend.batch_analyzer is not None:
            backend.batch_analyzer.stop()
        if backend.health_service is not None:
            backend.health_service.stop()
        detection_service.stop()
        if backend.disk_monitor is not None:
            backend.disk_monitor.stop()
        if backend.event_service is not None:
            backend.event_service.stop()
        if backend.recording_service is not None:
            backend.recording_service.stop()
        for b in backend.per_monitor_builders.values():
            b.shutdown()
        if backend.combined_builder is not None:
            backend.combined_builder.shutdown()
        if backend.recording_service is not None:
            get_telemetry().stop()
        if req_server is not None:
            req_server.stop()
        if req_client is not None:
            req_client.stop()
        if preview_server is not None:
            preview_server.stop()
        if browser_local is not None:
            browser_local.stop()
        if live_view is not None:
            live_view.stop()

    return _stop_backend


def _wire_hot_plug(
    detection_service: MonitorDetectionService,
    backend: RecordingBackend,
    api: ApiLayer,
) -> None:
    """Wire hot-plug monitor add/remove without a UI bridge."""
    recording_service = backend.recording_service
    if recording_service is not None and backend.build_worker_for is not None:
        def _hot_add(monitor: MonitorInfo) -> None:
            w = backend.build_worker_for(monitor)
            w.segment_dir.mkdir(parents=True, exist_ok=True)
            recording_service.add_worker(w)
            w.set_on_recording_failed(api.recording.on_recording_failed)
        detection_service._on_monitor_added   = _hot_add                         # noqa: SLF001
        detection_service._on_monitor_removed = recording_service.remove_worker  # noqa: SLF001


def main() -> None:
    # Configure logging FIRST — before anything that can exit early, the
    # single-instance lock included — so every startup path, even a failed
    # one, leaves a trace in watcher.log.
    configure_logging()
    # Peek the role before the lock so an operator box exits 0 (no dialog) on a
    # benign contention — its restart watchdog must not read that as a crash.
    _instance_lock = _acquire_single_instance_lock(operator_silent=_peek_role() == OPERATOR)
    # Set by the role-change relaunch callback; checked after app.exec() returns
    # so the existing teardown runs once before we spawn the replacement.
    _relaunch_flag = {"requested": False}
    _register_ffmpeg_cleanup()

    settings, segment_compiler = _load_settings_and_compiler()
    user_config_port, user_config, clips_dir = _load_user_config_and_clips_dir(settings)
    _enforce_role_and_configure_encoder(user_config, settings)

    logger.info("The Watcher starting...")
    logger.info(
        "Config: segment_dir={} clips_dir={} retention={}h segment_duration={}s",
        settings.segment_dir,
        clips_dir,
        settings.retention_hours,
        settings.segment_duration,
    )
    _warn_if_default_it_pin(settings)

    raw_clips_dir, event_clips_dir = _prepare_directories(settings, clips_dir)

    # ── Infrastructure ────────────────────────────────────────────────
    storage = FilesystemStorageAdapter()

    detection_service, all_monitors = _detect_monitors(user_config)

    # ── Recording stack (skipped for Supervisor role) ────────────────
    # Built by the shared, Qt-free factory so the headless daemon/sidecar
    # (ADR-0010) construct the same backend. Unpacked into locals so the rest
    # of the Qt startup below is unchanged.
    backend = build_recording_backend(
        settings=settings,
        user_config=user_config,
        storage=storage,
        all_monitors=all_monitors,
        clips_dir=clips_dir,
        raw_clips_dir=raw_clips_dir,
        event_clips_dir=event_clips_dir,
        segment_compiler=segment_compiler,
    )
    recording_service = backend.recording_service

    # Constructed now (cheap) but not started — starting it (and the rest of
    # the recording stack) is deferred to a background thread below so it
    # cannot block the IPC pipe from binding.
    preview_server = _build_preview_server(user_config, settings)

    inspector, player_service, editor_export, cloud_share_service = _build_player_editor_services(
        segment_compiler, settings
    )

    api = _build_api(
        detection_service=detection_service,
        settings=settings,
        user_config_port=user_config_port,
        backend=backend,
        player_service=player_service,
        editor_export=editor_export,
        inspector=inspector,
        cloud_share_service=cloud_share_service,
        clips_dir=clips_dir,
        event_clips_dir=event_clips_dir,
        preview_server=preview_server,
    )
    browser_local = _build_browser_local_adapter(
        user_config, settings, api, clips_dir, event_clips_dir
    )
    live_view = _build_live_view_adapter(user_config, settings, api)

    req_server, req_client = _wire_request_system(user_config, settings, api)
    _wire_failure_callbacks(backend, api, is_operator_daemon=(user_config.role == OPERATOR))

    api.settings.set_restart_encoder_cb(_make_restart_recording_cb(recording_service, settings))
    api.settings.set_autorecord_cb(_make_autorecord_cb(recording_service))

    _stop_backend = _make_stop_backend_cb(
        backend, detection_service, req_server, req_client, preview_server, browser_local, live_view
    )

    # ── Role-conditional topology (ADR-0010): headless daemon / sidecar ──
    # Operator = --daemon (decoupled, survives the Tauri window closing);
    # everyone else = --sidecar (launched by Tauri, stops on stdin shutdown,
    # TD-3). QML is gone (F3) — this is the only path now.
    mode = resolve_mode(sys.argv, role=user_config.role)
    from app.adapters.ipc.pipe_server import NamedPipeIpcServer  # noqa: PLC0415
    from app.adapters.ipc.router import IpcRouter                # noqa: PLC0415
    from app.runtime.headless import HeadlessRuntime             # noqa: PLC0415

    _wire_hot_plug(detection_service, backend, api)

    pipe_server = NamedPipeIpcServer(IpcRouter(api), api.bus)
    runtime = HeadlessRuntime(api, pipe_server, on_stop=_stop_backend)
    # Role change (first-run wizard or an IT-initiated change) stops this
    # runtime cleanly (same teardown as SIGTERM), then main() relaunches.
    api.settings.set_relaunch_cb(runtime.request_stop)

    def _start_recording_async() -> None:
        """Run the recording stack's startup off the main thread.

        See _start_recording_services' docstring: this is where the FFmpeg
        capture-backend/encoder probes (each up to 8-12s, uncached across
        monitors) used to block — synchronously, before the IPC pipe even
        existed. Running them here lets the pipe bind immediately so the UI
        connects right away instead of appearing hung during a slow probe.
        """
        if runtime.stop_requested():
            return  # shutdown raced startup — nothing to do
        try:
            _start_recording_services(
                backend, user_config, detection_service, settings, preview_server, browser_local, live_view
            )
            _recover_startup_clips(backend, settings)
        except Exception:
            logger.exception("[startup] recording stack failed to start.")
            return
        if backend.health_service is not None and not runtime.stop_requested():
            backend.health_service.start()

    threading.Thread(
        target=_start_recording_async, daemon=True, name="recording-startup"
    ).start()

    logger.info("Headless '{}' mode — serving IPC contract.", mode)
    code = runtime.serve_daemon() if mode == DAEMON else runtime.serve_sidecar()
    if _relaunch_flag["requested"]:
        from app.infrastructure.relaunch import relaunch_and_exit  # noqa: PLC0415
        relaunch_and_exit(
            teardown=lambda: None,
            release_lock=lambda: _release_single_instance_lock(_instance_lock),
            # api.settings.role is the NEW role (set_role already mutated it);
            # user_config is a stale snapshot from before the change.
            mode_args=["--daemon"] if api.settings.role == OPERATOR else ["--sidecar"],
        )
    _release_single_instance_lock(_instance_lock)
    sys.exit(code)


if __name__ == "__main__":
    main()
