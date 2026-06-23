"""Editor reel export (R-5) — :class:`EditorExportPort` implementation.

Orchestrates the smart export: trims each clip and concatenates the reel into a
single MP4.  The lossless work (keyframe-aligned trim + concat) is delegated to a
:class:`SegmentCompilerPort` (Rust engine by default, FFmpeg fallback).

Two strategies:

* **stream-copy** (default, ``reencode=False``) — lossless, fast, cuts on the
  nearest keyframe. Multi-clip concat requires uniform codec/resolution, so an
  up-front guard refuses mismatched sources instead of emitting a corrupt file.
* **re-encode** (``reencode=True``) — frame-exact cuts (input-seek + libx264)
  and every clip normalized to one resolution/fps, so mismatched sources just
  work. Slightly lossy and slower, but right for a precise evidence reel. The
  editor opts into this; the segment-compiler port stays pure stream-copy.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from loguru import logger

from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.core.editor.models import EditTimeline
from app.core.ports.clip_inspector_port import ClipInspectorPort
from app.core.ports.editor_export_port import EditorExportPort
from app.core.ports.segment_compiler_port import SegmentCompilerPort


class FFmpegEditorExportAdapter(EditorExportPort):
    """Export an :class:`EditTimeline` to one MP4 using a segment compiler."""

    def __init__(
        self,
        segment_compiler: SegmentCompilerPort,
        work_dir: Optional[Path] = None,
        inspector: Optional[ClipInspectorPort] = None,
        reencode: bool = False,
    ) -> None:
        self._compiler = segment_compiler
        self._work_dir = Path(work_dir) if work_dir else None
        # Optional: used to refuse a multi-clip concat whose sources have
        # incompatible codec/resolution. Stream-copy concat silently produces a
        # broken/truncated file in that case, so we catch it before exporting.
        self._inspector = inspector
        # Frame-exact + normalize mode (see module docstring). When on, the
        # codec/res guard is unnecessary because every part is re-encoded to a
        # common format.
        self._reencode = reencode

    def _assert_concat_compatible(self, clips: list) -> None:
        """Raise ValueError if the multi-clip sources can't be stream-copy joined.

        The FFmpeg concat demuxer with ``-c copy`` requires every input to share
        codec + resolution; otherwise it emits a corrupt, short file with no
        error. We turn that silent corruption into an actionable message.
        """
        if self._inspector is None or len(clips) <= 1:
            return
        sigs: dict[str, tuple] = {}
        for c in clips:
            try:
                v = self._inspector.inspect(c.source_path).video_stream
            except Exception:  # noqa: BLE001 — probe failure shouldn't block; concat will surface it
                logger.warning("[export] could not probe {} for compat check", c.source_path)
                continue
            sigs[c.source_path.name] = (
                (v.codec, v.width, v.height) if v else (None, None, None)
            )
        distinct = set(sigs.values())
        if len(distinct) > 1:
            detail = "; ".join(
                f"{name}: {codec or '?'} {w or '?'}x{h or '?'}"
                for name, (codec, w, h) in sigs.items()
            )
            raise ValueError(
                "Los clips tienen códecs o resoluciones distintos y no se pueden "
                "unir sin reconvertir. Usa clips del mismo formato. Detalle: " + detail
            )

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
        mode = "reencode" if self._reencode else "copy"
        logger.info(
            "[export] Reel → {} ({} clip(s), engine={}, mode={})",
            output_path.name, len(clips), self._compiler.engine_name, mode,
        )

        # Pick a common target up front when normalizing (frame-exact mode).
        target = self._target_format(clips) if self._reencode else None

        # ── Single clip: one trim, no concat. ─────────────────────────────
        if len(clips) == 1:
            c = clips[0]
            if self._reencode and target is not None:
                self._reencode_trim(c.source_path, output_path, c.in_point_s, c.out_point_s, target)
            else:
                self._compiler.compile([c.source_path], output_path, c.in_point_s, c.out_point_s)
            progress(1.0)
            logger.info("[export] Done: {}", output_path.name)
            return output_path

        # ── Multi-clip: trim each to a part, then concatenate. ────────────
        # Copy mode requires uniform sources, so guard first (silent corruption
        # otherwise). Re-encode mode normalizes every part to *target*, so any
        # mix of codecs/resolutions joins cleanly and the guard is unnecessary.
        if not self._reencode:
            self._assert_concat_compatible(clips)
        own_workdir = self._work_dir is None
        work = self._work_dir or Path(tempfile.mkdtemp(prefix="watcher_export_"))
        work.mkdir(parents=True, exist_ok=True)
        parts: List[Path] = []
        n = len(clips)
        try:
            for i, c in enumerate(clips):
                part = work / f"part_{i:03d}.mp4"
                if self._reencode and target is not None:
                    self._reencode_trim(c.source_path, part, c.in_point_s, c.out_point_s, target)
                else:
                    self._compiler.compile([c.source_path], part, c.in_point_s, c.out_point_s)
                parts.append(part)
                progress((i + 1) / (n + 1))  # reserve final slice for the concat
            # Parts are now uniform → lossless copy concat (compiler port).
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

    # ── Frame-exact re-encode helpers (reencode=True) ─────────────────────
    def _target_format(self, clips: list) -> Tuple[int, int, int]:
        """Common (width, height, fps) to normalize every clip to.

        Largest width/height seen (so nothing is upscaled past a source) and the
        highest fps, with sane fallbacks when probing is unavailable.
        """
        w = h = 0
        fps = 0
        if self._inspector is not None:
            for c in clips:
                try:
                    info = self._inspector.inspect(c.source_path)
                except Exception:  # noqa: BLE001
                    logger.warning("[export] could not probe {} for target format", c.source_path)
                    continue
                v = getattr(info, "video_stream", None)
                if v and v.width and v.height:
                    w = max(w, int(v.width)); h = max(h, int(v.height))
                ifps = getattr(info, "fps", None)
                if ifps:
                    fps = max(fps, int(round(ifps)))
        w = w or 1920
        h = h or 1080
        fps = fps if fps and fps <= 120 else 30
        # libx264 needs even dimensions.
        return (w - (w % 2), h - (h % 2), fps)

    def _reencode_trim(
        self, src: Path, out: Path, in_s: float, out_s: float, target: Tuple[int, int, int]
    ) -> None:
        """Frame-exact trim of [in_s, out_s] re-encoded to *target* (w, h, fps).

        Input-side ``-ss`` + libx264 gives an exact cut at *in_s*; scale+pad
        normalizes the picture so heterogeneous clips concatenate cleanly.
        """
        tw, th, fps = target
        dur = max(0.0, float(out_s) - float(in_s))
        vf = (
            f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
            f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={fps}"
        )
        cmd = [
            resolve_ffmpeg(),
            "-ss", f"{float(in_s):.3f}",
            "-i", str(Path(src)),
            "-t", f"{dur:.3f}",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart",
            "-y", str(Path(out)),
        ]
        logger.info("[export] re-encode trim → {} [{:.3f}s @ {}x{}]", Path(out).name, dur, tw, th)
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=900, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            logger.error("[export] re-encode failed (rc={}):\n{}", result.returncode, stderr)
            Path(out).unlink(missing_ok=True)
            raise RuntimeError(f"Fallo al recodificar el clip (rc={result.returncode}).")
