"""
Unit tests — Milestone 2: get_segments_between time-range query.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.recording_service.buffer_manager import BufferManager
from app.core.recording_service.models import Segment
from app.core.recording_service.segment_index import SegmentIndex

BASE = datetime(2026, 4, 27, 10, 0, 0, tzinfo=timezone.utc)


def make_segment(offset_s: int, duration_s: int = 10) -> Segment:
    return Segment(
        path=Path(f"seg_{offset_s:04d}.mp4"),
        started_at=BASE + timedelta(seconds=offset_s),
        ended_at=BASE + timedelta(seconds=offset_s + duration_s),
    )


def make_buffer() -> tuple[BufferManager, SegmentIndex]:
    storage = MagicMock()
    storage.delete_segment = MagicMock()
    bm = BufferManager(storage=storage, retention_count=8)
    # Seed 12 segments: 0..110s in 10s steps
    for i in range(12):
        bm._index.add(make_segment(i * 10))
    return bm, bm._index


class TestGetSegmentsBetween:
    def test_exact_overlap(self) -> None:
        bm, _ = make_buffer()
        result = bm.get_segments_between(
            BASE + timedelta(seconds=15),
            BASE + timedelta(seconds=35),
        )
        # Segments 10–20, 20–30, 30–40 overlap the window [15, 35]
        assert len(result) == 3
        assert result[0].started_at == BASE + timedelta(seconds=10)
        assert result[-1].started_at == BASE + timedelta(seconds=30)

    def test_window_covers_entire_buffer(self) -> None:
        bm, idx = make_buffer()
        result = bm.get_segments_between(
            BASE - timedelta(seconds=1),
            BASE + timedelta(seconds=200),
        )
        assert len(result) == 12

    def test_window_before_buffer_returns_empty(self) -> None:
        bm, _ = make_buffer()
        result = bm.get_segments_between(
            BASE - timedelta(seconds=60),
            BASE - timedelta(seconds=1),
        )
        assert result == []

    def test_window_after_buffer_returns_empty(self) -> None:
        bm, _ = make_buffer()
        result = bm.get_segments_between(
            BASE + timedelta(seconds=200),
            BASE + timedelta(seconds=300),
        )
        assert result == []

    def test_single_segment_exact_boundaries(self) -> None:
        bm, _ = make_buffer()
        # Window exactly [0, 10] — overlaps the first segment [0, 10]
        result = bm.get_segments_between(BASE, BASE + timedelta(seconds=10))
        # Overlap: started_at(0) < end(10) AND ended_at(10) > start(0) → True
        assert len(result) >= 1
        assert result[0].started_at == BASE

    def test_order_is_chronological(self) -> None:
        bm, _ = make_buffer()
        result = bm.get_segments_between(BASE, BASE + timedelta(seconds=50))
        starts = [s.started_at for s in result]
        assert starts == sorted(starts)
