"""
Unit tests — Fase 2 (R-AI): MockDetector + AutoEventService pipeline.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from app.adapters.ml.mock_detector import MockDetectorAdapter
from app.core.analytics.models import AnalyticEvent
from app.core.auto_event_service import AutoEventService

_T0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)


class _Clock:
    def __init__(self) -> None:
        self.now = _T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def _meta() -> dict:
    return {"frame_time": _T0, "monitor_index": 0, "width": 1920, "height": 1080}


class TestMockDetector:
    def test_analyze_returns_detection(self) -> None:
        d = MockDetectorAdapter().analyze(b"jpeg", _meta())
        assert len(d) == 1
        assert d[0].class_name == "person"

    def test_subscribe_notified_on_analyze(self) -> None:
        det = MockDetectorAdapter()
        seen: List = []
        det.subscribe(seen.append)
        det.analyze(b"x", _meta())
        assert len(seen) == 1


class TestAutoEventService:
    def test_detection_above_threshold_emits_event(self) -> None:
        det = MockDetectorAdapter(confidence=0.9)
        events: List[AnalyticEvent] = []
        svc = AutoEventService(det, events.append, confidence_threshold=0.6, cooldown_seconds=0)
        svc.start()
        det.analyze(b"x", _meta())
        assert len(events) == 1
        assert events[0].source == "auto:yolo"
        assert events[0].type == "person"
        assert events[0].confidence == 0.9

    def test_below_threshold_no_event(self) -> None:
        det = MockDetectorAdapter(confidence=0.3)
        events: List[AnalyticEvent] = []
        svc = AutoEventService(det, events.append, confidence_threshold=0.6, cooldown_seconds=0)
        svc.start()
        det.analyze(b"x", _meta())
        assert events == []

    def test_cooldown_suppresses_second(self) -> None:
        clock = _Clock()
        det = MockDetectorAdapter(confidence=0.9)
        events: List[AnalyticEvent] = []
        svc = AutoEventService(det, events.append, confidence_threshold=0.6,
                               cooldown_seconds=30, clock=clock)
        svc.start()
        det.analyze(b"x", _meta())
        det.analyze(b"x", _meta())  # immediately → cooldown
        assert len(events) == 1

    def test_cooldown_elapsed_emits_again(self) -> None:
        clock = _Clock()
        det = MockDetectorAdapter(confidence=0.9)
        events: List[AnalyticEvent] = []
        svc = AutoEventService(det, events.append, confidence_threshold=0.6,
                               cooldown_seconds=30, clock=clock)
        svc.start()
        det.analyze(b"x", _meta())
        clock.advance(31)
        det.analyze(b"x", _meta())
        assert len(events) == 2

    def test_empty_detections_no_event(self) -> None:
        events: List[AnalyticEvent] = []
        svc = AutoEventService(MockDetectorAdapter(), events.append, cooldown_seconds=0)
        assert svc._on_detections([]) is False
        assert events == []
