"""Editor domain — evidence-reel timeline model and sequencer.

Pure domain logic (no Qt / FFmpeg / Rust).  Backs the IT editing tab's
multi-clip "evidence reel" (see docs/editing/goals.md, R-1).
"""
from __future__ import annotations

from app.core.editor.models import ClipEntry, EditTimeline
from app.core.editor.sequencer import TimelineSequencer

__all__ = ["ClipEntry", "EditTimeline", "TimelineSequencer"]
