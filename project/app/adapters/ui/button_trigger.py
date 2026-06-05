from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import List

from app.core.ports.trigger_port import TriggerPort


class ButtonTrigger(TriggerPort):
    """
    Programmatic trigger adapter — used by the UI button and tests.

    Call fire() to simulate a button press from any context.
    """

    def __init__(self) -> None:
        self._callbacks: List[Callable[[datetime], None]] = []

    def subscribe(self, callback: Callable[[datetime], None]) -> None:
        self._callbacks.append(callback)

    def fire(self) -> None:
        """Fire the trigger with the current UTC timestamp."""
        now = datetime.now(tz=timezone.utc)
        for cb in self._callbacks:
            cb(now)
