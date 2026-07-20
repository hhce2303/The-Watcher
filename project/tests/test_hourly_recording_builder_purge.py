"""
Regression tests for stale ``*.tmp.mp4`` cleanup in RecordingClipBuilder.

Before this change, ``_purge_stale_temps()`` only ran once in ``__init__``.
If the whole app process (not just ffmpeg) crashed mid-``_build()``, the
orphaned tmp survived until the next full app restart. These tests cover the
new age-bounded sweep that also runs opportunistically at the top of every
``_build()`` call.
"""
from __future__ import annotations

import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.adapters.ffmpeg.hourly_recording_builder import RecordingClipBuilder
from app.core.recording_service.models import Segment


def _completed(returncode: int, stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["ffmpeg"], returncode, None, stderr)


def _age_file(path: Path, age_seconds: float) -> None:
    old = time.time() - age_seconds
    os.utime(path, (old, old))


class TestPurgeStaleTemps:
    def test_unconditional_purge_removes_everything(self, tmp_path):
        out_dir = tmp_path / "clips"
        out_dir.mkdir()
        stale = out_dir / "2026-01-01_00-00-00_m0.tmp.mp4"
        stale.write_bytes(b"")

        builder = RecordingClipBuilder(output_dir=out_dir, monitor_index=0)
        builder._purge_stale_temps()

        assert not stale.exists()

    def test_max_age_only_removes_files_older_than_threshold(self, tmp_path):
        out_dir = tmp_path / "clips"
        out_dir.mkdir()
        builder = RecordingClipBuilder(output_dir=out_dir, monitor_index=0)

        old_tmp = out_dir / "2026-01-01_00-00-00_m0.tmp.mp4"
        old_tmp.write_bytes(b"")
        _age_file(old_tmp, age_seconds=3 * 3600)

        recent_tmp = out_dir / "2026-01-01_01-00-00_m0.tmp.mp4"
        recent_tmp.write_bytes(b"")

        builder._purge_stale_temps(max_age_seconds=2 * 3600)

        assert not old_tmp.exists()
        assert recent_tmp.exists()

    def test_max_age_skips_excluded_path_even_if_old(self, tmp_path):
        out_dir = tmp_path / "clips"
        out_dir.mkdir()
        builder = RecordingClipBuilder(output_dir=out_dir, monitor_index=0)

        active_tmp = out_dir / "2026-01-01_00-00-00_m0.tmp.mp4"
        active_tmp.write_bytes(b"")
        _age_file(active_tmp, age_seconds=3 * 3600)

        builder._purge_stale_temps(max_age_seconds=2 * 3600, exclude=active_tmp)

        assert active_tmp.exists()

    def test_purge_never_touches_another_monitors_tmp(self, tmp_path):
        # Regression test: all monitors share output_dir (backend.py wires the
        # same raw_clips_dir into every HourlyRecordingBuilder), and a builder
        # is constructed live on hot-plug, not only at cold startup — an
        # unscoped glob here would delete another monitor's in-flight build.
        out_dir = tmp_path / "clips"
        out_dir.mkdir()
        other_monitor_tmp = out_dir / "2026-01-01_00-00-00_m1.tmp.mp4"
        other_monitor_tmp.write_bytes(b"")

        # Constructing monitor 0's builder must not purge monitor 1's tmp,
        # even via the unconditional (max_age_seconds=None) startup path.
        RecordingClipBuilder(output_dir=out_dir, monitor_index=0)

        assert other_monitor_tmp.exists()


class TestOpportunisticPurgeDuringBuild:
    def test_build_sweeps_orphaned_tmp_from_a_prior_crash(self, tmp_path):
        out_dir = tmp_path / "clips"
        out_dir.mkdir()
        builder = RecordingClipBuilder(output_dir=out_dir, monitor_index=0)

        # Simulate a tmp left behind by a whole-app crash mid-_build(), for a
        # *different* window than the one we're about to build.
        orphan = out_dir / "2026-01-01_00-00-00_m0.tmp.mp4"
        orphan.write_bytes(b"")
        _age_file(orphan, age_seconds=3 * 3600)

        seg_path = tmp_path / "seg1.ts"
        seg_path.write_bytes(b"fake-ts")
        now = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
        seg = Segment(path=seg_path, started_at=now, ended_at=now, finalized=True)
        output = out_dir / "2026-01-01_01-00-00_m0.mp4"

        def fake_run(cmd, *, label, timeout, on_started=None, on_finished=None):
            Path(cmd[-1]).write_bytes(b"clip output")
            return _completed(0)

        with patch(
            "app.adapters.ffmpeg.hourly_recording_builder.run_batched_ffmpeg",
            side_effect=fake_run,
        ):
            builder._build(
                [seg], output, raw_size_bytes=len(b"fake-ts"),
                window_key="2026-01-01_01-00-00", real_start=now,
            )

        assert not orphan.exists()
        assert output.exists()
