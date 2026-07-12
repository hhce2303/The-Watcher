"""
Regression tests for the migration of CombinedClipBuilder / RecordingClipBuilder
(hourly_recording_builder.py) from an inline batch_slot()+Popen block to the
shared app.adapters.ffmpeg.process_guard.run_batched_ffmpeg() helper.

Neither builder had any test coverage before this migration. These tests only
cover what changed: that _active_proc is still set/cleared around the FFmpeg
call (used by shutdown() to kill an in-flight encode), and that the
success/failure handling still works against a CompletedProcess-shaped result
instead of a raw Popen.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.adapters.ffmpeg.combined_clip_builder import CombinedClipBuilder
from app.adapters.ffmpeg.hourly_recording_builder import RecordingClipBuilder
from app.core.recording_service.models import Segment


def _completed(returncode: int, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["ffmpeg"], returncode, None, stderr)


class TestCombinedClipBuilderMigration:
    def _make_builder(self, tmp_path) -> tuple[CombinedClipBuilder, Path]:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        out_dir = tmp_path / "clips"
        clip = raw_dir / "2026-01-01_00-00-00_m0.mp4"
        clip.write_bytes(b"fake")
        builder = CombinedClipBuilder(raw_dir=raw_dir, output_dir=out_dir, monitor_count=1)
        return builder, clip

    def test_active_proc_set_during_call_and_cleared_after(self, tmp_path):
        builder, clip = self._make_builder(tmp_path)
        seen = {}

        def fake_run(cmd, *, label, timeout, on_started=None, on_finished=None):
            proc = MagicMock(pid=1234)
            on_started(proc)
            with builder._proc_lock:
                seen["active_during_call"] = builder._active_proc
            on_finished()
            return _completed(1, b"boom")

        with patch(
            "app.adapters.ffmpeg.combined_clip_builder.run_batched_ffmpeg",
            side_effect=fake_run,
        ):
            builder._build(
                [clip], tmp_path / "clips" / "out.mp4", "2026-01-01_00-00-00",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

        assert seen["active_during_call"] is not None
        assert builder._active_proc is None

    def test_nonzero_returncode_discards_submission_for_retry(self, tmp_path):
        builder, clip = self._make_builder(tmp_path)
        output = tmp_path / "clips" / "out.mp4"
        builder._submitted.add("2026-01-01_00-00-00")

        def fake_run(cmd, *, label, timeout, on_started=None, on_finished=None):
            return _completed(1, b"encode failed")

        with patch(
            "app.adapters.ffmpeg.combined_clip_builder.run_batched_ffmpeg",
            side_effect=fake_run,
        ):
            builder._build(
                [clip], output, "2026-01-01_00-00-00",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

        assert not output.exists()
        assert "2026-01-01_00-00-00" not in builder._submitted

    def test_success_replaces_tmp_with_output(self, tmp_path):
        builder, clip = self._make_builder(tmp_path)
        output = tmp_path / "clips" / "out.mp4"

        def fake_run(cmd, *, label, timeout, on_started=None, on_finished=None):
            # cmd's last argument is the tmp output path (see cmd construction).
            Path(cmd[-1]).write_bytes(b"combined output")
            return _completed(0)

        with patch(
            "app.adapters.ffmpeg.combined_clip_builder.run_batched_ffmpeg",
            side_effect=fake_run,
        ):
            builder._build(
                [clip], output, "2026-01-01_00-00-00",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            )

        assert output.exists()
        assert output.read_bytes() == b"combined output"


class TestRecordingClipBuilderMigration:
    def _make_segment(self, tmp_path, name: str) -> Segment:
        seg_path = tmp_path / name
        seg_path.write_bytes(b"fake-ts")
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        return Segment(path=seg_path, started_at=now, ended_at=now, finalized=True)

    def test_active_proc_set_during_call_and_cleared_after(self, tmp_path):
        output_dir = tmp_path / "clips"
        builder = RecordingClipBuilder(output_dir=output_dir, monitor_index=0)
        seg = self._make_segment(tmp_path, "seg1.ts")
        seen = {}

        def fake_run(cmd, *, label, timeout, on_started=None, on_finished=None):
            proc = MagicMock(pid=5678)
            on_started(proc)
            with builder._proc_lock:
                seen["active_during_call"] = builder._active_proc
            on_finished()
            return _completed(1, b"boom")

        with patch(
            "app.adapters.ffmpeg.hourly_recording_builder.run_batched_ffmpeg",
            side_effect=fake_run,
        ):
            builder._build(
                [seg], output_dir / "out_m0.mp4", raw_size_bytes=len(b"fake-ts"),
                window_key="2026-01-01_00-00-00", real_start=seg.started_at,
            )

        assert seen["active_during_call"] is not None
        assert builder._active_proc is None

    def test_success_replaces_tmp_with_output_and_fires_callback(self, tmp_path):
        output_dir = tmp_path / "clips"
        ready: list[Path] = []

        def _capture(path: Path, window_key: str, real_start: datetime) -> None:
            ready.append(path)

        builder = RecordingClipBuilder(
            output_dir=output_dir, monitor_index=0, on_clip_ready=_capture
        )
        seg = self._make_segment(tmp_path, "seg1.ts")
        output = output_dir / "out_m0.mp4"

        def fake_run(cmd, *, label, timeout, on_started=None, on_finished=None):
            Path(cmd[-1]).write_bytes(b"clip output")
            return _completed(0)

        with patch(
            "app.adapters.ffmpeg.hourly_recording_builder.run_batched_ffmpeg",
            side_effect=fake_run,
        ):
            builder._build(
                [seg], output, raw_size_bytes=len(b"fake-ts"),
                window_key="2026-01-01_00-00-00", real_start=seg.started_at,
            )

        assert output.exists()
        assert ready == [output]
