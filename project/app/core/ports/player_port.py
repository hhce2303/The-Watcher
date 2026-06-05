from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class PlayerPort(ABC):
    """Abstract port for controlling media playback.

    The UI widget implements this port and exposes it to the domain.
    """

    @abstractmethod
    def load(self, path: Path) -> None:
        """Load a media file.  Does not auto-play."""

    @abstractmethod
    def play(self) -> None:
        """Start or resume playback."""

    @abstractmethod
    def pause(self) -> None:
        """Pause playback."""

    @abstractmethod
    def stop(self) -> None:
        """Stop playback and reset position to zero."""

    @abstractmethod
    def seek(self, position_ms: int) -> None:
        """Seek to *position_ms* milliseconds from the start."""

    @abstractmethod
    def set_volume(self, volume: float) -> None:
        """Set playback volume.  *volume* is in the range 0.0 – 1.0."""

    @property
    @abstractmethod
    def position_ms(self) -> int:
        """Current playback position in milliseconds."""

    @property
    @abstractmethod
    def duration_ms(self) -> int:
        """Total clip duration in milliseconds (0 if unknown)."""
