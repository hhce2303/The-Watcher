from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.core.player.models import ClipInfo


class ClipInspectorPort(ABC):
    """Abstract port for extracting metadata from a media file.

    Implementations may use ffprobe, mediainfo, or any other backend.
    """

    @abstractmethod
    def inspect(self, path: Path) -> ClipInfo:
        """Analyse *path* and return a fully-populated :class:`ClipInfo`.

        Raises :exc:`FileNotFoundError` if the file does not exist.
        Raises :exc:`RuntimeError` if the probe backend reports an error.
        """
