"""Mock detector (Fase 2, R-AI): a :class:`DetectorPort` with no real model.

Returns deterministic synthetic detections so the full detect→event→clip
pipeline (``AutoEventService``) can be wired and tested end-to-end before any
ONNX/YOLO model exists.  Real inference arrives in Fase 3 (ADR-0005).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, List

from loguru import logger

from app.core.analytics.models import BoundingBox, Detection
from app.core.ports.detector_port import DetectorPort


class MockDetectorAdapter(DetectorPort):
    """Emits one synthetic detection per analysed frame (configurable)."""

    def __init__(
        self,
        class_name: str = "person",
        confidence: float = 0.9,
        track_id: int = 1,
    ) -> None:
        self._class_name = class_name
        self._confidence = confidence
        self._track_id = track_id
        self._subs: List[Callable[[Sequence[Detection]], None]] = []
        self._started = False

    def analyze(self, frame: bytes, meta: dict[str, Any]) -> Sequence[Detection]:
        det = Detection(
            class_name=self._class_name,
            confidence=self._confidence,
            bbox=BoundingBox(x=0.4, y=0.4, w=0.2, h=0.2),
            frame_time=meta["frame_time"],
            track_id=self._track_id,
        )
        results: Sequence[Detection] = [det]
        for cb in list(self._subs):
            cb(results)
        return results

    def subscribe(self, callback: Callable[[Sequence[Detection]], None]) -> None:
        self._subs.append(callback)

    def start(self) -> None:
        self._started = True
        logger.info("[mock-detector] started (class={}, conf={})", self._class_name, self._confidence)

    def stop(self) -> None:
        self._started = False
        self._subs.clear()
