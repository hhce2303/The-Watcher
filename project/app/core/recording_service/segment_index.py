from __future__ import annotations

import threading
from datetime import datetime
from typing import List

from app.core.recording_service.models import Segment


class SegmentIndex:
    """
    In-memory, time-ordered index of recorded segments.

    Milestone 2 core deliverable. Provides O(n) time-range queries
    sufficient for buffers containing several hours of 10-second segments.

    Thread-safe.
    """

    def __init__(self) -> None:
        self._segments: List[Segment] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def add(self, segment: Segment) -> None:
        """Insert a segment and keep the list ordered by start time."""
        with self._lock:
            self._segments.append(segment)
            self._segments.sort(key=lambda s: s.started_at)

    def remove(self, segment: Segment) -> None:
        """Remove a segment from the index (no-op if not found)."""
        with self._lock:
            try:
                self._segments.remove(segment)
            except ValueError:
                pass

    def upsert(self, segment: Segment) -> bool:
        """Add or replace a segment matched by path.

        Returns True if an existing entry was replaced, False if newly added.
        Used to update the estimated end-time of the live segment once the
        accurate end-time is known.
        """
        with self._lock:
            before = len(self._segments)
            self._segments = [s for s in self._segments if s.path != segment.path]
            self._segments.append(segment)
            self._segments.sort(key=lambda s: s.started_at)
            return len(self._segments) == before

    # ------------------------------------------------------------------
    # Queries (Milestone 2 API)
    # ------------------------------------------------------------------

    def get_segments_between(self, start: datetime, end: datetime) -> List[Segment]:
        """
        Return all segments whose time range overlaps [start, end].

        Overlap condition:
            segment.started_at < end  AND  segment.ended_at > start
        """
        with self._lock:
            return [
                s for s in self._segments
                if s.started_at < end and s.ended_at > start
            ]

    def all(self) -> List[Segment]:
        """Return a snapshot of all indexed segments."""
        with self._lock:
            return list(self._segments)

    def oldest(self) -> Segment | None:
        with self._lock:
            return self._segments[0] if self._segments else None

    def newest(self) -> Segment | None:
        with self._lock:
            return self._segments[-1] if self._segments else None

    def count(self) -> int:
        with self._lock:
            return len(self._segments)

    def total_duration_seconds(self) -> float:
        """Wall-clock span from the oldest segment start to the newest segment end."""
        with self._lock:
            if len(self._segments) < 2:
                return 0.0
            return (
                self._segments[-1].ended_at - self._segments[0].started_at
            ).total_seconds()
