from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Optional

from loguru import logger

from app.core.recording_service.service import RecordingService, WorkerHealth


class RecordingHealthService:
    """
    Watchdog that sits above the per-process RecorderSupervisor.

    RecorderSupervisor handles individual FFmpeg crash → restart.
    RecordingHealthService operates at the worker pool level:

    - Polls every ``poll_interval_seconds``.
    - Logs the health of every registered worker at DEBUG (steady state)
      or WARNING/CRITICAL (degraded / permanently failed).
    - Fires ``on_degraded`` when any worker is not RECORDING so the UI can
      show a warning badge without needing to know about individual workers.
    - Has its own daemon thread with internal exception guard so it never
      takes down the application if it crashes.

    This service depends only on RecordingService (core) — no adapters.
    """

    _DEGRADED_WARN_INTERVAL  = 3   # log CRITICAL after this many degraded polls
    _FAILED_LOG_THROTTLE     = 10  # only repeat CRITICAL every N polls

    def __init__(
        self,
        recording_service: RecordingService,
        poll_interval_seconds: float = 30.0,
        on_degraded: Optional[Callable[[dict], None]] = None,
        on_recovered: Optional[Callable[[], None]] = None,
    ) -> None:
        self._rs              = recording_service
        self._interval        = poll_interval_seconds
        self._on_degraded     = on_degraded
        self._on_recovered    = on_recovered

        self._stop_event      = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._consecutive_degraded = 0
        self._was_degraded         = False

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="recording-health-watchdog",
        )
        self._thread.start()
        logger.info(
            "RecordingHealthService started — polling every {}s.",
            self._interval,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("RecordingHealthService stopped.")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Main loop ─────────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            try:
                self._check()
            except Exception:
                logger.exception("RecordingHealthService: unexpected error in health check.")

    def _check(self) -> None:
        report = self._rs.health_report()
        all_ok  = True
        problems: list[str] = []

        for idx, status in report["workers"].items():
            if status == WorkerHealth.RECORDING.name:
                logger.debug("[HEALTH] monitor idx={} — RECORDING ✓", idx)
            elif status == WorkerHealth.RECOVERING.name:
                all_ok = False
                problems.append(f"idx={idx} RECOVERING")
                logger.warning("[HEALTH] monitor idx={} — RECOVERING (supervisor restarting FFmpeg)", idx)
            else:  # STOPPED
                all_ok = False
                problems.append(f"idx={idx} STOPPED")
                logger.critical("[HEALTH] monitor idx={} — STOPPED (recording lost, no more restarts)", idx)

        if not report["workers"]:
            logger.warning("[HEALTH] RecordingService has no registered workers.")

        if all_ok:
            self._consecutive_degraded = 0
            if self._was_degraded:
                self._was_degraded = False
                logger.info("[HEALTH] All workers recovered — recording healthy.")
                if self._on_recovered is not None:
                    try:
                        self._on_recovered()
                    except Exception:
                        logger.exception("on_recovered callback raised.")
        else:
            self._consecutive_degraded += 1
            self._was_degraded = True
            if self._consecutive_degraded <= self._DEGRADED_WARN_INTERVAL or \
               self._consecutive_degraded % self._FAILED_LOG_THROTTLE == 0:
                logger.error(
                    "[HEALTH] Recording degraded for {} consecutive poll(s): {}",
                    self._consecutive_degraded,
                    ", ".join(problems),
                )
            if self._on_degraded is not None:
                try:
                    self._on_degraded(report)
                except Exception:
                    logger.exception("on_degraded callback raised.")
