from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from loguru import logger

# OneDrive / Windows Defender may hold a brief lock on freshly-written files.
# Retry once after this delay (seconds) before logging the error.
_DELETE_RETRY_DELAY = 0.25

from app.core.ports.storage_port import StoragePort
from app.core.recording_service.models import Segment

_SEGMENT_FILENAME_RE = re.compile(
    r"seg_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.ts$"
)


class FilesystemStorageAdapter(StoragePort):
    """
    Local-filesystem implementation of StoragePort.

    Segments are identified by the naming convention produced by
    FFmpegRecorderAdapter: seg_YYYYMMDD_HHMMSS.ts
    """

    def list_segments(self, directory: Path) -> List[Segment]:
        """
        Scan directory for completed segment files.

        Start time is parsed from the filename. End time is inferred from
        the file modification time (last byte written by FFmpeg).
        Used for recovering the buffer index after an application restart.
        """
        segments: List[Segment] = []
        for path in sorted(directory.glob("seg_*.ts")):
            match = _SEGMENT_FILENAME_RE.search(path.name)
            if not match:
                continue
            year, month, day, hour, minute, second = (
                int(g) for g in match.groups()
            )
            # FFmpeg strftime uses local time — parse naive then convert to UTC
            started_at = datetime(
                year, month, day, hour, minute, second
            ).astimezone(timezone.utc)
            try:
                mtime = path.stat().st_mtime
                ended_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
            except OSError:
                ended_at = started_at

            segments.append(
                Segment(path=path, started_at=started_at, ended_at=ended_at)
            )
        return segments

    def delete_segment(self, segment: Segment) -> None:
        try:
            segment.path.unlink(missing_ok=True)
            logger.debug("Deleted: {}", segment.path.name)
        except OSError:
            # OneDrive / Defender can briefly lock a file (WinError 5 / 32).
            # Wait a short moment and retry once before giving up.
            time.sleep(_DELETE_RETRY_DELAY)
            try:
                segment.path.unlink(missing_ok=True)
                logger.debug("Deleted (retry): {}", segment.path.name)
            except OSError as exc:
                logger.warning("Could not delete {}: {} — will retry next cycle", segment.path.name, exc)

    def ensure_directory(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
