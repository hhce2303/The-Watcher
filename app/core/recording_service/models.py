from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, computed_field


class MonitorInfo(BaseModel):
    """Represents a physical display device."""

    model_config = ConfigDict(frozen=True)

    name: str
    width: int
    height: int
    x: int
    y: int
    is_primary: bool = False
    index: int = 0  # sequential position-based index (0=primary, then left→right)

    @computed_field
    @property
    def fingerprint(self) -> str:
        """Stable identifier that survives reboot and index changes."""
        return f"{self.name}_{self.width}x{self.height}_{self.x}_{self.y}"

    @computed_field
    @property
    def display_name(self) -> str:
        label = self.name.lstrip("\\\\.\\ ").lstrip("\\.")
        primary = " (Primary)" if self.is_primary else ""
        return f"{label}  {self.width}×{self.height}{primary}"


class Segment(BaseModel):
    """Represents a single recorded video segment on disk."""

    path: Path
    started_at: datetime
    ended_at: datetime
    # True once the segment's *real* end-time is known — i.e. the next segment
    # started (or the recorder stopped / a previous run was recovered).  While
    # False the segment is still in progress and ``ended_at`` is only an estimate
    # (started_at + segment_duration).  Event clip building (F5) waits for a
    # finalized segment covering the post-event window before assembling.
    finalized: bool = False

    @computed_field
    @property
    def duration_seconds(self) -> float:
        return (self.ended_at - self.started_at).total_seconds()

    @property
    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0


class Event(BaseModel):
    """Represents a triggered recording event."""

    triggered_at: datetime
    source: str = "manual"


@dataclass(frozen=True)
class EventContext:
    """Immutable snapshot of an event, taken at *trigger time* (pipeline F5).

    Captures WHICH monitors were selected and the exact clip window at the
    moment the event was accepted.  Building the clip from this snapshot makes
    the result deterministic even if the user changes the monitor selection
    during the post-event window, and gives every log line in the build branch
    a stable ``event_id`` for end-to-end correlation.
    """

    event_id: str
    triggered_at: datetime
    window_start: datetime
    window_end: datetime
    monitors: tuple[MonitorInfo, ...]
    requested_by: str = "manual"
