from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from app.core.recording_service.models import Segment


class StoragePort(ABC):
    """
    Port defining what the core expects from any storage backend.

    Implementations must be provided by adapters (e.g., FilesystemStorageAdapter).
    """

    @abstractmethod
    def list_segments(self, directory: Path) -> List[Segment]:
        """Return all complete segment files found in directory, ordered by start time."""

    @abstractmethod
    def delete_segment(self, segment: Segment) -> None:
        """Permanently delete a segment file from storage."""

    @abstractmethod
    def ensure_directory(self, path: Path) -> None:
        """Create the directory if it does not already exist."""
