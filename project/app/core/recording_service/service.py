from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from loguru import logger

from app.core.recording_service.context import (
    LifecycleState,
    MonitorContext,
    WorkerHealth,
    new_session_id,
)
from app.core.recording_service.models import MonitorInfo
from app.core.recording_service.monitor_worker import MonitorWorker

# Re-exported for backwards compatibility — RecordingHealthService and others
# import WorkerHealth from this module.
__all__ = ["RecordingService", "WorkerHealth"]


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

    Per-monitor state (lifecycle, clip-selection flag, segment floor, session id
    and audit counters) lives in one :class:`MonitorContext` per worker — the
    single source of truth, keyed by monitor index.
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
        self._contexts: Dict[int, MonitorContext] = {
            w.monitor.index: MonitorContext(
                info=w.monitor, session_id=new_session_id()
            )
            for w in workers
        }
        self._checkpoint: Optional[datetime] = None
        self._started:    bool = False

        # Callbacks fired when detection service adds/removes monitors at runtime
        self._on_worker_added   = on_worker_added
        self._on_worker_removed = on_worker_removed

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        self._started = True
        for idx, worker in self._workers.items():
            worker.start()
            ctx = self._contexts.get(idx)
            if ctx is not None:
                ctx.lifecycle = LifecycleState.CAPTURING
            log = logger.bind(
                phase="RECORDING",
                mon=f"m{idx}",
                sid=ctx.session_id if ctx else "-",
            )
            log.info(
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
        for idx, worker in self._workers.items():
            worker.stop()
            ctx = self._contexts.get(idx)
            if ctx is not None:
                ctx.lifecycle = LifecycleState.RETIRED
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
        ctx = MonitorContext(info=worker.monitor, session_id=new_session_id())
        self._contexts[idx] = ctx
        if self._started:
            worker.start()
            ctx.lifecycle = LifecycleState.CAPTURING
            logger.bind(phase="PROVISION", mon=f"m{idx}", sid=ctx.session_id).info(
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
        ctx = self._contexts.get(monitor_index)
        if worker is None:
            logger.warning(
                "RecordingService.remove_worker: no worker for idx={} — ignored.",
                monitor_index,
            )
            return
        worker.stop()
        if ctx is not None:
            ctx.lifecycle = LifecycleState.RETIRED
        logger.bind(
            phase="PROVISION",
            mon=f"m{monitor_index}",
            sid=ctx.session_id if ctx else "-",
        ).warning(
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
        current = frozenset(idx for idx, c in self._contexts.items() if c.is_active)
        if new_keys == current:
            return
        self._checkpoint = datetime.now(tz=timezone.utc)
        for idx, ctx in self._contexts.items():
            active = idx in new_keys
            ctx.is_active = active
            if active:
                ctx.segment_floor = self._checkpoint
                w = self._workers.get(idx)
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
            "lifecycle": {
                idx: ctx.lifecycle.name for idx, ctx in self._contexts.items()
            },
            "sessions": {
                idx: ctx.session_id for idx, ctx in self._contexts.items()
            },
            "recording": self.is_recording(),
        }

    # ── Queries ───────────────────────────────────────────────────────

    @property
    def selected_monitors(self) -> List[MonitorInfo]:
        return [
            ctx.info
            for idx, ctx in sorted(self._contexts.items())
            if ctx.is_active
        ]

    @property
    def checkpoint(self) -> Optional[datetime]:
        return self._checkpoint

    def get_worker(self, monitor_index: int) -> Optional[MonitorWorker]:
        return self._workers.get(monitor_index)

    def get_context(self, monitor_index: int) -> Optional[MonitorContext]:
        return self._contexts.get(monitor_index)

    def total_stored_duration_seconds(self) -> float:
        return sum(
            w.buffer.total_duration_seconds()
            for w in self._workers.values()
            if w.is_running()
        )
