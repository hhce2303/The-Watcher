from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional


class Mp4ConverterPort(ABC):
    """Abstract port for converting a media file to MP4/H.264 format."""

    @abstractmethod
    def convert(
        self,
        source: Path,
        output: Optional[Path] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> Path:
        """Convert *source* to MP4.

        Args:
            source:      Input file path (any container supported by FFmpeg).
            output:      Destination path.  If *None*, a ``_converted.mp4`` suffix
                         is appended next to *source*.
            on_progress: Optional callback receiving a float in 0.0 – 1.0.

        Returns:
            The absolute path of the produced MP4 file.

        Raises:
            FileNotFoundError: if *source* does not exist.
            RuntimeError:      if the encoder reports a failure.
        """
