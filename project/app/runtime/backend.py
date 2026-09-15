"""build_recording_backend — construct the recording stack, headless-safe (ADR-0010).

Extracted verbatim from ``main.py`` so both the Qt entrypoint and the headless
daemon/sidecar build the *same* backend.  It contains no Qt: just the recording
services/adapters.  Non-recording roles (supervisor / unconfigured) get an empty
backend.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

from loguru import logger

from app.adapters.ffmpeg.recorder_adapter import FFmpegRecorderAdapter
from app.adapters.ffmpeg.trim_adapter import FFmpegTrimAdapter
from app.adapters.ffmpeg.timestamp_adapter import FFmpegTimestampAdapter
from app.adapters.ffmpeg.hourly_recording_builder import HourlyRecordingBuilder
from app.adapters.ffmpeg.combined_clip_builder import CombinedClipBuilder
from app.adapters.ffmpeg.process_guard import configure_batch_concurrency, configure_batch_governance
from app.adapters.filesystem.storage_adapter import FilesystemStorageAdapter
from app.adapters.ml.iou_tracker import IouTracker
from app.adapters.ml.live_inference_service import LiveInferenceService
from app.adapters.ml.mock_detector import MockDetectorAdapter
from app.adapters.native import make_clip_adapter
from app.adapters.storage.sqlite_analytics import SqliteAnalyticsAdapter
from app.adapters.storage.sqlite_event_store import SqliteEventStoreAdapter
from app.core.analytics.batch_clip_analyzer import BatchClipAnalyzer
from app.core.analytics.manual_event import analytic_event_from_context
from app.core.analytics.models import AnalyticEvent
from app.core.analytics.sidecar import write_sidecar
from app.core.auto_event_service import AutoEventService
from app.core.disk_monitor import DiskSpaceMonitor
from app.core.event_service import EventService
from app.core.ports.segment_compiler_port import SegmentCompilerPort
from app.core.recording_health.service import RecordingHealthService
from app.core.recording_service.buffer_manager import BufferManager
from app.core.recording_service.clip_builder import ClipBuilder
from app.core.recording_service.models import EventContext, MonitorInfo, Segment
from app.core.recording_service.monitor_worker import MonitorWorker
from app.core.recording_service.service import RecordingService
from app.core.recording_service.supervisor import RecorderSupervisor
from app.core.role import is_recording_role
from app.infrastructure.proc_telemetry import configure_telemetry, get_telemetry


def build_worker(
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
        capture_backend=settings.capture_backend,
        capture_pipeline=settings.capture_pipeline,
        codec=settings.video_codec,
        on_segment_ready=buffer.register_segment,
        on_crash=supervisor.notify_crash,
        preview_path=preview_path,
        # The LAN adapter fans out this same recorder-owned JPEG; it must not
        # launch another capture process merely to provide Supervisor fluency.
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


@dataclass
class RecordingBackend:
    """The recording stack for a role — empty for non-recording roles."""

    combined_builder: Optional[CombinedClipBuilder] = None
    per_monitor_builders: Dict[int, HourlyRecordingBuilder] = field(default_factory=dict)
    workers: List[MonitorWorker] = field(default_factory=list)
    preview_paths: Dict[int, Path] = field(default_factory=dict)
    recording_service: Optional[RecordingService] = None
    clip_builder: Optional[ClipBuilder] = None
    event_service: Optional[EventService] = None
    disk_monitor: Optional[DiskSpaceMonitor] = None
    health_service: Optional[RecordingHealthService] = None
    event_store: Optional[SqliteEventStoreAdapter] = None
    auto_event_service: Optional[AutoEventService] = None
    batch_analyzer: Optional[BatchClipAnalyzer] = None
    live_service: Optional[LiveInferenceService] = None
    analytics: Optional[SqliteAnalyticsAdapter] = None
    # Factory to build a worker for a hot-added monitor (None on non-recording roles).
    build_worker_for: Optional[Callable[[MonitorInfo], MonitorWorker]] = None

    @property
    def records(self) -> bool:
        return self.recording_service is not None


def build_recording_backend(
    *,
    settings,
    user_config,
    storage: FilesystemStorageAdapter,
    all_monitors: List[MonitorInfo],
    clips_dir: Path,
    raw_clips_dir: Path,
    event_clips_dir: Path,
    segment_compiler: Optional[SegmentCompilerPort] = None,
) -> RecordingBackend:
    """Build the recording stack (or an empty backend for non-recording roles)."""
    if not is_recording_role(user_config.role):
        logger.info(
            "Non-recording role '{}' — recording stack not built.",
            user_config.role or "(not configured)",
        )
        return RecordingBackend()

    # PoC-2 governance (ffmpeg-pipeline-optimization-research.md §4): configure
    # the shared batch Job Object + concurrency semaphore before any builder,
    # converter, or analyzer can spawn an FFmpeg process.
    configure_batch_governance(
        weight=settings.batch_job_weight,
        memory_limit_mb=settings.batch_job_memory_limit_mb,
        cpu_hard_cap_percent=settings.batch_cpu_hard_cap_percent,
    )
    configure_batch_concurrency(settings.max_batch_ffmpeg)
    configure_telemetry(settings.proc_telemetry_interval_seconds)
    get_telemetry().start()

    backend = RecordingBackend()
    backend.combined_builder = CombinedClipBuilder(
        raw_dir=raw_clips_dir,
        output_dir=clips_dir,
        monitor_count=len(all_monitors),
        monitor_indices=[m.index for m in all_monitors],
        timestamp_adapter=FFmpegTimestampAdapter(codec=settings.video_codec),
        codec=settings.video_codec,
        cell_width=settings.combined_cell_width,
        cell_height=settings.combined_cell_height,
        quality=settings.combined_quality,
        window_minutes=settings.clip_window_minutes,
    )

    def _make_builder(monitor: MonitorInfo) -> HourlyRecordingBuilder:
        def _on_clip_ready(clip_path: Path, window_key: str, real_start: datetime) -> None:
            backend.combined_builder.on_clip_ready(clip_path, window_key, real_start)
            if backend.batch_analyzer is not None:
                backend.batch_analyzer.queue_clip(clip_path, real_start)

        b = HourlyRecordingBuilder(
            output_dir=raw_clips_dir,
            monitor_count=1,
            monitor_index=monitor.index,
            window_minutes=settings.clip_window_minutes,
            max_size_mb=settings.clip_max_size_mb,
            on_clip_ready=_on_clip_ready,
            codec=settings.video_codec,
        )
        backend.per_monitor_builders[monitor.index] = b
        return b

    def _build_worker_for(monitor: MonitorInfo, preview_path: "Path | None" = None) -> MonitorWorker:
        return build_worker(monitor, storage, settings, _make_builder(monitor), preview_path)

    backend.build_worker_for = _build_worker_for

    for m in all_monitors:
        preview_path = settings.segment_dir / f"m{m.index}" / "preview.jpg"
        backend.preview_paths[m.index] = preview_path
        backend.workers.append(_build_worker_for(m, preview_path))
    for w in backend.workers:
        w.segment_dir.mkdir(parents=True, exist_ok=True)

    backend.recording_service = RecordingService(workers=backend.workers)

    # Continuous recording must feed every monitor into the combined review
    # clip. The legacy saved selection was event-specific and its empty state
    # silently chose only the primary display.
    backend.recording_service.change_monitors(all_monitors)

    clip_compiler = (
        make_clip_adapter(segment_compiler, settings.clip_engine)
        if segment_compiler is not None
        else None
    )
    backend.clip_builder = ClipBuilder(
        recording_service=backend.recording_service,
        clip_adapter=FFmpegTrimAdapter(codec=settings.video_codec, segment_compiler=clip_compiler),
        clips_dir=event_clips_dir,
        pre_seconds=settings.event_pre_seconds,
        post_seconds=settings.event_post_seconds,
        timestamp_adapter=FFmpegTimestampAdapter(codec=settings.video_codec),
    )

    # Event persistence — manual events become queryable AnalyticEvents + sidecar.
    backend.event_store = SqliteEventStoreAdapter(settings.segment_dir.parent / "events.db")

    # The event/ML pipeline is intentionally opt-in while continuous recording
    # is stabilised. Keep the event store because it is also the audit store,
    # but do not start inference, automatic events or event-clip FFmpeg jobs.
    # getattr(..., True) preserves minimal legacy test/settings fixtures.
    if not getattr(settings, "events_enabled", True):
        logger.info("[backend] event pipeline disabled (EVENTS_ENABLED=false).")
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
            hang_grace_seconds=settings.event_pipeline_hang_grace_seconds,
        )
        return backend

    def _persist_manual_event(ctx, output_path) -> None:
        ev = analytic_event_from_context(ctx, output_path)
        backend.event_store.add(ev)
        try:
            write_sidecar(output_path, [ev])
        except OSError:
            logger.warning("Could not write event sidecar for {}", output_path)

    backend.event_service = EventService(
        clip_builder=backend.clip_builder,
        post_seconds=settings.event_post_seconds,
        cooldown_seconds=settings.event_cooldown_seconds,
        retry_delay_seconds=settings.clip_retry_delay_seconds,
        on_clip_built=_persist_manual_event,
    )

    # Fase 2/3 — automatic detection pipeline.
    # Use OnnxDetectorAdapter when ONNX_MODEL_PATH is configured; fall back to mock.
    _onnx_path = settings.onnx_model_path
    if _onnx_path:
        from app.adapters.ml.onnx_detector import OnnxDetectorAdapter
        _detector = OnnxDetectorAdapter(
            model_path=_onnx_path,
            device=settings.inference_device,
        )
        logger.info("[backend] ONNX detector: {} (device={})", _onnx_path, settings.inference_device)
    else:
        _detector = MockDetectorAdapter()
        logger.info("[backend] no ONNX model configured — using mock detector")

    # Guards how often a detection schedules a full clip BUILD (as opposed to
    # EVENT_COOLDOWN_SECONDS, which only gates how often a detection becomes an
    # AnalyticEvent for analytics/timeline purposes). Without this, continuous
    # detections (e.g. a person lingering) each scheduled their own full
    # multi-monitor re-encode — with a 4-minute clip window and a 30s event
    # cooldown that meant up to 8 heavily-overlapping clips for one visit.
    _auto_build_lock = threading.Lock()
    _last_auto_build_at: Optional[datetime] = None
    _auto_build_min_interval = timedelta(
        seconds=settings.event_auto_build_min_interval_seconds
    )

    def _on_auto_event(event: AnalyticEvent) -> None:
        nonlocal _last_auto_build_at
        # Guarded: this runs synchronously inside LiveInferenceService's
        # "live-inference" thread (via AutoEventService._on_detections). ADR-0019
        # guarded the build step (schedule_clip_build) but an exception here —
        # e.g. a SQLite hiccup — used to propagate straight back into that thread
        # and kill it permanently, silently ending all future auto-events/clips.
        try:
            backend.event_store.add(event)
        except Exception:
            logger.exception("[auto-event] failed to persist event {} — continuing.", event.event_id)

        with _auto_build_lock:
            if (
                _last_auto_build_at is not None
                and event.start - _last_auto_build_at < _auto_build_min_interval
            ):
                logger.debug(
                    "[auto-event] clip build coalesced — already covered by a pending/recent build."
                )
                return
            _last_auto_build_at = event.start

        try:
            ctx = backend.clip_builder.snapshot_event(event.start)
        except Exception:
            logger.exception("[auto-event] snapshot_event failed for {} — clip not built.", event.event_id)
            return

        def _persist_auto_clip(_ctx: EventContext, output: Path) -> None:
            updated = event.model_copy(update={"clip_path": output})
            backend.event_store.add(updated)
            try:
                write_sidecar(output, [updated])
            except OSError:
                logger.warning("[auto-event] could not write sidecar for {}", output)

        # Routed through EventService.schedule_clip_build (not a bespoke timer)
        # so auto-event builds get the same retry-on-failure and success/error
        # logging as manual events — previously an exception here died silently
        # inside the Timer thread with no log line at all.
        backend.event_service.schedule_clip_build(ctx, on_built=_persist_auto_clip)

    # Fase 4 — wrap detector in LiveInferenceService (motion gate + tracker).
    # AutoEventService subscribes to live_service, not the raw detector, so the
    # motion gate and stable track IDs are applied before any event is emitted.
    # BatchClipAnalyzer retains the raw _detector (no motion gate needed there).
    _tracker = IouTracker(
        iou_threshold=settings.tracker_iou_threshold,
        max_age=settings.tracker_max_age,
    )
    backend.live_service = LiveInferenceService(
        detector=_detector,
        preview_paths=backend.preview_paths,
        motion_threshold=settings.motion_threshold,
        poll_interval=settings.live_poll_interval,
        tracker=_tracker,
    )

    backend.auto_event_service = AutoEventService(
        detector=backend.live_service,
        on_event=_on_auto_event,
        confidence_threshold=0.6,
        cooldown_seconds=settings.event_cooldown_seconds,
        zones=[],  # populated from config / UI in a later iteration
    )

    # Fase 3 — batch analysis of closed clips using the same detector + event pipeline.
    # on_batch_event: clip already exists, so just persist the event + sidecar.
    def _on_batch_event(event: AnalyticEvent, source_clip: Path) -> None:
        backend.event_store.add(event)
        try:
            write_sidecar(source_clip, [event])
        except OSError:
            logger.warning("[batch-event] could not write sidecar for {}", source_clip)

    backend.batch_analyzer = BatchClipAnalyzer(
        detector=_detector,
        on_batch_event=_on_batch_event,
        confidence_threshold=0.6,
        cooldown_seconds=settings.event_cooldown_seconds,
        frame_interval_seconds=settings.batch_frame_interval,
    )

    backend.analytics = SqliteAnalyticsAdapter(backend.event_store)

    backend.disk_monitor = DiskSpaceMonitor(
        segment_dir=settings.segment_dir,
        on_low_disk=backend.recording_service.stop,
        warn_threshold_bytes=settings.disk_warn_bytes,
        stop_threshold_bytes=settings.disk_stop_bytes,
    )

    backend.health_service = RecordingHealthService(
        recording_service=backend.recording_service,
        poll_interval_seconds=30.0,
        background_services={"live-inference": backend.live_service},
        hang_grace_seconds=settings.event_pipeline_hang_grace_seconds,
    )
    return backend
