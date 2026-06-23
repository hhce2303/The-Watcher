"""Detection / analytic-event schema (R-AI).

Versioned pydantic models shared by the (future) detector, the event store and
the editor's timeline markers.  Frozen + validated so the same record is safe to
persist to SQLite, serialise to a ``<clip>.events.json`` sidecar, and hand to QML.

Pure domain — no Qt / FFmpeg / ML imports.  A bump to ``SCHEMA_VERSION`` signals
an incompatible change (see docs/editing/roadmap.md §buenas prácticas).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, computed_field

SCHEMA_VERSION = "1.0"


class BoundingBox(BaseModel):
    """Axis-aligned box in **normalised** image coordinates (0..1)."""

    model_config = ConfigDict(frozen=True)

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(ge=0.0, le=1.0)
    h: float = Field(ge=0.0, le=1.0)


class Detection(BaseModel):
    """A single object detection in one frame (e.g. one YOLO box)."""

    model_config = ConfigDict(frozen=True)

    class_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox
    frame_time: datetime  # absolute wall-clock of the detected frame
    track_id: Optional[int] = None  # stable id across frames (tracker output)


class AnalyticEvent(BaseModel):
    """A bounded time interval of interest = clip + structured metadata.

    Produced by a manual trigger (``source="manual"``) today, or by an automatic
    detector (``source="auto:yolo"``) in a later phase.  Materialises as a clip
    (via the existing event pipeline) and as a queryable record + timeline marker.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = SCHEMA_VERSION
    event_id: str
    type: str = "manual"  # "manual" | "person" | "motion" | …
    source: str = "manual"  # "manual" | "auto:yolo" | "auto:motion" | …
    start: datetime
    end: datetime
    monitor_index: Optional[int] = None
    track_id: Optional[int] = None
    zone: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    clip_path: Optional[Path] = None
    detections: Tuple[Detection, ...] = ()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.end - self.start).total_seconds())
