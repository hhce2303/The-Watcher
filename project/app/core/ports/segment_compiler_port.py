"""Port: lossless compilation/concatenation of media segments into one MP4.

The default engine is the native Rust crate (``watcher_segments`` .pyd); FFmpeg
is the fallback.  See docs/editing/adr/ADR-0006-rust-segment-engine.md.

This is the low-level *stream-copy* seam (no decode/scale/encode).  Anything that
needs re-encoding (multi-monitor grid, frame-accurate boundary GOP) stays in the
FFmpeg adapters.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Sequence


class SegmentCompilerPort(ABC):
    """Abstract port for assembling one MP4 from one or more source files."""

    @abstractmethod
    def compile(
        self,
        sources: Sequence[Path],
        output_path: Path,
        in_point_s: Optional[float] = None,
        out_point_s: Optional[float] = None,
    ) -> Path:
        """Concatenate *sources* (in order) into *output_path*, losslessly.

        When ``in_point_s`` / ``out_point_s`` are given they bound a single
        window across the concatenation (cut on the nearest keyframe — exact
        framing is the caller's concern, see EditorExportPort).  Stream-copy
        only: no re-encode.

        Returns *output_path* on success.  Raises :exc:`RuntimeError` on backend
        failure and :exc:`FileNotFoundError` if a source is missing.
        """

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Identifier of the active backend, e.g. ``"rust"`` or ``"ffmpeg"`` —
        for logging and the Rust↔FFmpeg parity test."""
