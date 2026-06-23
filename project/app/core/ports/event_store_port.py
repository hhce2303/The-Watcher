"""Port: persistence + querying of analytic events (R-AI — Fase 1 seam).

The editor reads this store to paint timeline markers; the event pipeline writes
to it.  Adapter v1 is SQLite (Fase 1).  See
docs/editing/adr/ADR-0004-ai-detection-seams.md.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from app.core.analytics.models import AnalyticEvent


class EventStorePort(ABC):
    """Abstract port for storing and querying :class:`AnalyticEvent`s."""

    @abstractmethod
    def add(self, event: AnalyticEvent) -> None:
        """Persist *event* (insert, or replace if ``event_id`` already exists)."""

    @abstractmethod
    def query(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        monitor_index: Optional[int] = None,
        type: Optional[str] = None,
    ) -> List[AnalyticEvent]:
        """Return events overlapping ``[start, end]`` filtered by monitor/type.

        All filters are optional; omitting them returns every event, newest first.
        """

    @abstractmethod
    def get(self, event_id: str) -> Optional[AnalyticEvent]:
        """Return the event with *event_id*, or ``None``."""
