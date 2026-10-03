"""daemon_root - composition root of the Operator recording + LAN-streaming daemon.

Replaces the monorepo's ``main.py`` + ``runtime/backend.py`` (spec section 4).
It wires, in this order:

    config -> monitors -> RecordingService + health -> LiveViewLanAdapter (+ TLS bundle)

Differences from the monorepo, all deliberate:

* Fixed Operator role: no ``enforce_role``, no role/IT-PIN/user-config files.
  Auto-record is always on; autostart + the Scheduled-Task watchdog are kept.
* No ``ApiLayer``/event bus/IPC pipe/Tauri: the LAN adapter gets ``DaemonApi``,
  the two-method facade it actually consumes.
* No event/ML pipeline (``auto_event_service``), no MJPEG ``preview_server``
  (ADR-0003): neither is used by
  recording or LAN streaming in the Operator flow.
* Control is a CLI (``start|stop|status|health``) plus small state files
  (``app.runtime.instance``).

Exit codes: 0 clean stop / benign second instance; 1 no monitors (non-zero so
the restart watchdog retries); 3 ``status`` when not running.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger

from app import __version__
from app.core.disk_monitor import DiskSpaceMonitor
from app.core.monitor_detection.service import MonitorDetectionService
from app.core.recording_health.service import RecordingHealthService
from app.core.recording_service.buffer_manager import BufferManager
from app.core.recording_service.clip_builder import ClipBuilder
from app.core.recording_service.models import MonitorInfo, Segment
from app.core.recording_service.monitor_worker import MonitorWorker
from app.core.recording_service.service import RecordingService
from app.core.recording_service.supervisor import RecorderSupervisor
from app.core.ports.segment_compiler_port import SegmentCompilerPort
from app.daemon_api import DaemonApi
from app.infrastructure.config import Settings, get_settings
from app.infrastructure.logging_setup import configure_logging
from app.infrastructure.proc_telemetry import configure_telemetry, get_telemetry
from app.runtime import instance
from app.runtime.headless import HeadlessRuntime

EXIT_OK = 0
EXIT_NO_MONITORS = 1
EXIT_NOT_RUNNING = 3
# A status older than this means the daemon is hung or dead (tick is ~2 s).
STATUS_STALE_SECONDS = 30.0

_DEFAULT = object()


class NoMonitorsError(RuntimeError):
    """The recording role needs at least one monitor."""


# ── Recording backend (ported from runtime/backend.py, events path removed) ──

@dataclass
class RecordingBackend:
    combined_builder: object = None
    per_monitor_builders: Dict[int, object] = field(default_factory=dict)
    workers: List[MonitorWorker] = field(default_factory=list)
    preview_paths: Dict[int, Path] = field(default_factory=dict)
    recording_service: Optional[RecordingService] = None
    clip_builder: Optional[ClipBuilder] = None
    disk_monitor: Optional[DiskSpaceMonitor] = None
    health_service: Optional[RecordingHealthService] = None
    build_worker_for: Optional[Callable[[MonitorInfo], MonitorWorker]] = None


def build_worker(monitor, storage, settings, builder, preview_path: Optional[Path] = None) -> MonitorWorker:
    """Factory: a fully-wired MonitorWorker for one physical monitor."""
    from app.adapters.ffmpeg.recorder_adapter import FFmpegRecorderAdapter  # noqa: PLC0415

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
        capture_backend=settings.capture_backend,
        capture_pipeline=settings.capture_pipeline,
        codec=settings.video_codec,
        on_segment_ready=buffer.register_segment,
        on_crash=supervisor.notify_crash,
        preview_path=preview_path,
        # The LAN adapter fans out this same recorder-owned JPEG; it must not
        # launch another capture process just to provide viewer fluency.
        preview_fps=10 if settings.live_view_enabled else 2,
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


def build_recording_backend(
    *,
    settings: Settings,
    storage,
    all_monitors: List[MonitorInfo],
    segment_compiler: Optional[SegmentCompilerPort] = None,
) -> RecordingBackend:
    from app.adapters.ffmpeg.combined_clip_builder import CombinedClipBuilder  # noqa: PLC0415
    from app.adapters.ffmpeg.hourly_recording_builder import HourlyRecordingBuilder  # noqa: PLC0415
    from app.adapters.ffmpeg.process_guard import (  # noqa: PLC0415
        configure_batch_concurrency,
        configure_batch_governance,
    )
    from app.adapters.ffmpeg.timestamp_adapter import FFmpegTimestampAdapter  # noqa: PLC0415
    from app.adapters.ffmpeg.trim_adapter import FFmpegTrimAdapter  # noqa: PLC0415
    from app.adapters.native import make_clip_adapter  # noqa: PLC0415

    # Shared batch Job Object + concurrency semaphore before any FFmpeg spawns
    # (ffmpeg-pipeline-optimization-research.md section 4, ADR-0015).
    configure_batch_governance(
        weight=settings.batch_job_weight,
        memory_limit_mb=settings.batch_job_memory_limit_mb,
        cpu_hard_cap_percent=settings.batch_cpu_hard_cap_percent,
    )
    configure_batch_concurrency(settings.max_batch_ffmpeg)
    configure_telemetry(settings.proc_telemetry_interval_seconds)

    backend = RecordingBackend()
    combined = CombinedClipBuilder(
        raw_dir=settings.raw_clips_dir,
        output_dir=settings.clips_dir,
        monitor_count=len(all_monitors),
        monitor_indices=[m.index for m in all_monitors],
        timestamp_adapter=FFmpegTimestampAdapter(codec=settings.video_codec),
        codec=settings.video_codec,
        cell_width=settings.combined_cell_width,
        cell_height=settings.combined_cell_height,
        quality=settings.combined_quality,
        window_minutes=settings.clip_window_minutes,
    )
    backend.combined_builder = combined

    def _make_builder(monitor: MonitorInfo):
        b = HourlyRecordingBuilder(
            output_dir=settings.raw_clips_dir,
            monitor_count=1,
            monitor_index=monitor.index,
            window_minutes=settings.clip_window_minutes,
            max_size_mb=settings.clip_max_size_mb,
            on_clip_ready=lambda clip_path, window_key, real_start: combined.on_clip_ready(
                clip_path, window_key, real_start
            ),
            codec=settings.video_codec,
        )
        backend.per_monitor_builders[monitor.index] = b
        return b

    def _build_worker_for(monitor: MonitorInfo, preview_path: Optional[Path] = None) -> MonitorWorker:
        return build_worker(monitor, storage, settings, _make_builder(monitor), preview_path)

    backend.build_worker_for = _build_worker_for

    for m in all_monitors:
        preview_path = settings.segment_dir / f"m{m.index}" / "preview.jpg"
        backend.preview_paths[m.index] = preview_path
        backend.workers.append(_build_worker_for(m, preview_path))
    for w in backend.workers:
        w.segment_dir.mkdir(parents=True, exist_ok=True)

    backend.recording_service = RecordingService(workers=backend.workers)
    # Continuous recording feeds every monitor into the combined review clip.
    backend.recording_service.change_monitors(all_monitors)

    clip_compiler = (
        make_clip_adapter(segment_compiler, settings.clip_engine) if segment_compiler is not None else None
    )
    backend.clip_builder = ClipBuilder(
        recording_service=backend.recording_service,
        clip_adapter=FFmpegTrimAdapter(codec=settings.video_codec, segment_compiler=clip_compiler),
        clips_dir=settings.event_clips_dir,
        pre_seconds=settings.event_pre_seconds,
        post_seconds=settings.event_post_seconds,
        timestamp_adapter=FFmpegTimestampAdapter(codec=settings.video_codec),
    )
    backend.disk_monitor = DiskSpaceMonitor(
        segment_dir=settings.segment_dir,
        on_low_disk=backend.recording_service.stop,
        warn_threshold_bytes=settings.disk_warn_bytes,
        stop_threshold_bytes=settings.disk_stop_bytes,
    )
    backend.health_service = RecordingHealthService(
        recording_service=backend.recording_service,
        poll_interval_seconds=30.0,
        background_services={},
    )
    return backend


# ── Daemon assembly + lifecycle ───────────────────────────────────────────────

def _default_live_view_factory(settings, api, tls):
    from app.adapters.live_view_lan import LiveViewLanAdapter  # noqa: PLC0415

    return LiveViewLanAdapter(settings, api, tls)


def _default_tls_factory(settings):
    from app.adapters.tls_provisioning import build_tls_material  # noqa: PLC0415

    return build_tls_material(settings)


@dataclass
class Daemon:
    settings: Settings
    detection: MonitorDetectionService
    backend: RecordingBackend
    api: DaemonApi
    live_view: Optional[object] = None
    _startup: Optional[threading.Thread] = None
    _stopping: threading.Event = field(default_factory=threading.Event)
    _stopped: bool = False

    def start(self, *, start_recording: bool = True, background: bool = True) -> None:
        """Bring the daemon up.  The LAN endpoint comes first and is cheap; the
        recording start-up (FFmpeg probes can burn 8-12 s each on a flaky GPU
        driver) runs on a background thread so it cannot delay the endpoint."""
        if self.live_view is not None:
            self.live_view.start()
        if not background:
            self._start_services(start_recording)
            return
        self._startup = threading.Thread(
            target=self._start_services, args=(start_recording,), daemon=True, name="recording-startup"
        )
        self._startup.start()

    def _start_services(self, start_recording: bool) -> None:
        if self._stopping.is_set():
            return
        try:
            rs = self.backend.recording_service
            if start_recording and rs is not None and not self._stopping.is_set():
                rs.start()
            else:
                logger.info("Recording not started at launch (start_recording=False).")
            if self._stopping.is_set():
                return
            if self.backend.disk_monitor is not None:
                self.backend.disk_monitor.start()
            self.detection.start()
            if start_recording and not self._stopping.is_set():
                self._recover_startup_clips()
        except Exception:
            logger.exception("[startup] recording stack failed to start.")
            return
        # Last: its first poll must not report "degraded" for a recorder that
        # simply has not been asked to start yet.
        if self.backend.health_service is not None and not self._stopping.is_set():
            self.backend.health_service.start()

    def _recover_startup_clips(self) -> None:
        """Rebuild clips from segments already on disk (crash/restart recovery)."""
        for w in self.backend.workers:
            b = self.backend.per_monitor_builders[w.monitor.index]
            segs = list(w.buffer.all_segments())
            if segs:
                logger.info("Clip recovery for m{} - {} segment(s) in buffer.", w.monitor.index, len(segs))
                b.recover_from_segments(segs)
        if self.backend.combined_builder is not None:
            self.backend.combined_builder.recover(backfill_hours=self.settings.retention_hours)

    def stop(self) -> None:
        """Full teardown; stops FFmpeg so no orphans remain (TD-3). Idempotent."""
        if self._stopped:
            return
        self._stopped = True
        self._stopping.set()
        if self._startup is not None and self._startup is not threading.current_thread():
            self._startup.join(timeout=15)
            if self._startup.is_alive():
                logger.warning("[stop] recording start-up still running after 15 s; stopping anyway.")
        b = self.backend
        steps: list[tuple[str, Optional[Callable[[], None]]]] = [
            ("health", b.health_service.stop if b.health_service is not None else None),
            ("detection", self.detection.stop),
            ("disk monitor", b.disk_monitor.stop if b.disk_monitor is not None else None),
            # Always reached even if an earlier step raised: it kills the ffmpeg children.
            ("recording", b.recording_service.stop if b.recording_service is not None else None),
        ]
        steps += [(f"builder m{i}", pb.shutdown) for i, pb in b.per_monitor_builders.items()]
        if b.combined_builder is not None:
            steps.append(("combined builder", b.combined_builder.shutdown))
        steps.append(("telemetry", get_telemetry().stop))
        if self.live_view is not None:
            steps.append(("live view", self.live_view.stop))
        for name, fn in steps:
            if fn is None:
                continue
            try:
                fn()
            except Exception:  # noqa: BLE001 - one failing step must not skip the rest
                logger.exception("[stop] {} failed", name)

    def status(self) -> dict:
        state = self.api.recording.get_recording_state()
        return {
            "version": __version__,
            "recording": state.is_recording,
            "record_seconds": state.record_seconds,
            "monitors": len(self.api.recording.get_monitors()),
            "live_view": self.live_view is not None,
        }


def build_daemon(
    settings: Settings,
    *,
    monitor_port=None,
    segment_compiler=_DEFAULT,
    live_view_factory=None,
    tls_factory=None,
) -> Daemon:
    from app.adapters.filesystem.storage_adapter import FilesystemStorageAdapter  # noqa: PLC0415

    for d in (settings.segment_dir, settings.clips_dir, settings.raw_clips_dir, settings.event_clips_dir):
        d.mkdir(parents=True, exist_ok=True)
    logger.info(
        "Output directories ready: segments={} clips={} raw={} events={}",
        settings.segment_dir, settings.clips_dir, settings.raw_clips_dir, settings.event_clips_dir,
    )

    if monitor_port is None:
        from app.adapters.monitor.screeninfo_adapter import ScreeninfoMonitorAdapter  # noqa: PLC0415

        monitor_port = ScreeninfoMonitorAdapter()
    detection = MonitorDetectionService(monitor_port=monitor_port, poll_interval_seconds=5.0)
    all_monitors = detection.detect_now()
    if not all_monitors:
        raise NoMonitorsError("No monitors detected - cannot start recording.")

    if segment_compiler is _DEFAULT:
        from app.adapters.native import make_segment_compiler  # noqa: PLC0415

        # Rust engine when available, FFmpeg fallback otherwise (ADR-0006).
        segment_compiler = make_segment_compiler(codec=settings.video_codec)

    backend = build_recording_backend(
        settings=settings,
        storage=FilesystemStorageAdapter(),
        all_monitors=all_monitors,
        segment_compiler=segment_compiler,
    )
    api = DaemonApi(backend.recording_service, detection.get_monitors)

    live_view = None
    if settings.live_view_enabled:
        try:
            tls = (tls_factory or _default_tls_factory)(settings)
            live_view = (live_view_factory or _default_live_view_factory)(settings, api, tls)
        except Exception as exc:  # noqa: BLE001 - never sacrifice recording for live view
            logger.error("[live-view] unavailable: {}", exc)

    # Hot-plug: new/removed displays add/remove recording workers.
    rs = backend.recording_service

    def _hot_add(monitor: MonitorInfo) -> None:
        w = backend.build_worker_for(monitor)
        w.segment_dir.mkdir(parents=True, exist_ok=True)
        rs.add_worker(w)

    detection._on_monitor_added = _hot_add  # noqa: SLF001
    detection._on_monitor_removed = rs.remove_worker  # noqa: SLF001

    return Daemon(settings=settings, detection=detection, backend=backend, api=api, live_view=live_view)


# ── Launcher / watchdog (ported from core.role._setup_operator_launcher) ─────

def ensure_launcher(autostart_module, scheduled_task_module) -> str:
    """Operator restart watchdog: Scheduled Task is the sole launcher; the HKCU
    Run key is the degraded fallback (corporate policy may forbid tasks)."""
    if scheduled_task_module is not None:
        try:
            if scheduled_task_module.ensure_registered():
                autostart_module.set_autostart(False)  # task is the sole launcher
                return "task"
        except Exception:  # noqa: BLE001 - registration must never crash startup
            logger.exception("scheduled task registration failed.")
    autostart_module.set_autostart(True, launch_args=["--daemon"])
    logger.warning("Scheduled-task watchdog unavailable - fell back to the HKCU Run key (no restart-on-kill).")
    return "runkey"


def _register_ffmpeg_cleanup() -> None:
    """Last-resort atexit net: kill child ffmpeg processes (races with stop())."""
    import psutil  # noqa: PLC0415

    def _cleanup() -> None:
        try:
            for child in psutil.Process(os.getpid()).children(recursive=True):
                if "ffmpeg" in child.name().lower():
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
        except Exception:  # noqa: BLE001
            pass

    atexit.register(_cleanup)


def run_daemon(
    settings: Settings,
    *,
    monitor_port=None,
    segment_compiler=_DEFAULT,
    live_view_factory=None,
    tls_factory=None,
    start_recording: bool = True,
    install_signals: bool = True,
    poll_seconds: float = 2.0,
    register_launcher: bool = True,
    lock_wait_seconds: float = 25.0,
) -> int:
    state_dir = settings.segment_dir.parent
    lock = instance.InstanceLock(state_dir)
    # A relaunch (watchdog, stop+start, update) can race the previous instance's
    # graceful shutdown (up to ~20 s); wait for it like the monorepo mutex did.
    deadline = time.monotonic() + lock_wait_seconds
    acquired = lock.acquire()
    while not acquired and time.monotonic() < deadline:
        time.sleep(0.25)
        acquired = lock.acquire()
    if not acquired:
        # Benign collision: exit 0 so the restart watchdog does not read it as a crash.
        logger.info("Another daemon instance is already running - exiting quietly.")
        return EXIT_OK
    try:
        instance.clear_stop(state_dir)  # stale request from a previous run
        _register_ffmpeg_cleanup()
        if register_launcher:
            from app.infrastructure import autostart, scheduled_task  # noqa: PLC0415

            logger.info("watchdog: {}", ensure_launcher(autostart, scheduled_task))
        try:
            daemon = build_daemon(
                settings,
                monitor_port=monitor_port,
                segment_compiler=segment_compiler,
                live_view_factory=live_view_factory,
                tls_factory=tls_factory,
            )
        except NoMonitorsError as exc:
            logger.critical("{}", exc)
            return EXIT_NO_MONITORS

        def _tick() -> None:
            instance.write_status(state_dir, daemon.status())

        runtime = HeadlessRuntime(
            state_dir, on_stop=daemon.stop, on_tick=_tick,
            install_signals=install_signals, poll_seconds=poll_seconds,
        )
        # Handlers first: a SIGINT/SIGTERM during live-view start-up (up to 8 s)
        # must request a stop, not kill the process past the teardown.
        runtime.install_signal_handlers()
        try:
            daemon.start(start_recording=start_recording)
            logger.info("Daemon {} up (recording={}).", __version__, start_recording)
            return runtime.serve()
        except BaseException:
            daemon.stop()
            raise
    finally:
        lock.release()


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="the-watcher-daemon", description="Recording + LAN streaming daemon")
    p.add_argument(
        "command", nargs="?", default="start", choices=["start", "stop", "status", "health"],
        help="start (default, foreground) | stop | status | health",
    )
    # Scheduled tasks / Run-key entries registered by the monorepo build pass --daemon.
    p.add_argument("--daemon", dest="legacy_daemon", action="store_true", help="alias of 'start'")
    return p.parse_args(argv)


def _cmd_status(settings: Settings) -> int:
    state_dir = settings.segment_dir.parent
    st = instance.read_status(state_dir)
    if st is None or not instance.pid_alive(st.get("pid")):
        print("not running")
        return EXIT_NOT_RUNNING
    st = {**st, "age_seconds": round(instance.status_age_seconds(st), 1)}
    print(json.dumps(st, sort_keys=True))
    return EXIT_OK


def _cmd_health(settings: Settings) -> int:
    st = instance.read_status(settings.segment_dir.parent)
    if st is None or not instance.pid_alive(st.get("pid")):
        print("unhealthy: not running")
        return 1
    if instance.status_age_seconds(st) > STATUS_STALE_SECONDS:
        print("unhealthy: status is stale (daemon hung?)")
        return 1
    if not st.get("recording"):
        print("unhealthy: not recording")
        return 1
    print("healthy")
    return 0


def main(argv: Optional[List[str]] = None, *, settings: Optional[Settings] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    settings = settings or get_settings()
    if args.command == "stop":
        instance.request_stop(settings.segment_dir.parent)
        print("stop requested")
        return EXIT_OK
    if args.command == "status":
        return _cmd_status(settings)
    if args.command == "health":
        return _cmd_health(settings)
    configure_logging(settings.log_level)
    return run_daemon(settings)


if __name__ == "__main__":
    sys.exit(main())
