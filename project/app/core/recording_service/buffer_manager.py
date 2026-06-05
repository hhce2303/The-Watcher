from __future__ import annotations

from datetime import datetime
from typing import Callable, List, Optional

from loguru import logger

from app.core.ports.storage_port import StoragePort
from app.core.recording_service.models import Segment
from app.core.recording_service.segment_index import SegmentIndex


class BufferManager:
    """
    Manages the continuous recording segment store.

    Responsibilities:
    - Accept new segments from the recorder adapter.
    - Enforce the retention policy: keep the last *retention_count* completed
      segments plus the one currently being written.  Older segments are
      deleted from disk to reclaim space.
    - Expose time-range queries for clip assembly.

    With 1-hour segments and retention_count=8 this keeps ~8 hours of
    recordings on disk, mirroring the behaviour expected from OBS-style
    continuous recording.
    """

    def __init__(
        self,
        storage: StoragePort,
        retention_count: int = 8,
        on_segment_finalized: Optional[Callable[[Segment], None]] = None,
    ) -> None:
        self._storage = storage
        self._retention_count = max(1, retention_count)
        self._index = SegmentIndex()
        self._on_segment_finalized = on_segment_finalized
        # Segments produced before this timestamp have different video dimensions
        # (monitor config changed) and must not be mixed into new clips.
        self._segment_floor: Optional[datetime] = None

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def register_segment(self, segment: Segment) -> None:
        """Called by the recorder adapter when a segment is ready or updated.

        Uses upsert semantics: if a segment for the same file path already exists
        (e.g. an in-progress segment with an estimated end-time), it is replaced
        in-place with the finalised version.
        """
        was_update = self._index.upsert(segment)
        if not was_update:
            logger.info(
                "Segment indexed: {} | duration={:.1f}s | total={:.0f}s | count={}",
                segment.path.name,
                segment.duration_seconds,
                self._index.total_duration_seconds(),
                self._index.count(),
            )
        else:
            logger.debug(
                "Segment finalised: {} | duration={:.1f}s",
                segment.path.name,
                segment.duration_seconds,
            )
            if self._on_segment_finalized is not None:
                self._on_segment_finalized(segment)
        self._enforce_retention()

    # ------------------------------------------------------------------
    # Monitor config change — dimension floor
    # ------------------------------------------------------------------

    def set_segment_floor(self, dt: datetime) -> None:
        """Discard segments that started before *dt* from future clip queries.

        Called by RecordingService whenever the monitor selection changes and
        the output video dimensions change.  Segments produced under the old
        config are incompatible with the new dimensions and would corrupt a
        clip assembled with ``-f concat -c copy``.
        """
        self._segment_floor = dt
        logger.info(
            "Segment floor set to {} — clips will only use segments after this time.",
            dt.isoformat(),
        )

    # ------------------------------------------------------------------
    # Milestone 2 — Time-range query API
    # ------------------------------------------------------------------

    def get_segments_between(self, start: datetime, end: datetime) -> List[Segment]:
        """Return all segments whose time range overlaps [start, end].

        Segments that started before the current segment_floor are excluded
        because they were produced with a different monitor configuration and
        have incompatible video dimensions.
        """
        segments = self._index.get_segments_between(start, end)
        if self._segment_floor is not None:
            floor = self._segment_floor
            before = len(segments)
            segments = [s for s in segments if s.started_at >= floor]
            dropped = before - len(segments)
            if dropped:
                logger.debug(
                    "Filtered {} segment(s) older than monitor-config floor ({}).",
                    dropped,
                    floor.isoformat(),
                )
        return segments

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def all_segments(self) -> List[Segment]:
        return self._index.all()

    def total_duration_seconds(self) -> float:
        return self._index.total_duration_seconds()

    def segment_count(self) -> int:
        return self._index.count()

    # ------------------------------------------------------------------
    # Retention enforcement (count-based policy)
    # ------------------------------------------------------------------

    def _enforce_retention(self) -> None:
        """Delete oldest segments beyond the retention limit.

        The segment most recently added to the index may still be open for
        writing by FFmpeg, so it is never touched.  Only completed (older)
        segments are candidates for deletion.

        With 1-hour segments and retention_count=8 this keeps at most 9 files
        on disk at any time (8 completed + 1 in-progress).
        """
        all_segs = self._index.all()  # oldest-first order from SegmentIndex
        if len(all_segs) <= 1:
            return

        # Treat the last segment as potentially in-progress; never delete it.
        completed = all_segs[:-1]
        excess = completed[:-self._retention_count] if self._retention_count > 0 else completed

        for segment in excess:
            self._storage.delete_segment(segment)
            self._index.remove(segment)
            logger.info(
                "Retention: removed old recording {} (keeping {} segments)",
                segment.path.name,
                self._retention_count,
            )
