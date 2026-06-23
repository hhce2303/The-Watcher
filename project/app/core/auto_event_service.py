"""AutoEventService (Fase 2, R-AI): turn detections into analytic events.

Subscribes to a :class:`DetectorPort`; when a detection clears the confidence
threshold and the cooldown has elapsed, it builds an :class:`AnalyticEvent`
(``source="auto:yolo"``) and dispatches it via a callback.  That callback is the
seam where wiring persists the event (EventStore + sidecar) and/or triggers the
clip build — exactly the same downstream pipeline as a manual event.

Cooldown mirrors :class:`EventService` so automatic events can't storm the
recorder.  ``clock`` is injectable for deterministic tests.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from app.core.analytics.models import AnalyticEvent, Detection
from app.core.ports.detector_port import DetectorPort


class AutoEventService:
    """Bridges a detector to the event pipeline with thresholding + cooldown."""

    def __init__(
        self,
        detector: DetectorPort,
        on_event: Callable[[AnalyticEvent], None],
        confidence_threshold: float = 0.6,
        cooldown_seconds: int = 30,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._detector = detector
        self._on_event = on_event
        self._threshold = confidence_threshold
        self._cooldown = cooldown_seconds
        self._clock = clock or (lambda: datetime.now(tz=timezone.utc))
        self._last_at: Optional[datetime] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._detector.subscribe(self._on_detections)
        self._detector.start()
        logger.info("[auto-event] started (threshold={}, cooldown={}s)", self._threshold, self._cooldown)

    def stop(self) -> None:
        self._detector.stop()

    def _on_detections(self, detections: Sequence[Detection]) -> bool:
        """Handle a batch of detections. Returns True if an event was emitted."""
        best = max(detections, key=lambda d: d.confidence, default=None)
        if best is None or best.confidence < self._threshold:
            return False

        now = self._clock()
        with self._lock:
            if self._last_at is not None:
                elapsed = (now - self._last_at).total_seconds()
                if elapsed < self._cooldown:
                    logger.debug("[auto-event] suppressed — cooldown ({:.0f}s left)",
                                 self._cooldown - elapsed)
                    return False
            self._last_at = now

        event = AnalyticEvent(
            event_id=now.strftime("%Y%m%d%H%M%S%f"),
            type=best.class_name,
            source="auto:yolo",
            start=now,
            end=now,
            confidence=best.confidence,
            track_id=best.track_id,
            detections=tuple(detections),
        )
        logger.info("[auto-event] {} (conf={:.2f}) → event {}",
                    best.class_name, best.confidence, event.event_id)
        self._on_event(event)
        return True
