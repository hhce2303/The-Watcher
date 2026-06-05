from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum, auto
from typing import Callable, Dict, List, Optional

from loguru import logger

from app.core.recording_service.models import MonitorInfo
from app.core.recording_service.monitor_worker import MonitorWorker


class WorkerHealth(Enum):
    RECORDING  = auto()   # FFmpeg is running
    RECOVERING = auto()   # supervisor is restarting it
    STOPPED    = auto()   # not started or permanently failed


class RecordingService:
    """
    Manages a pool of per-monitor recording workers.

    Design contract
    ---------------
    - All detected monitors are ALWAYS recorded.  The UI never starts or
      stops individual workers — that is the domain of MonitorDetectionService
      (which calls add_worker / remove_worker when hardware changes).
    - ``change_monitors()`` records a *clip-selection* checkpoint only: which
      monitors to include when assembling event clips.  It does not affect
      the recording processes themselves.
    - Health status is exposed per-worker so the UI and watchdog can observe
      the state without driving it.
    """

    def __init__(
        self,
        workers: List[MonitorWorker],
        on_worker_added: Optional[Callable[[MonitorInfo], None]] = None,
        on_worker_removed: Optional[Callable[[MonitorInfo], None]] = None,
    ) -> None:
        self._workers: Dict[int, MonitorWorker] = {
            w.monitor.index: w for w in workers
        }
        self._selected:   List[MonitorInfo] = []
        self._checkpoint: Optional[datetime] = None
        self._started:    bool = False

        # Callbacks fired when detection service adds/removes monitors at runtime
        self._on_worker_added   = on_worker_added
        self._on_worker_removed = on_worker_removed

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        self._started = True
        for worker in self._workers.values():
            worker.start()
            logger.info(
                "[RECORDING] Worker started: {} — capturing {}×{} @ ({},{})",
                worker.monitor.display_name,
                worker.monitor.width, worker.monitor.height,
                worker.monitor.x, worker.monitor.y,
            )
        logger.info(
            "RecordingService started — {} monitor worker(s) recording.",
            len(self._workers),
        )

    def stop(self) -> None:
        for worker in self._workers.values():
            worker.stop()
        self._started = False
        logger.info("RecordingService stopped.")

    def is_recording(self) -> bool:
        return any(w.is_running() for w in self._workers.values())

    # ── Dynamic worker management (driven by MonitorDetectionService) ──

    def add_worker(self, worker: MonitorWorker) -> None:
        """Called by MonitorDetectionService when a new monitor is detected."""
        idx = worker.monitor.index
        if idx in self._workers:
            logger.warning(
                "RecordingService.add_worker: worker for idx={} already exists — ignored.",
                idx,
            )
            return
        self._workers[idx] = worker
        if self._started:
            worker.start()
            logger.info(
                "[RECORDING+] Hot-added worker: {}",
                worker.monitor.display_name,
            )
        if self._on_worker_added is not None:
            try:
                self._on_worker_added(worker.monitor)
            except Exception:
                logger.exception("on_worker_added callback raised.")

    def remove_worker(self, monitor_index: int) -> None:
        """Called by MonitorDetectionService when a monitor is disconnected."""
        worker = self._workers.pop(monitor_index, None)
        if worker is None:
            logger.warning(
                "RecordingService.remove_worker: no worker for idx={} — ignored.",
                monitor_index,
            )
            return
        worker.stop()
        logger.warning(
            "[RECORDING-] Worker removed: {} (monitor disconnected).",
            worker.monitor.display_name,
        )
        if self._on_worker_removed is not None:
            try:
                self._on_worker_removed(worker.monitor)
            except Exception:
                logger.exception("on_worker_removed callback raised.")

    # ── Clip selection (UI concern, does not affect recording) ────────

    def change_monitors(self, monitors: List[MonitorInfo]) -> None:
        """Record which monitors to include in future *event clips* only.

        Does NOT start, stop, or restart any recording process.
        """
        if not monitors:
            return
        new_keys = frozenset(m.index for m in monitors)
        if new_keys == frozenset(m.index for m in self._selected):
            return
        self._selected   = list(monitors)
        self._checkpoint = datetime.now(tz=timezone.utc)
        for m in monitors:
            w = self._workers.get(m.index)
            if w is not None:
                w.buffer.set_segment_floor(self._checkpoint)
        logger.info(
            "Clip selection updated → {} monitor(s): {} | checkpoint={}",
            len(monitors),
            [m.display_name for m in monitors],
            self._checkpoint.isoformat(),
        )

    def change_monitor(self, monitor: MonitorInfo) -> None:
        self.change_monitors([monitor])

    # ── Health reporting ──────────────────────────────────────────────

    def worker_health(self, monitor_index: int) -> WorkerHealth:
        w = self._workers.get(monitor_index)
        if w is None:
            return WorkerHealth.STOPPED
        return WorkerHealth.RECORDING if w.is_running() else WorkerHealth.RECOVERING

    def health_report(self) -> dict:
        return {
            "workers": {
                idx: self.worker_health(idx).name
                for idx in self._workers
            },
            "recording": self.is_recording(),
        }

    # ── Queries ───────────────────────────────────────────────────────

    @property
    def selected_monitors(self) -> List[MonitorInfo]:
        return list(self._selected)

    @property
    def checkpoint(self) -> Optional[datetime]:
        return self._checkpoint

    def get_worker(self, monitor_index: int) -> Optional[MonitorWorker]:
        return self._workers.get(monitor_index)

    def total_stored_duration_seconds(self) -> float:
        return sum(
            w.buffer.total_duration_seconds()
            for w in self._workers.values()
            if w.is_running()
        )
