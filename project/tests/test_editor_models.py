"""
Unit tests — Fase 0 (R-1, R-2): evidence-reel timeline model.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.editor.models import ClipEntry, EditTimeline


def _clip(name: str = "a.mp4", dur: float = 10.0, in_s: float = 0.0,
          out_s: float | None = None) -> ClipEntry:
    if out_s is None:
        return ClipEntry(Path(name), dur, in_s)
    return ClipEntry(Path(name), dur, in_s, out_s)


class TestClipEntry:
    def test_out_point_defaults_to_source_duration(self) -> None:
        c = ClipEntry(Path("a.mp4"), 12.5)
        assert c.out_point_s == 12.5
        assert c.in_point_s == 0.0
        assert c.trimmed_duration_s == 12.5

    def test_trimmed_duration(self) -> None:
        c = _clip(dur=10, in_s=2, out_s=7)
        assert c.trimmed_duration_s == 5.0

    def test_in_point_clamped_to_zero(self) -> None:
        assert _clip(in_s=-5, out_s=8).in_point_s == 0.0

    def test_out_point_clamped_to_duration(self) -> None:
        assert _clip(dur=10, out_s=99).out_point_s == 10.0

    def test_out_below_in_collapses_to_in(self) -> None:
        c = _clip(dur=10, in_s=6, out_s=3)
        assert c.in_point_s == 6.0
        assert c.out_point_s == 6.0
        assert c.trimmed_duration_s == 0.0

    def test_negative_duration_treated_as_zero(self) -> None:
        c = ClipEntry(Path("a.mp4"), -3.0)
        assert c.source_duration_s == 0.0
        assert c.trimmed_duration_s == 0.0

    def test_with_trim_returns_new_clamped_entry(self) -> None:
        c = _clip(dur=10)
        c2 = c.with_trim(3, 50)
        assert (c2.in_point_s, c2.out_point_s) == (3.0, 10.0)
        # original is frozen / unchanged
        assert c.out_point_s == 10.0

    def test_is_frozen(self) -> None:
        c = _clip()
        with pytest.raises((AttributeError, TypeError)):
            c.in_point_s = 1.0  # type: ignore[misc]

    def test_source_path_coerced_to_path(self) -> None:
        c = ClipEntry("plain/str.mp4", 5.0)  # type: ignore[arg-type]
        assert isinstance(c.source_path, Path)


class TestEditTimeline:
    def test_empty_by_default(self) -> None:
        t = EditTimeline()
        assert len(t) == 0
        assert t.total_duration_s == 0.0

    def test_add_returns_index(self) -> None:
        t = EditTimeline()
        assert t.add(_clip("a.mp4")) == 0
        assert t.add(_clip("b.mp4")) == 1
        assert len(t) == 2

    def test_total_duration_sums_trimmed(self) -> None:
        t = EditTimeline()
        t.add(_clip(dur=10, in_s=0, out_s=4))   # 4
        t.add(_clip(dur=10, in_s=2, out_s=9))   # 7
        assert t.total_duration_s == 11.0

    def test_remove_pops_and_returns(self) -> None:
        t = EditTimeline()
        t.add(_clip("a.mp4")); t.add(_clip("b.mp4"))
        removed = t.remove(0)
        assert removed.source_path == Path("a.mp4")
        assert len(t) == 1
        assert t[0].source_path == Path("b.mp4")

    def test_remove_out_of_range_raises(self) -> None:
        with pytest.raises(IndexError):
            EditTimeline().remove(0)

    def test_move_reorders(self) -> None:
        t = EditTimeline()
        for n in ("a", "b", "c"):
            t.add(_clip(f"{n}.mp4"))
        t.move(0, 2)  # a → after b,c
        assert [c.source_path.stem for c in t] == ["b", "c", "a"]

    def test_move_dst_clamped(self) -> None:
        t = EditTimeline()
        for n in ("a", "b"):
            t.add(_clip(f"{n}.mp4"))
        t.move(0, 99)
        assert [c.source_path.stem for c in t] == ["b", "a"]

    def test_move_src_out_of_range_raises(self) -> None:
        with pytest.raises(IndexError):
            EditTimeline().move(0, 0)

    def test_set_trim_replaces_entry(self) -> None:
        t = EditTimeline()
        t.add(_clip(dur=10))
        t.set_trim(0, 2, 6)
        assert t[0].trimmed_duration_s == 4.0

    def test_clear(self) -> None:
        t = EditTimeline()
        t.add(_clip()); t.clear()
        assert len(t) == 0

    def test_validate_empty(self) -> None:
        assert EditTimeline().validate()  # non-empty list of errors

    def test_validate_zero_duration_clip(self) -> None:
        t = EditTimeline()
        t.add(_clip(dur=10, in_s=5, out_s=5))
        errors = t.validate()
        assert any("#1" in e for e in errors)

    def test_validate_ok(self) -> None:
        t = EditTimeline()
        t.add(_clip(dur=10, in_s=0, out_s=5))
        assert t.validate() == []
