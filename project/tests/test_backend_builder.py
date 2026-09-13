"""build_recording_backend — non-recording roles get an empty backend (ADR-0010),
and the recording-role path wires every service without touching real ffmpeg.

Constructing the recording stack (FFmpegRecorderAdapter, RecordingService, etc.)
does not itself spawn any subprocess — that only happens when something later
calls .start() on a worker/recorder, which is main.py's job, not
build_recording_backend()'s. So the recording-role branch can be exercised
directly with a real (filesystem-backed) storage adapter and a fake monitor,
with no ffmpeg binary required.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.filesystem.storage_adapter import FilesystemStorageAdapter
from app.core.recording_service.models import MonitorInfo
from app.infrastructure.proc_telemetry import get_telemetry
from app.runtime.backend import RecordingBackend, build_recording_backend


class _Storage:
    pass


def _settings(tmp_path):
    return SimpleNamespace(
        segment_dir=tmp_path / "segments",
        video_codec="h264",
    )


def _recording_settings(tmp_path):
    """Every field build_recording_backend()'s recording-role path reads."""
    return SimpleNamespace(
        segment_dir=tmp_path / "segments",
        video_codec="h264",
        clip_engine="ffmpeg",
        live_view_enabled=False,
        capture_source="desktop",
        capture_backend="auto",
        capture_pipeline="auto",
        capture_framerate=30,
        output_width=1920,
        output_height=1080,
        crf=28,
        combined_cell_width=1280,
        combined_cell_height=720,
        combined_quality=27,
        max_recorder_restarts=10,
        retention_hours=1,
        segment_duration=300,
        clip_window_minutes=60,
        clip_max_size_mb=3072,
        event_pre_seconds=120,
        event_post_seconds=120,
        event_cooldown_seconds=30,
        event_auto_build_min_interval_seconds=240,
        event_pipeline_hang_grace_seconds=300,
        clip_retry_delay_seconds=30,
        onnx_model_path="",
        inference_device="cpu",
        batch_frame_interval=1,
        motion_threshold=0.015,
        live_poll_interval=0.5,
        tracker_iou_threshold=0.3,
        tracker_max_age=5,
        disk_warn_bytes=2 * 1024**3,
        disk_stop_bytes=512 * 1024**2,
        batch_job_weight=2,
        batch_job_memory_limit_mb=1536,
        batch_cpu_hard_cap_percent=0,
        max_batch_ffmpeg=1,
        proc_telemetry_interval_seconds=10.0,
    )


def test_supervisor_gets_empty_backend(tmp_path):
    backend = build_recording_backend(
        settings=_settings(tmp_path),
        user_config=SimpleNamespace(role="supervisor", selected_monitor_fingerprints=[]),
        storage=_Storage(),
        all_monitors=[],
        clips_dir=tmp_path / "clips",
        raw_clips_dir=tmp_path / "raw",
        event_clips_dir=tmp_path / "clips_events",
    )
    assert isinstance(backend, RecordingBackend)
    assert backend.records is False
    assert backend.recording_service is None
    assert backend.build_worker_for is None
    assert backend.workers == []


def test_unconfigured_role_gets_empty_backend(tmp_path):
    backend = build_recording_backend(
        settings=_settings(tmp_path),
        user_config=SimpleNamespace(role="", selected_monitor_fingerprints=[]),
        storage=_Storage(),
        all_monitors=[],
        clips_dir=tmp_path / "clips",
        raw_clips_dir=tmp_path / "raw",
        event_clips_dir=tmp_path / "clips_events",
    )
    assert backend.records is False
    assert backend.event_store is None


@pytest.fixture
def _stop_telemetry_after():
    """build_recording_backend() starts the process-telemetry singleton —
    stop its background thread after the test so it doesn't leak across the
    suite (mirrors the module's own documented start()/stop() contract)."""
    yield
    get_telemetry().stop()


def _operator_monitor() -> MonitorInfo:
    return MonitorInfo(
        name="\\\\.\\DISPLAY1", width=1920, height=1080, x=0, y=0, is_primary=True, index=0
    )


def test_operator_role_builds_full_recording_backend(tmp_path, _stop_telemetry_after):
    monitor = _operator_monitor()
    backend = build_recording_backend(
        settings=_recording_settings(tmp_path),
        user_config=SimpleNamespace(role="operator", selected_monitor_fingerprints=[]),
        storage=FilesystemStorageAdapter(),
        all_monitors=[monitor],
        clips_dir=tmp_path / "clips",
        raw_clips_dir=tmp_path / "raw",
        event_clips_dir=tmp_path / "clips_events",
    )

    assert backend.records is True
    assert backend.recording_service is not None
    assert backend.recording_service.selected_monitors == [monitor]

    # One worker per monitor, each wired with its own per-monitor HourlyRecordingBuilder.
    assert len(backend.workers) == 1
    assert backend.workers[0].monitor == monitor
    assert 0 in backend.per_monitor_builders

    # Combined + per-monitor clip builders, event pipeline, and analytics all wired.
    assert backend.combined_builder is not None
    assert backend.clip_builder is not None
    assert backend.event_store is not None
    assert backend.event_service is not None
    assert backend.disk_monitor is not None
    assert backend.health_service is not None
    assert backend.auto_event_service is not None
    assert backend.batch_analyzer is not None
    assert backend.live_service is not None
    assert backend.analytics is not None

    # Hot-plug factory is wired and produces another worker for a new monitor.
    assert backend.build_worker_for is not None
    monitor2 = MonitorInfo(
        name="\\\\.\\DISPLAY2", width=1920, height=1080, x=1920, y=0, index=1
    )
    worker2 = backend.build_worker_for(monitor2)
    assert worker2.monitor == monitor2
    assert 1 in backend.per_monitor_builders


def test_operator_role_falls_back_to_primary_monitor_when_no_saved_selection(
    tmp_path, _stop_telemetry_after
):
    primary = _operator_monitor()
    backend = build_recording_backend(
        settings=_recording_settings(tmp_path),
        user_config=SimpleNamespace(role="operator", selected_monitor_fingerprints=[]),
        storage=FilesystemStorageAdapter(),
        all_monitors=[primary],
        clips_dir=tmp_path / "clips",
        raw_clips_dir=tmp_path / "raw",
        event_clips_dir=tmp_path / "clips_events",
    )
    assert backend.recording_service.selected_monitors == [primary]
