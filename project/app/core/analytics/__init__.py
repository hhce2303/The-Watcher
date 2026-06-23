"""Analytics domain — detection / event schema for the future AI pipeline.

Fase 0 deliverable: the *schema* and seams only (no inference).  See
docs/editing/roadmap.md and docs/editing/adr/ADR-0004-ai-detection-seams.md.
"""
from __future__ import annotations

from app.core.analytics.models import (
    SCHEMA_VERSION,
    AnalyticEvent,
    BoundingBox,
    Detection,
)

__all__ = ["SCHEMA_VERSION", "AnalyticEvent", "BoundingBox", "Detection"]
