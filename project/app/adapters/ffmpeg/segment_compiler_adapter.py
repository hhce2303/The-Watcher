"""FFmpeg implementation of :class:`SegmentCompilerPort` (R-6 fallback).

Lossless stream-copy concatenation of MP4/TS sources via the FFmpeg concat
demuxer (``-c copy``).  This is the fallback engine; the Rust crate is the
default when its ``.pyd`` is built and ready (see ADR-0006).

The command is built by a pure ``_build_cmd`` method so it can be unit-tested
without invoking FFmpeg.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

from loguru import logger

from app.adapters.ffmpeg.encoder_selector import codec_tag, effective_codec
from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.core.ports.segment_compiler_port import SegmentCompilerPort


class FFmpegSegmentCompilerAdapter(SegmentCompilerPort):
    """Concatenate/trim sources losslessly with FFmpeg (stream copy)."""

    def __init__(self, codec: str = "h264") -> None:
        self._codec = codec

    @property
    def engine_name(self) -> str:
        return "ffmpeg"

    # ── Port API ──────────────────────────────────────────────────────
    def compile(
        self,
        sources: Sequence[Path],
        output_path: Path,
        in_point_s: Optional[float] = None,
        out_point_s: Optional[float] = None,
    ) -> Path:
        srcs = [Path(s) for s in sources]
        if not srcs:
            raise ValueError("compile() requires at least one source.")
        for s in srcs:
            if not s.exists():
                raise FileNotFoundError(s)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        concat_path = self._write_concat_file(srcs)
        try:
            cmd = self._build_cmd(concat_path, output_path, in_point_s, out_point_s)
            self._run(cmd, output_path)
        finally:
            concat_path.unlink(missing_ok=True)
        return output_path

    # ── Pure command builder (unit-tested) ────────────────────────────
    def _build_cmd(
        self,
        concat_path: Path,
        output_path: Path,
        in_point_s: Optional[float],
        out_point_s: Optional[float],
    ) -> List[str]:
        cmd: List[str] = [
            resolve_ffmpeg(),
            "-fflags", "+genpts",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_path),
        ]
        # Output-side window: keyframe-aligned with -c copy (lossless, fast).
        # Exact-frame cutting is the EditorExport adapter's job (boundary GOP
        # re-encode); the compiler stays purely stream-copy.
        if in_point_s is not None and in_point_s > 0:
            cmd += ["-ss", f"{float(in_point_s):.3f}"]
        if out_point_s is not None:
            cmd += ["-to", f"{float(out_point_s):.3f}"]
        cmd += [
            "-c", "copy",
            *codec_tag(effective_codec(self._codec)),
            "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart",
            "-y",
            str(output_path),
        ]
        return cmd

    def _write_concat_file(self, sources: List[Path]) -> Path:
        fd, path_str = tempfile.mkstemp(suffix=".txt", prefix="watcher_segcompile_")
        concat_path = Path(path_str)
        with open(fd, mode="w", encoding="utf-8") as f:
            for src in sources:
                safe = str(src.resolve()).replace("\\", "/").replace("'", r"'\''")
                f.write(f"file '{safe}'\n")
        return concat_path

    def _run(self, cmd: List[str], output_path: Path) -> None:
        logger.info("[segcompile] FFmpeg → {}", output_path.name)
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=900,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            logger.error("[segcompile] FFmpeg failed (rc={}):\n{}", result.returncode, stderr)
            if output_path.exists() and output_path.stat().st_size == 0:
                output_path.unlink(missing_ok=True)
            raise RuntimeError(f"FFmpeg segment compile failed (rc={result.returncode})")
