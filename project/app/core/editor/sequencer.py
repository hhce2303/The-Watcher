"""Timeline ↔ source position mapping for the evidence reel (R-1).

The reel concatenates each clip's trimmed range end-to-end.  A *global* position
runs ``0 .. total_duration_s`` across the whole reel; a *local* position is a
time within a specific source file (``in_point_s .. out_point_s``).

The QML player owns one ``MediaPlayer``; the sequencer tells it which clip to
load and where to seek as the playhead crosses clip boundaries.  Pure math —
no Qt — so it is fully unit-tested.
"""
from __future__ import annotations

from typing import Optional, Tuple

from app.core.editor.models import EditTimeline


class TimelineSequencer:
    """Maps reel-global seconds to ``(clip_index, local_seconds_in_source)``."""

    def __init__(self, timeline: EditTimeline) -> None:
        self._t = timeline

    def clip_start_global(self, index: int) -> float:
        """Global start time of the clip at *index* (sum of prior trimmed durations)."""
        if not (0 <= index < len(self._t.clips)):
            raise IndexError(index)
        return sum(self._t.clips[i].trimmed_duration_s for i in range(index))

    def locate(self, global_pos_s: float) -> Optional[Tuple[int, float]]:
        """Return ``(clip_index, local_pos_s)`` for a reel-global position.

        ``local_pos_s`` is the absolute time within that clip's source file
        (i.e. ``in_point_s`` ≤ value ≤ ``out_point_s``).  Returns ``None`` if the
        reel has no playable content.  Clips of zero trimmed duration are
        skipped.  The position is clamped into ``[0, total_duration_s]``.
        """
        total = self._t.total_duration_s
        if total <= 0:
            return None

        g = min(max(0.0, float(global_pos_s)), total)
        cum = 0.0
        last_playable: Optional[Tuple[int, float]] = None
        for i, clip in enumerate(self._t.clips):
            dur = clip.trimmed_duration_s
            if dur <= 0:
                continue
            last_playable = (i, clip.out_point_s)
            if g < cum + dur:
                return (i, clip.in_point_s + (g - cum))
            cum += dur
        # g == total → end of the last playable clip.
        return last_playable

    def global_of(self, index: int, local_pos_s: float) -> float:
        """Inverse of :meth:`locate`: reel-global time for a source-local position.

        *local_pos_s* is clamped into the clip's ``[in, out]`` window.
        """
        clip = self._t.clips[index]
        local = min(max(clip.in_point_s, float(local_pos_s)), clip.out_point_s)
        return self.clip_start_global(index) + (local - clip.in_point_s)

    def next_index(self, index: int) -> Optional[int]:
        """Index of the next clip with playable content after *index*, or None."""
        for i in range(index + 1, len(self._t.clips)):
            if self._t.clips[i].trimmed_duration_s > 0:
                return i
        return None
