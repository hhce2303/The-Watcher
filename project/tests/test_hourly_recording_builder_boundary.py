"""
Mandatory wall-clock boundary enforcement for RecordingClipBuilder.

Bug report: a raw segment straddling an hour boundary (e.g. started 16:59:33,
finalized 17:04:33 with SEGMENT_DURATION=300) used to be counted whole into
whichever window it started in, producing a short/long clip that bled past
the hour instead of cutting exactly on it. These tests cover the fix: such a
segment's CONTENT is split across both windows via FFmpeg concat-demuxer
inpoint/outpoint directives (on_segment_finalized and recover_from_segments).
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.adapters.ffmpeg.hourly_recording_builder import RecordingClipBuilder
from app.core.recording_service.models import Segment


def _completed(returncode: int, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["ffmpeg"], returncode, None, stderr)


def _concat_recording_fake_run(calls: list[str]):
    """Fake run_batched_ffmpeg that records the concat file's content and
    writes a fake output file, so builds "succeed" without real FFmpeg."""

    def fake_run(cmd, *, label, timeout, on_started=None, on_finished=None):
        concat_path = Path(cmd[cmd.index("-i") + 1])
        calls.append(concat_path.read_text(encoding="utf-8"))
        Path(cmd[-1]).write_bytes(b"clip output")
        return _completed(0)

    return fake_run


class TestStraddlingSegmentLive:
    def test_segment_straddling_hour_is_split_into_two_clips(self, tmp_path):
        out_dir = tmp_path / "clips"
        out_dir.mkdir()
        builder = RecordingClipBuilder(output_dir=out_dir, monitor_index=0, window_minutes=60)

        seg_path = tmp_path / "seg1.ts"
        seg_path.write_bytes(b"fake-ts")
        started = datetime(2026, 7, 12, 16, 59, 33, tzinfo=timezone.utc)
        ended = datetime(2026, 7, 12, 17, 4, 33, tzinfo=timezone.utc)
        seg = Segment(path=seg_path, started_at=started, ended_at=ended, finalized=True)

        calls: list[str] = []
        with patch(
            "app.adapters.ffmpeg.hourly_recording_builder.run_batched_ffmpeg",
            side_effect=_concat_recording_fake_run(calls),
        ):
            builder.on_segment_finalized(seg, monitor_index=0)
            builder._executor.shutdown(wait=True)

        closing_output = out_dir / "2026-07-12_16-59-33_m0.mp4"
        new_output = out_dir / "2026-07-12_17-00-00_m0.mp4"
        assert closing_output.exists(), "closing window's clip must exist"
        assert new_output.exists(), "new window's clip must start exactly at the boundary"
        assert len(calls) == 2

        # Closing build: only the tail is cut off (outpoint), no inpoint.
        assert "outpoint 27.000" in calls[0]
        assert "inpoint" not in calls[0]
        # New build: only the head is cut off (inpoint), no outpoint.
        assert "inpoint 27.000" in calls[1]
        assert "outpoint" not in calls[1]

    def test_next_normal_segment_keeps_front_trim_on_rebuild(self, tmp_path):
        """After the straddle-split, a normal follow-up segment (fully inside
        the new hour) must trigger a rebuild of the new window that STILL
        trims the carried-over segment's front — the trim isn't a one-off."""
        out_dir = tmp_path / "clips"
        out_dir.mkdir()
        builder = RecordingClipBuilder(output_dir=out_dir, monitor_index=0, window_minutes=60)

        seg1_path = tmp_path / "seg1.ts"
        seg1_path.write_bytes(b"fake-ts-1")
        seg1 = Segment(
            path=seg1_path,
            started_at=datetime(2026, 7, 12, 16, 59, 33, tzinfo=timezone.utc),
            ended_at=datetime(2026, 7, 12, 17, 4, 33, tzinfo=timezone.utc),
            finalized=True,
        )
        seg2_path = tmp_path / "seg2.ts"
        seg2_path.write_bytes(b"fake-ts-2")
        seg2 = Segment(
            path=seg2_path,
            started_at=datetime(2026, 7, 12, 17, 4, 33, tzinfo=timezone.utc),
            ended_at=datetime(2026, 7, 12, 17, 9, 33, tzinfo=timezone.utc),
            finalized=True,
        )

        calls: list[str] = []
        with patch(
            "app.adapters.ffmpeg.hourly_recording_builder.run_batched_ffmpeg",
            side_effect=_concat_recording_fake_run(calls),
        ):
            builder.on_segment_finalized(seg1, monitor_index=0)
            builder._executor.shutdown(wait=True)
            # Re-open a fresh executor to submit the follow-up build (shutdown
            # above only exists to drain the straddle-split's two builds).
            builder._init_ffmpeg_executor(thread_name_prefix="clip-m0-2", log_label="[clip m0]")
            builder.on_segment_finalized(seg2, monitor_index=0)
            builder._executor.shutdown(wait=True)

        assert len(calls) == 3
        rebuild = calls[2]
        assert "seg1.ts" in rebuild and "seg2.ts" in rebuild
        assert "inpoint 27.000" in rebuild  # seg1 still trimmed on every rebuild
        # seg2 starts exactly at the new window's real_start — no trim for it.
        seg2_line_idx = rebuild.index("seg2.ts")
        tail = rebuild[seg2_line_idx:]
        assert "inpoint" not in tail and "outpoint" not in tail


class TestStraddlingSegmentRecovery:
    def test_recovery_splits_a_historical_straddling_segment(self, tmp_path):
        out_dir = tmp_path / "clips"
        out_dir.mkdir()
        builder = RecordingClipBuilder(output_dir=out_dir, monitor_index=0, window_minutes=60)

        seg_path = tmp_path / "seg1.ts"
        seg_path.write_bytes(b"fake-ts")
        seg = Segment(
            path=seg_path,
            started_at=datetime(2026, 7, 12, 16, 59, 33, tzinfo=timezone.utc),
            ended_at=datetime(2026, 7, 12, 17, 4, 33, tzinfo=timezone.utc),
            finalized=True,
        )

        calls: list[str] = []
        with patch(
            "app.adapters.ffmpeg.hourly_recording_builder.run_batched_ffmpeg",
            side_effect=_concat_recording_fake_run(calls),
        ):
            builder.recover_from_segments([seg])
            builder._executor.shutdown(wait=True)

        closing_output = out_dir / "2026-07-12_16-59-33_m0.mp4"
        new_output = out_dir / "2026-07-12_17-00-00_m0.mp4"
        assert closing_output.exists()
        assert new_output.exists()
        assert len(calls) == 2
        assert "outpoint 27.000" in calls[0] and "inpoint" not in calls[0]
        assert "inpoint 27.000" in calls[1] and "outpoint" not in calls[1]


class TestNonStraddlingSegmentUnchanged:
    def test_segment_within_one_window_gets_no_trim_directives(self, tmp_path):
        """Regression guard: the common case (no straddle) must keep the
        exact previous behaviour — a single clip, no inpoint/outpoint lines."""
        out_dir = tmp_path / "clips"
        out_dir.mkdir()
        builder = RecordingClipBuilder(output_dir=out_dir, monitor_index=0, window_minutes=60)

        seg_path = tmp_path / "seg1.ts"
        seg_path.write_bytes(b"fake-ts")
        seg = Segment(
            path=seg_path,
            started_at=datetime(2026, 7, 12, 16, 10, 0, tzinfo=timezone.utc),
            ended_at=datetime(2026, 7, 12, 16, 15, 0, tzinfo=timezone.utc),
            finalized=True,
        )

        calls: list[str] = []
        with patch(
            "app.adapters.ffmpeg.hourly_recording_builder.run_batched_ffmpeg",
            side_effect=_concat_recording_fake_run(calls),
        ):
            builder.on_segment_finalized(seg, monitor_index=0)
            builder._executor.shutdown(wait=True)

        output = out_dir / "2026-07-12_16-10-00_m0.mp4"
        assert output.exists()
        assert len(calls) == 1
        assert "inpoint" not in calls[0] and "outpoint" not in calls[0]
