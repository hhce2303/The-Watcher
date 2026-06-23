"""Editor reel export (R-5) — :class:`EditorExportPort` implementation.

Orchestrates the smart export: trims each clip and concatenates the reel into a
single MP4.  The lossless work (keyframe-aligned trim + concat) is delegated to a
:class:`SegmentCompilerPort` (Rust engine by default, FFmpeg fallback).

Current strategy: **stream-copy** (lossless, keyframe-aligned cuts).  Frame-exact
cutting via boundary-GOP re-encode is a planned enhancement of R-5
(ADR-0002) and is marked below; the copy path is fully functional and lossless.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, List, Optional

from loguru import logger

from app.core.editor.models import EditTimeline
from app.core.ports.editor_export_port import EditorExportPort
from app.core.ports.segment_compiler_port import SegmentCompilerPort


class FFmpegEditorExportAdapter(EditorExportPort):
    """Export an :class:`EditTimeline` to one MP4 using a segment compiler."""

    def __init__(
        self,
        segment_compiler: SegmentCompilerPort,
        work_dir: Optional[Path] = None,
    ) -> None:
        self._compiler = segment_compiler
        self._work_dir = Path(work_dir) if work_dir else None

    def export(
        self,
        timeline: EditTimeline,
        output_path: Path,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> Path:
        errors = timeline.validate()
        if errors:
            raise ValueError("Reel inválido: " + " ".join(errors))

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        def progress(frac: float) -> None:
            if on_progress is not None:
                on_progress(max(0.0, min(1.0, frac)))

        clips = list(timeline.clips)
        logger.info(
            "[export] Reel → {} ({} clip(s), engine={})",
            output_path.name, len(clips), self._compiler.engine_name,
        )

        # Single clip: one lossless trim, no concat.
        if len(clips) == 1:
            c = clips[0]
            self._compiler.compile([c.source_path], output_path, c.in_point_s, c.out_point_s)
            progress(1.0)
            logger.info("[export] Done: {}", output_path.name)
            return output_path

        # Multi-clip: trim each to a part, then concatenate the parts losslessly.
        # NOTE (R-5 enhancement): when frame-exact cuts are required, the boundary
        # GOP of each part should be re-encoded here before concatenation
        # (ADR-0002). The copy path below is lossless but cuts on keyframes.
        own_workdir = self._work_dir is None
        work = self._work_dir or Path(tempfile.mkdtemp(prefix="watcher_export_"))
        work.mkdir(parents=True, exist_ok=True)
        parts: List[Path] = []
        n = len(clips)
        try:
            for i, c in enumerate(clips):
                part = work / f"part_{i:03d}.mp4"
                self._compiler.compile([c.source_path], part, c.in_point_s, c.out_point_s)
                parts.append(part)
                progress((i + 1) / (n + 1))  # reserve final slice for the concat
            self._compiler.compile(parts, output_path)
            progress(1.0)
            logger.info("[export] Done: {} ({} parts)", output_path.name, n)
            return output_path
        finally:
            for p in parts:
                p.unlink(missing_ok=True)
            if own_workdir:
                try:
                    work.rmdir()
                except OSError:
                    pass
