from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path


class TimestampPort(ABC):
    """
    Port for burning a wall-clock timestamp overlay into a finished clip.

    Implementations receive the final clip path and the UTC start time of the
    clip so they can compute the exact frame time for every position in the video.

    The adapter overwrites the clip in-place (via a temp file) and returns the
    same path so callers do not need to track a new location.
    """

    @abstractmethod
    def burn(self, clip_path: Path, clip_start: datetime) -> Path:
        """Burn a per-frame datetime overlay into *clip_path*.

        Args:
            clip_path:  Path to the assembled MP4 clip (will be overwritten).
            clip_start: UTC datetime of the first frame of the clip.

        Returns:
            The path to the finished clip (same as *clip_path*).
        """
