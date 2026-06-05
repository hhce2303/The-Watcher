"""
Unit tests — Milestone 1: Segment model and SegmentIndex.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.recording_service.models import Segment
from app.core.recording_service.segment_index import SegmentIndex


# ── Helpers ──────────────────────────────────────────────────────────────────

BASE = datetime(2026, 4, 27, 10, 0, 0, tzinfo=timezone.utc)


def make_segment(offset_s: int, duration_s: int = 10) -> Segment:
    return Segment(
        path=Path(f"seg_{offset_s:04d}.mp4"),
        started_at=BASE + timedelta(seconds=offset_s),
        ended_at=BASE + timedelta(seconds=offset_s + duration_s),
    )


# ── Segment model ─────────────────────────────────────────────────────────────

class TestSegmentModel:
    def test_duration_seconds(self) -> None:
        seg = make_segment(0, 10)
        assert seg.duration_seconds == 10.0

    def test_size_bytes_missing_file(self) -> None:
        seg = make_segment(0)
        # Path does not exist on disk — should return 0 without raising.
        assert seg.size_bytes == 0

    def test_immutable_path(self) -> None:
        seg = make_segment(0)
        assert seg.path == Path("seg_0000.mp4")


# ── SegmentIndex ──────────────────────────────────────────────────────────────

class TestSegmentIndex:
    def test_add_and_count(self) -> None:
        idx = SegmentIndex()
        idx.add(make_segment(0))
        idx.add(make_segment(10))
        assert idx.count() == 2

    def test_order_preserved(self) -> None:
        idx = SegmentIndex()
        # Insert out-of-order
        idx.add(make_segment(20))
        idx.add(make_segment(0))
        idx.add(make_segment(10))
        times = [s.started_at for s in idx.all()]
        assert times == sorted(times)

    def test_remove(self) -> None:
        idx = SegmentIndex()
        seg = make_segment(0)
        idx.add(seg)
        idx.remove(seg)
        assert idx.count() == 0

    def test_remove_nonexistent_is_noop(self) -> None:
        idx = SegmentIndex()
        idx.remove(make_segment(99))  # must not raise

    def test_oldest_newest(self) -> None:
        idx = SegmentIndex()
        idx.add(make_segment(10))
        idx.add(make_segment(0))
        assert idx.oldest().started_at == BASE  # type: ignore[union-attr]
        assert idx.newest().started_at == BASE + timedelta(seconds=10)  # type: ignore[union-attr]

    def test_oldest_newest_empty(self) -> None:
        idx = SegmentIndex()
        assert idx.oldest() is None
        assert idx.newest() is None

    def test_total_duration_empty(self) -> None:
        assert SegmentIndex().total_duration_seconds() == 0.0

    def test_total_duration_single(self) -> None:
        idx = SegmentIndex()
        idx.add(make_segment(0))
        assert idx.total_duration_seconds() == 0.0  # needs ≥2 segments

    def test_total_duration_multiple(self) -> None:
        idx = SegmentIndex()
        for i in range(6):
            idx.add(make_segment(i * 10))
        # oldest.started_at=0, newest.ended_at=60 → span=60
        assert idx.total_duration_seconds() == 60.0
