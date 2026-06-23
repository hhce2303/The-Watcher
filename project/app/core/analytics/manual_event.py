"""Map a manual :class:`EventContext` to an :class:`AnalyticEvent` (Fase 1).

When the existing event pipeline builds a clip from a manual trigger, this turns
the frozen snapshot into a queryable analytic event so it shows up as a timeline
marker — the same record shape an automatic detector will later produce.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.core.analytics.models import AnalyticEvent
from app.core.recording_service.models import EventContext


def analytic_event_from_context(
    ctx: EventContext, clip_path: Optional[Path] = None
) -> AnalyticEvent:
    """Build an ``AnalyticEvent`` (source ``"manual"``) from an event snapshot."""
    monitor_index = ctx.monitors[0].index if ctx.monitors else None
    return AnalyticEvent(
        event_id=ctx.event_id,
        type="manual",
        source="manual",
        start=ctx.window_start,
        end=ctx.window_end,
        monitor_index=monitor_index,
        clip_path=Path(clip_path) if clip_path is not None else None,
    )
