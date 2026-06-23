"""Port: object/event detection over video frames (R-AI — Fase 0 costura).

Declared now, implemented later (Fase 2 mock adapter → Fase 3 ONNX/`ort`).  The
recorder must never block on inference, so implementations run out-of-process or
on a worker thread and deliver results via ``subscribe`` (see
docs/editing/adr/ADR-0004-ai-detection-seams.md).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from typing import Any

from app.core.analytics.models import Detection


class DetectorPort(ABC):
    """Abstract port for analysing frames and emitting :class:`Detection`s."""

    @abstractmethod
    def analyze(self, frame: bytes, meta: dict[str, Any]) -> Sequence[Detection]:
        """Analyse a single encoded frame (e.g. JPEG bytes).

        *meta* carries at least ``{"frame_time": datetime, "monitor_index": int,
        "width": int, "height": int}``.  Returns the detections found (possibly
        empty).  Raises :exc:`RuntimeError` if inference fails.
        """

    @abstractmethod
    def subscribe(self, callback: Callable[[Sequence[Detection]], None]) -> None:
        """Register *callback*, invoked asynchronously with each batch of results."""

    @abstractmethod
    def start(self) -> None:
        """Acquire resources (load model, allocate device)."""

    @abstractmethod
    def stop(self) -> None:
        """Release resources.  Idempotent."""
