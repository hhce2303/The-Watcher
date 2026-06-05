from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from app.core.recording_service.models import MonitorInfo


class MonitorPort(ABC):
    """Port for discovering available display monitors."""

    @abstractmethod
    def list_monitors(self) -> List[MonitorInfo]:
        """Return all currently connected monitors."""
