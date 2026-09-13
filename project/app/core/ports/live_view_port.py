"""Read-only live-view boundary for remote Supervisor observation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class LiveViewHeartbeat:
    """Operational state published by an enrolled Operator daemon."""

    device_id: str
    station_id: int
    recording_state: str
    health: str
    monitors: tuple[int, ...]


class LiveViewPort(ABC):
    """Operator-only outbound presence and inbound read-only stream boundary."""

    @abstractmethod
    def start(self) -> bool: ...

    @abstractmethod
    def stop(self) -> None: ...
