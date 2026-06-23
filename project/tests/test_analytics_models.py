"""
Unit tests — Fase 0 (R-AI): detection / analytic-event schema.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.core.analytics.models import (
    SCHEMA_VERSION,
    AnalyticEvent,
    BoundingBox,
    Detection,
)

_T0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)


def _detection() -> Detection:
    return Detection(
        class_name="person",
        confidence=0.91,
        bbox=BoundingBox(x=0.1, y=0.2, w=0.3, h=0.4),
        frame_time=_T0,
        track_id=7,
    )


class TestBoundingBox:
    def test_valid(self) -> None:
        BoundingBox(x=0.0, y=0.0, w=1.0, h=1.0)

    def test_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BoundingBox(x=-0.1, y=0, w=0.5, h=0.5)
        with pytest.raises(ValidationError):
            BoundingBox(x=0, y=0, w=1.5, h=0.5)


class TestDetection:
    def test_fields(self) -> None:
        d = _detection()
        assert d.class_name == "person"
        assert d.track_id == 7

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Detection(class_name="x", confidence=1.5,
                      bbox=BoundingBox(x=0, y=0, w=0.1, h=0.1), frame_time=_T0)

    def test_frozen(self) -> None:
        with pytest.raises(ValidationError):
            _detection().confidence = 0.5  # type: ignore[misc]


class TestAnalyticEvent:
    def test_defaults(self) -> None:
        e = AnalyticEvent(event_id="120000", start=_T0, end=_T0 + timedelta(seconds=30))
        assert e.schema_version == SCHEMA_VERSION
        assert e.source == "manual"
        assert e.type == "manual"
        assert e.detections == ()

    def test_duration_seconds_computed(self) -> None:
        e = AnalyticEvent(event_id="e", start=_T0, end=_T0 + timedelta(seconds=42))
        assert e.duration_seconds == 42.0

    def test_negative_interval_clamped_to_zero(self) -> None:
        e = AnalyticEvent(event_id="e", start=_T0, end=_T0 - timedelta(seconds=5))
        assert e.duration_seconds == 0.0

    def test_with_detections(self) -> None:
        e = AnalyticEvent(
            event_id="e", type="person", source="auto:yolo",
            start=_T0, end=_T0 + timedelta(seconds=10),
            detections=(_detection(),),
        )
        assert len(e.detections) == 1
        assert e.detections[0].class_name == "person"

    def test_json_round_trip(self) -> None:
        """Sidecar serialisation (Fase 1) must round-trip losslessly."""
        e = AnalyticEvent(
            event_id="e", source="auto:yolo", start=_T0,
            end=_T0 + timedelta(seconds=10), monitor_index=1, confidence=0.8,
            detections=(_detection(),),
        )
        restored = AnalyticEvent.model_validate_json(e.model_dump_json())
        assert restored == e

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValidationError):
            AnalyticEvent(event_id="e", start=_T0, end=_T0, confidence=2.0)
