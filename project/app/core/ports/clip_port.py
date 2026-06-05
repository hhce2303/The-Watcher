from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.core.recording_service.models import MonitorInfo, Segment


class ClipPort(ABC):
    """
    Port defining how the core requests clip assembly from any backend.

    The core knows WHAT segments to use (per monitor), WHERE to write the
    output, and the precise time window to extract.  The adapter decides
    HOW to encode and composite them.

    monitor_segments: ordered mapping of MonitorInfo → segments for that monitor.
      - Single entry  → fast stream-copy (no re-encode).
      - Multiple entries → hstack composite clip (re-encodes to combine streams).

    clip_start / clip_end: exact UTC timestamps bounding the desired clip.
      With large (e.g. 1-hour) segment files the adapter uses these to write
      FFmpeg concat-demuxer ``inpoint``/``outpoint`` directives so only the
      relevant portion of each file is read — no intermediate trimming needed.
    """

    @abstractmethod
    def build_clip(
        self,
        monitor_segments: Dict[MonitorInfo, List[Segment]],
        output_path: Path,
        clip_start: Optional[datetime] = None,
        clip_end: Optional[datetime] = None,
    ) -> Path:
        """
        Assemble a clip from per-monitor segment lists.

        clip_start / clip_end bound the extraction window inside each segment.
        When provided the adapter must honour them precisely (via inpoint /
        outpoint or equivalent).  When omitted the full segment content is used.

        Returns the output_path on success.
        Raises RuntimeError on backend failure.
        """
