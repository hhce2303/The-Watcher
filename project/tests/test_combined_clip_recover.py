"""Regression tests for CombinedClipBuilder.recover()'s "is this window still
in progress" decision.

Root cause covered: recover() used to exempt only the newest window key found
on disk (``if window_key >= newest: continue``) from combining, on the theory
that "the newest one might still be growing, the live path will combine it
once a later window appears". That assumption only holds while the SAME
process keeps recording. Any session shorter than window_minutes (the
IT/Supervisor sidecar topology, which dies with the app; a daemon restarted
before the hour rolls over) never produces a second window's clip in that
process, so its last window stays "the newest on disk" forever — and every
later recover() call (from a fresh process, after the gap) still measured
"newest" as the max of whatever happened to be on disk, not against the real
wall clock, so a window that is now days old and unambiguously finished could
still be skipped as "in progress" if nothing newer had ever been written.
Net effect: combined clips were never produced for any short-lived or
restart-heavy session — only a continuously-running process that itself
crossed an hour boundary ever combined anything.

The fix compares each window against the CURRENT wall-clock window bucket
instead of the max found on disk: a window is only exempt if it is the one
the wall clock is in right now (i.e. a live process could still be adding to
it). Anything older is combined immediately, regardless of whether a later
window exists.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.adapters.ffmpeg.combined_clip_builder import CombinedClipBuilder


def _make_builder(tmp_path: Path, **clips: bytes) -> tuple[CombinedClipBuilder, Path]:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    out_dir = tmp_path / "clips"
    for name in clips:
        (raw_dir / name).write_bytes(b"fake")
    builder = CombinedClipBuilder(
        raw_dir=raw_dir, output_dir=out_dir, monitor_count=1, window_minutes=60
    )
    return builder, out_dir


class TestRecoverInProgressGate:
    def test_single_old_window_with_no_successor_is_combined(self, tmp_path):
        """A session that never produced a second window's clip (e.g. the
        sidecar died, or the app was closed within the hour) must still get
        its lone, long-finished window combined — it must not wait forever
        for a successor that will never come.
        """
        builder, _ = _make_builder(
            tmp_path, **{"2026-01-01_08-00-05_m0.mp4": b"fake"}
        )
        queued = []
        with patch.object(builder, "_submit", side_effect=lambda *a: queued.append(a)):
            builder.recover(backfill_hours=None)

        assert len(queued) == 1
        assert queued[0][2] == "2026-01-01_08-00-00"

    def test_genuinely_live_current_window_is_still_exempt(self, tmp_path):
        """A window that IS the real wall-clock window right now must not be
        combined — a live process could still be appending segments to it.
        """
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%d_%H-%M-%S")
        builder, _ = _make_builder(tmp_path, **{f"{ts}_m0.mp4": b"fake"})

        queued = []
        with patch.object(builder, "_submit", side_effect=lambda *a: queued.append(a)):
            builder.recover(backfill_hours=None)

        assert queued == []

    def test_multiple_stale_windows_all_combine_on_one_recover(self, tmp_path):
        """Several past sessions, none of which ever overlapped a live
        successor in-process, must all catch up in a single recover() call.
        """
        builder, _ = _make_builder(
            tmp_path,
            **{
                "2026-01-01_08-00-05_m0.mp4": b"fake",
                "2026-01-01_11-00-05_m0.mp4": b"fake",
                "2026-01-01_13-00-05_m0.mp4": b"fake",
            },
        )
        queued = []
        with patch.object(builder, "_submit", side_effect=lambda *a: queued.append(a)):
            builder.recover(backfill_hours=None)

        assert {q[2] for q in queued} == {
            "2026-01-01_08-00-00",
            "2026-01-01_11-00-00",
            "2026-01-01_13-00-00",
        }

    def test_backfill_horizon_still_applies_to_ancient_windows(self, tmp_path):
        """The deliberate backfill_hours guard (avoid a CPU-heavy rebuild
        burst of the whole history) is untouched by this fix — an old window
        outside the horizon is still left alone, just no longer confused
        with "still recording".
        """
        stale = (datetime.now(timezone.utc) - timedelta(hours=999)).strftime(
            "%Y-%m-%d_%H-%M-%S"
        )
        builder, _ = _make_builder(tmp_path, **{f"{stale}_m0.mp4": b"fake"})

        queued = []
        with patch.object(builder, "_submit", side_effect=lambda *a: queued.append(a)):
            builder.recover(backfill_hours=8)

        assert queued == []
