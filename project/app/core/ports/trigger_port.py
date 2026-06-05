from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime


class TriggerPort(ABC):
    """
    Port defining how the core receives external event triggers.

    Implementations are provided by adapters (e.g., ButtonTrigger, HotkeyTrigger).
    The core never knows *how* the event was raised — it only receives the timestamp.
    """

    @abstractmethod
    def subscribe(self, callback: Callable[[datetime], None]) -> None:
        """Register a callback that fires with the event timestamp when triggered."""
