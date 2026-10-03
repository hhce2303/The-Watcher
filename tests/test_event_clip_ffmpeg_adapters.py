"""
Regression tests for FFmpegTrimAdapter / FFmpegTimestampAdapter now that they
run their FFmpeg calls through app.adapters.ffmpeg.process_guard.run_batched_ffmpeg()
instead of a plain subprocess.run(). Neither adapter had any test coverage
before this change.

This closes the concurrency gap that caused event-clip builds (manual or
auto-detected) to spawn unbounded concurrent FFmpeg processes: every other
offline FFmpeg pipeline in the repo (combined/hourly/mp4-converter/batch
analyzer) already serializes through the same batch_slot() semaphore.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from app.adapters.ffmpeg.timestamp_adapter import FFmpegTimestampAdapter
from app.adapters.ffmpeg.trim_adapter import FFmpegTrimAdapter
from app.core.recording_service.models import MonitorInfo, Segment


def _completed(returncode: int, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["ffmpeg"], returncode, None, stderr)


def _monitor(index: int = 0) -> MonitorInfo:
    return MonitorInfo(name="DISPLAY1", width=1920, height=1080, x=0, y=0, index=index)


def _segment(tmp_path: Path, name: str) -> Segment:
    seg_path = tmp_path / name
    seg_path.write_bytes(b"fake-ts")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return Segment(path=seg_path, started_at=now, ended_at=now + timedelta(seconds=5), finalized=True)


class TestFFmpegTrimAdapterUsesRunBatchedFfmpeg:
    def test_build_clip_success_writes_output_via_run_batched_ffmpeg(self, tmp_path):
        seg = _segment(tmp_path, "seg1.ts")
        output = tmp_path / "clip.mp4"
        adapter = FFmpegTrimAdapter()

        def fake_run(cmd, *, label, timeout):
            assert label == "clip-build"
            Path(cmd[-1]).write_bytes(b"clip bytes")
            return _completed(0)

        with patch(
            "app.adapters.ffmpeg.trim_adapter.run_batched_ffmpeg", side_effect=fake_run
        ):
            result = adapter.build_clip({_monitor(): [seg]}, output)

        assert result == output
        assert output.read_bytes() == b"clip bytes"

    def test_build_clip_failure_raises_and_removes_empty_output(self, tmp_path):
        seg = _segment(tmp_path, "seg1.ts")
        output = tmp_path / "clip.mp4"
        output.write_bytes(b"")  # FFmpeg left an empty file behind
        adapter = FFmpegTrimAdapter()

        def fake_run(cmd, *, label, timeout):
            return _completed(1, b"ffmpeg exploded")

        with patch(
            "app.adapters.ffmpeg.trim_adapter.run_batched_ffmpeg", side_effect=fake_run
        ):
            with pytest.raises(RuntimeError, match="return code 1"):
                adapter.build_clip({_monitor(): [seg]}, output)

        assert not output.exists()


class TestFFmpegTimestampAdapterUsesRunBatchedFfmpeg:
    def test_burn_success_replaces_clip_with_overlaid_version(self, tmp_path):
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"original")
        adapter = FFmpegTimestampAdapter()

        def fake_run(cmd, *, label, timeout):
            assert label == "timestamp-burn"
            Path(cmd[-1]).write_bytes(b"overlaid")
            return _completed(0)

        with patch(
            "app.adapters.ffmpeg.timestamp_adapter.run_batched_ffmpeg",
            side_effect=fake_run,
        ), patch(
            "app.adapters.ffmpeg.timestamp_adapter._find_font",
            return_value="C:/Windows/Fonts/consola.ttf",
        ):
            result = adapter.burn(clip, datetime(2026, 1, 1, tzinfo=timezone.utc))

        assert result == clip
        assert clip.read_bytes() == b"overlaid"

    def test_burn_failure_keeps_original_clip(self, tmp_path):
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"original")
        adapter = FFmpegTimestampAdapter()

        def fake_run(cmd, *, label, timeout):
            return _completed(1, b"drawtext failed")

        with patch(
            "app.adapters.ffmpeg.timestamp_adapter.run_batched_ffmpeg",
            side_effect=fake_run,
        ), patch(
            "app.adapters.ffmpeg.timestamp_adapter._find_font",
            return_value="C:/Windows/Fonts/consola.ttf",
        ):
            result = adapter.burn(clip, datetime(2026, 1, 1, tzinfo=timezone.utc))

        assert result == clip
        assert clip.read_bytes() == b"original"
