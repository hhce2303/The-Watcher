from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class PlaybackState(Enum):
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED  = "paused"


@dataclass(frozen=True)
class StreamInfo:
    """Represents a single stream (video, audio, subtitle…) within a media file."""

    index: int
    type: str           # "video" | "audio" | "subtitle" | "data" | "unknown"
    codec: str

    # Video-specific
    width:        Optional[int]   = None
    height:       Optional[int]   = None
    fps:          Optional[float] = None
    pixel_format: Optional[str]   = None

    # Audio-specific
    sample_rate: Optional[int] = None
    channels:    Optional[int] = None

    # Common
    bitrate_kbps: Optional[int] = None
    language:     Optional[str] = None


@dataclass(frozen=True)
class ClipInfo:
    """Full metadata for a single clip file, as inspected by ffprobe."""

    path:             Path
    duration_seconds: float
    size_bytes:       int
    streams:          List[StreamInfo] = field(default_factory=list)

    # ── derived helpers ───────────────────────────────────────────────

    @property
    def video_stream(self) -> Optional[StreamInfo]:
        return next((s for s in self.streams if s.type == "video"), None)

    @property
    def audio_streams(self) -> List[StreamInfo]:
        return [s for s in self.streams if s.type == "audio"]

    @property
    def resolution(self) -> Optional[tuple[int, int]]:
        v = self.video_stream
        return (v.width, v.height) if v and v.width and v.height else None

    @property
    def fps(self) -> Optional[float]:
        v = self.video_stream
        return v.fps if v else None

    @property
    def video_codec(self) -> Optional[str]:
        v = self.video_stream
        return v.codec if v else None

    @property
    def duration_str(self) -> str:
        total = int(self.duration_seconds)
        mins, secs = divmod(total, 60)
        hrs, mins = divmod(mins, 60)
        if hrs:
            return f"{hrs}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"

    @property
    def size_str(self) -> str:
        mb = self.size_bytes / 1_048_576
        return f"{mb:.1f} MB"
