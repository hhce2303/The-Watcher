"""
Unit tests — ClipBuilder segment selection, EventContext snapshot, output path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.recording_service.clip_builder import ClipBuilder
from app.core.recording_service.models import EventContext, MonitorInfo, Segment

BASE = datetime(2026, 4, 27, 13, 22, 10, tzinfo=timezone.utc)


def make_segment(offset_s: int, duration_s: int = 10) -> Segment:
    return Segment(
        path=Path(f"seg_{offset_s:04d}.mp4"),
        started_at=BASE - timedelta(seconds=120) + timedelta(seconds=offset_s),
        ended_at=BASE - timedelta(seconds=120) + timedelta(seconds=offset_s + duration_s),
        finalized=True,
    )


def make_monitor(index: int = 0) -> MonitorInfo:
    return MonitorInfo(
        name=f"DISPLAY{index}",
        width=1920,
        height=1080,
        x=index * 1920,
        y=0,
        is_primary=(index == 0),
        index=index,
    )


def _make_builder(
    segments: list[Segment],
    clips_dir: Path,
    monitor: MonitorInfo | None = None,
) -> tuple[ClipBuilder, MagicMock]:
    if monitor is None:
        monitor = make_monitor(0)

    # Mock worker — buffer reports its window segments and that the post-window
    # is already finalized so the bounded await short-circuits immediately.
    worker = MagicMock()
    worker.buffer.get_segments_between.return_value = segments
    worker.buffer.has_finalized_through.return_value = True

    # Mock recording_service
    recording_service = MagicMock()
    recording_service.selected_monitors = [monitor]
    recording_service.get_worker.return_value = worker

    clip_adapter = MagicMock()
    clip_adapter.build_clip.side_effect = lambda mon_segs, out, start, end: out

    builder = ClipBuilder(
        recording_service=recording_service,
        clip_adapter=clip_adapter,
        clips_dir=clips_dir,
        pre_seconds=120,
        post_seconds=120,
        post_window_timeout_seconds=0,  # no real waiting in unit tests
    )
    return builder, clip_adapter


class TestClipBuilder:
    def test_output_path_naming(self, tmp_path: Path) -> None:
        segs = [make_segment(i * 10) for i in range(24)]
        builder, _ = _make_builder(segs, tmp_path)
        result = builder.build(builder.snapshot_event(BASE))
        assert result is not None
        assert result.name == "2026-04-27_13-22-10_event.mp4"
        assert result.parent == tmp_path

    def test_calls_adapter_with_correct_segments(self, tmp_path: Path) -> None:
        monitor = make_monitor(0)
        segs = [make_segment(i * 10) for i in range(24)]
        builder, adapter = _make_builder(segs, tmp_path, monitor=monitor)
        builder.build(builder.snapshot_event(BASE))
        adapter.build_clip.assert_called_once()
        mon_segs = adapter.build_clip.call_args.args[0]
        # Should receive {monitor: segs}
        assert list(mon_segs.values())[0] == segs

    def test_returns_none_when_no_segments(self, tmp_path: Path) -> None:
        builder, adapter = _make_builder([], tmp_path)
        result = builder.build(builder.snapshot_event(BASE))
        assert result is None
        adapter.build_clip.assert_not_called()

    def test_returns_none_when_no_monitors_selected(self, tmp_path: Path) -> None:
        recording_service = MagicMock()
        recording_service.selected_monitors = []
        clip_adapter = MagicMock()
        builder = ClipBuilder(
            recording_service=recording_service,
            clip_adapter=clip_adapter,
            clips_dir=tmp_path,
            post_window_timeout_seconds=0,
        )
        result = builder.build(builder.snapshot_event(BASE))
        assert result is None
        clip_adapter.build_clip.assert_not_called()

    def test_clips_dir_is_created(self, tmp_path: Path) -> None:
        clips_dir = tmp_path / "subdir" / "clips"
        segs = [make_segment(0)]
        builder, _ = _make_builder(segs, clips_dir)
        builder.build(builder.snapshot_event(BASE))
        assert clips_dir.exists()

    def test_worker_queried_with_correct_window(self, tmp_path: Path) -> None:
        monitor = make_monitor(0)
        worker = MagicMock()
        worker.buffer.get_segments_between.return_value = [make_segment(0)]
        worker.buffer.has_finalized_through.return_value = True

        recording_service = MagicMock()
        recording_service.selected_monitors = [monitor]
        recording_service.get_worker.return_value = worker

        clip_adapter = MagicMock()
        clip_adapter.build_clip.side_effect = lambda mon_segs, out, start, end: out

        builder = ClipBuilder(
            recording_service=recording_service,
            clip_adapter=clip_adapter,
            clips_dir=tmp_path,
            pre_seconds=120,
            post_seconds=120,
            post_window_timeout_seconds=0,
        )
        builder.build(builder.snapshot_event(BASE))

        expected_start = BASE - timedelta(seconds=120)
        expected_end = BASE + timedelta(seconds=120)
        worker.buffer.get_segments_between.assert_called_once_with(
            expected_start, expected_end
        )

    def test_snapshot_freezes_selection_at_trigger_time(self, tmp_path: Path) -> None:
        """A clip built from a snapshot ignores later selection changes."""
        monitor = make_monitor(0)
        segs = [make_segment(i * 10) for i in range(24)]
        builder, adapter = _make_builder(segs, tmp_path, monitor=monitor)

        ctx = builder.snapshot_event(BASE)
        assert ctx.monitors == (monitor,)
        assert ctx.event_id == BASE.strftime("%H%M%S")

        # User changes the live selection AFTER the snapshot was taken.
        builder._service.selected_monitors = []

        # Build still uses the snapshotted monitor, not the now-empty selection.
        result = builder.build(ctx)
        assert result is not None
        adapter.build_clip.assert_called_once()
