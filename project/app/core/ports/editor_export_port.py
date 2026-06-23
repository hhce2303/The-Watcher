"""Port: export an evidence-reel timeline to a single MP4 (R-5).

Higher-level than :class:`SegmentCompilerPort`: it owns the *smart* strategy
(stream-copy when the cut is near a keyframe, re-encode only the boundary GOP for
frame accuracy — see docs/editing/adr/ADR-0002-smart-trim-copy-vs-encode.md),
then delegates the lossless concatenation to a ``SegmentCompilerPort``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

from app.core.editor.models import EditTimeline


class EditorExportPort(ABC):
    """Abstract port for rendering an :class:`EditTimeline` to one MP4 file."""

    @abstractmethod
    def export(
        self,
        timeline: EditTimeline,
        output_path: Path,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> Path:
        """Trim each clip and concatenate the reel into *output_path*.

        ``on_progress`` (if given) is called with a 0.0–1.0 fraction.

        Returns *output_path* on success.  Raises :exc:`ValueError` if the
        timeline is invalid (see ``EditTimeline.validate``) and
        :exc:`RuntimeError` on backend failure.
        """
