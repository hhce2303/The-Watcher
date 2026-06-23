"""
Unit tests — Fase 0 (R-5): editor reel export orchestration.

The SegmentCompilerPort is mocked: we verify the trim/concat call sequence and
progress reporting, not real FFmpeg output.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.adapters.ffmpeg.editor_export_adapter import FFmpegEditorExportAdapter
from app.core.editor.models import ClipEntry, EditTimeline
from app.core.ports.segment_compiler_port import SegmentCompilerPort


def _mock_compiler() -> MagicMock:
    m = MagicMock(spec=SegmentCompilerPort)
    m.engine_name = "ffmpeg"
    m.compile.side_effect = (
        lambda sources, output_path, in_point_s=None, out_point_s=None: Path(output_path)
    )
    return m


def _timeline(*durs: tuple[float, float, float]) -> EditTimeline:
    """durs: (source_duration, in, out)."""
    t = EditTimeline()
    for i, (d, a, b) in enumerate(durs):
        t.add(ClipEntry(Path(f"clip{i}.mp4"), d, a, b))
    return t


def _stream(codec: str, w: int, h: int, fps: float = 30.0):
    from types import SimpleNamespace
    return SimpleNamespace(
        video_stream=SimpleNamespace(codec=codec, width=w, height=h), fps=fps
    )


class _FakeInspector:
    """Returns a per-filename (codec, w, h) signature for the compat guard."""

    def __init__(self, by_name: dict) -> None:
        self._by_name = by_name

    def inspect(self, path: Path):
        return self._by_name[path.name]


def test_empty_timeline_raises(tmp_path: Path) -> None:
    adapter = FFmpegEditorExportAdapter(_mock_compiler())
    with pytest.raises(ValueError):
        adapter.export(EditTimeline(), tmp_path / "out.mp4")


def test_mismatched_streams_rejected_before_concat(tmp_path: Path) -> None:
    comp = _mock_compiler()
    insp = _FakeInspector({
        "clip0.mp4": _stream("hevc", 1920, 1080),
        "clip1.mp4": _stream("h264", 1280, 720),
    })
    adapter = FFmpegEditorExportAdapter(comp, inspector=insp)
    with pytest.raises(ValueError, match="códecs o resoluciones distintos"):
        adapter.export(_timeline((10, 0, 4), (10, 0, 4)), tmp_path / "out.mp4")
    comp.compile.assert_not_called()  # refused before doing any ffmpeg work


def test_matching_streams_allowed(tmp_path: Path) -> None:
    comp = _mock_compiler()
    insp = _FakeInspector({
        "clip0.mp4": _stream("hevc", 1920, 1080),
        "clip1.mp4": _stream("hevc", 1920, 1080),
    })
    adapter = FFmpegEditorExportAdapter(comp, work_dir=tmp_path / "w", inspector=insp)
    adapter.export(_timeline((10, 0, 4), (10, 0, 4)), tmp_path / "out.mp4")
    assert comp.compile.call_count == 3  # 2 trims + 1 concat


def test_no_inspector_skips_compat_check(tmp_path: Path) -> None:
    # Backward compatible: without an inspector the guard is a no-op.
    comp = _mock_compiler()
    adapter = FFmpegEditorExportAdapter(comp, work_dir=tmp_path / "w")
    adapter.export(_timeline((10, 0, 4), (10, 0, 4)), tmp_path / "out.mp4")
    assert comp.compile.call_count == 3


def test_reencode_normalizes_mismatched_and_skips_guard(tmp_path: Path, monkeypatch) -> None:
    # Re-encode mode: every clip re-encoded to a common target, so mismatched
    # codecs/resolutions are NOT rejected — they're normalized.
    comp = _mock_compiler()
    insp = _FakeInspector({
        "clip0.mp4": _stream("hevc", 1920, 1080, 30),
        "clip1.mp4": _stream("h264", 1280, 720, 60),
    })
    adapter = FFmpegEditorExportAdapter(comp, work_dir=tmp_path / "w",
                                        inspector=insp, reencode=True)
    calls: list = []

    def fake_trim(src, out, in_s, out_s, target):
        calls.append((Path(src).name, target))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"x")

    monkeypatch.setattr(adapter, "_reencode_trim", fake_trim)
    adapter.export(_timeline((10, 0, 4), (10, 0, 4)), tmp_path / "out.mp4")

    assert len(calls) == 2                  # both clips re-encoded (no reject)
    assert comp.compile.call_count == 1     # compiler only does the final concat
    # target = max dims (1920x1080), max fps (60)
    assert calls[0][1] == (1920, 1080, 60)


def test_reencode_single_clip_uses_trim_only(tmp_path: Path, monkeypatch) -> None:
    comp = _mock_compiler()
    insp = _FakeInspector({"clip0.mp4": _stream("hevc", 1920, 1080, 30)})
    adapter = FFmpegEditorExportAdapter(comp, inspector=insp, reencode=True)
    seen: list = []
    monkeypatch.setattr(adapter, "_reencode_trim",
                        lambda *a: seen.append(a) or Path(a[1]).write_bytes(b"x"))
    out = tmp_path / "out.mp4"
    adapter.export(_timeline((10, 2, 8)), out)
    assert len(seen) == 1 and seen[0][1] == out   # exact trim straight to output
    comp.compile.assert_not_called()              # no concat for a single clip


def test_target_format_falls_back_without_inspector(tmp_path: Path) -> None:
    adapter = FFmpegEditorExportAdapter(_mock_compiler(), reencode=True)
    assert adapter._target_format([]) == (1920, 1080, 30)


def test_single_clip_one_compile(tmp_path: Path) -> None:
    comp = _mock_compiler()
    adapter = FFmpegEditorExportAdapter(comp)
    out = tmp_path / "out.mp4"
    result = adapter.export(_timeline((10, 2, 8)), out)
    assert result == out
    comp.compile.assert_called_once()
    args, kwargs = comp.compile.call_args
    assert args[0] == [Path("clip0.mp4")]
    assert args[1] == out
    assert (args[2], args[3]) == (2.0, 8.0)


def test_multi_clip_trims_then_concats(tmp_path: Path) -> None:
    comp = _mock_compiler()
    adapter = FFmpegEditorExportAdapter(comp, work_dir=tmp_path / "work")
    out = tmp_path / "out.mp4"
    adapter.export(_timeline((10, 0, 4), (10, 1, 6), (10, 0, 3)), out)
    # 3 part-trims + 1 final concat = 4 calls
    assert comp.compile.call_count == 4
    # last call is the concat: a list of 3 part paths → output, no window
    last_args = comp.compile.call_args_list[-1].args
    assert isinstance(last_args[0], list) and len(last_args[0]) == 3
    assert last_args[1] == out


def test_progress_reaches_one(tmp_path: Path) -> None:
    comp = _mock_compiler()
    adapter = FFmpegEditorExportAdapter(comp, work_dir=tmp_path / "work")
    seen: list[float] = []
    adapter.export(_timeline((10, 0, 4), (10, 0, 5)), tmp_path / "out.mp4", on_progress=seen.append)
    assert seen
    assert seen[-1] == 1.0
    assert all(0.0 <= f <= 1.0 for f in seen)


def test_zero_duration_clip_makes_timeline_invalid(tmp_path: Path) -> None:
    comp = _mock_compiler()
    adapter = FFmpegEditorExportAdapter(comp)
    with pytest.raises(ValueError):
        adapter.export(_timeline((10, 5, 5)), tmp_path / "out.mp4")
