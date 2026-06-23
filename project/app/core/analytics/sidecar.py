"""Event sidecar (Fase 1, R-AI): ``<clip>.events.json`` next to each clip.

A versioned, regenerable JSON file holding the :class:`AnalyticEvent`s for a
clip — lets the editor overlay markers without a database, and survives DB loss.
Pure domain (stdlib + pydantic); no Qt/FFmpeg.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Sequence

from pydantic import BaseModel

from app.core.analytics.models import SCHEMA_VERSION, AnalyticEvent


class EventSidecar(BaseModel):
    """On-disk shape of a ``<clip>.events.json`` file."""

    schema_version: str = SCHEMA_VERSION
    clip: str = ""
    events: List[AnalyticEvent] = []


def sidecar_path(clip_path: Path) -> Path:
    """Return the sidecar path for *clip_path* (``foo.mp4`` → ``foo.events.json``)."""
    clip_path = Path(clip_path)
    return clip_path.with_suffix(".events.json")


def write_sidecar(clip_path: Path, events: Sequence[AnalyticEvent]) -> Path:
    """Write the sidecar for *clip_path*; return its path."""
    clip_path = Path(clip_path)
    sc = EventSidecar(clip=clip_path.name, events=list(events))
    path = sidecar_path(clip_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(sc.model_dump_json(indent=2), encoding="utf-8")
    return path


def read_sidecar(clip_path: Path) -> List[AnalyticEvent]:
    """Return events from *clip_path*'s sidecar, or ``[]`` if it does not exist."""
    path = sidecar_path(clip_path)
    if not path.exists():
        return []
    sc = EventSidecar.model_validate_json(path.read_text(encoding="utf-8"))
    return list(sc.events)
