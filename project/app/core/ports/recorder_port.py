from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class RecorderPort(ABC):
    """
    Port defining what the core expects from any recording backend.

    Implementations must be provided by adapters (e.g., FFmpegRecorderAdapter).
    """

    @abstractmethod
    def start(self, output_dir: Path) -> None:
        """Start continuous segment recording, writing files into output_dir."""

    @abstractmethod
    def stop(self) -> None:
        """Gracefully stop the recording process."""

    @abstractmethod
    def is_running(self) -> bool:
        """Return True if the recording process is active."""
