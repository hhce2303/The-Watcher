"""
Unit tests — Fase 1 (R-AI): event sidecar JSON.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.analytics.models import AnalyticEvent
from app.core.analytics.sidecar import read_sidecar, sidecar_path, write_sidecar

_T0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)


def _event(eid: str = "a") -> AnalyticEvent:
    return AnalyticEvent(event_id=eid, start=_T0, end=_T0 + timedelta(seconds=20))


def test_sidecar_path_naming(tmp_path: Path) -> None:
    assert sidecar_path(tmp_path / "clip.mp4").name == "clip.events.json"


def test_write_read_round_trip(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    events = [_event("a"), _event("b")]
    path = write_sidecar(clip, events)
    assert path.exists()
    restored = read_sidecar(clip)
    assert restored == events


def test_read_missing_returns_empty(tmp_path: Path) -> None:
    assert read_sidecar(tmp_path / "ghost.mp4") == []


def test_write_empty(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mp4"
    write_sidecar(clip, [])
    assert read_sidecar(clip) == []
