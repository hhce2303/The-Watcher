"""
Unit tests — Fase 0 (R-1): reel ↔ source position mapping.
"""
from __future__ import annotations

from pathlib import Path

from app.core.editor.models import ClipEntry, EditTimeline
from app.core.editor.sequencer import TimelineSequencer


def _timeline(*specs: tuple[str, float, float, float]) -> EditTimeline:
    """specs: (name, source_duration, in_point, out_point)."""
    t = EditTimeline()
    for name, dur, in_s, out_s in specs:
        t.add(ClipEntry(Path(name), dur, in_s, out_s))
    return t


class TestLocate:
    def test_empty_returns_none(self) -> None:
        assert TimelineSequencer(EditTimeline()).locate(0) is None

    def test_all_zero_duration_returns_none(self) -> None:
        t = _timeline(("a.mp4", 10, 5, 5))
        assert TimelineSequencer(t).locate(0) is None

    def test_single_clip_start_mid_end(self) -> None:
        t = _timeline(("a.mp4", 10, 2, 8))  # trimmed 6s, source local 2..8
        seq = TimelineSequencer(t)
        assert seq.locate(0) == (0, 2.0)
        assert seq.locate(3) == (0, 5.0)
        assert seq.locate(6) == (0, 8.0)  # end → out_point

    def test_clamp_beyond_total(self) -> None:
        t = _timeline(("a.mp4", 10, 0, 4))
        seq = TimelineSequencer(t)
        assert seq.locate(999) == (0, 4.0)
        assert seq.locate(-5) == (0, 0.0)

    def test_multi_clip_boundaries(self) -> None:
        # clip0: 0..4 (4s), clip1: local 1..6 (5s) → reel total 9s
        t = _timeline(("a.mp4", 10, 0, 4), ("b.mp4", 10, 1, 6))
        seq = TimelineSequencer(t)
        assert seq.locate(0) == (0, 0.0)
        assert seq.locate(3.5) == (0, 3.5)
        # at reel-global 4.0 we cross into clip1 at its in_point (1.0)
        assert seq.locate(4.0) == (1, 1.0)
        assert seq.locate(6.0) == (1, 3.0)   # 2s into clip1 → local 1+2
        assert seq.locate(9.0) == (1, 6.0)   # end of reel → clip1 out_point

    def test_zero_duration_clip_skipped(self) -> None:
        t = _timeline(("a.mp4", 10, 0, 4), ("z.mp4", 10, 5, 5), ("b.mp4", 10, 0, 3))
        seq = TimelineSequencer(t)
        # zero-length clip #1 contributes nothing; global 4..7 maps to clip #2
        assert seq.locate(4.0) == (2, 0.0)
        assert seq.locate(7.0) == (2, 3.0)


class TestGlobalOf:
    def test_inverse_of_locate(self) -> None:
        t = _timeline(("a.mp4", 10, 0, 4), ("b.mp4", 10, 1, 6))
        seq = TimelineSequencer(t)
        assert seq.global_of(0, 2.0) == 2.0
        assert seq.global_of(1, 1.0) == 4.0   # start of clip1
        assert seq.global_of(1, 3.0) == 6.0

    def test_local_clamped_to_window(self) -> None:
        t = _timeline(("b.mp4", 10, 1, 6))
        seq = TimelineSequencer(t)
        assert seq.global_of(0, 0.0) == 0.0   # below in_point → reel start
        assert seq.global_of(0, 99) == 5.0    # above out_point → reel end


class TestHelpers:
    def test_clip_start_global(self) -> None:
        t = _timeline(("a.mp4", 10, 0, 4), ("b.mp4", 10, 1, 6), ("c.mp4", 10, 0, 2))
        seq = TimelineSequencer(t)
        assert seq.clip_start_global(0) == 0.0
        assert seq.clip_start_global(1) == 4.0
        assert seq.clip_start_global(2) == 9.0

    def test_next_index_skips_zero_duration(self) -> None:
        t = _timeline(("a.mp4", 10, 0, 4), ("z.mp4", 10, 5, 5), ("b.mp4", 10, 0, 2))
        seq = TimelineSequencer(t)
        assert seq.next_index(0) == 2
        assert seq.next_index(2) is None
