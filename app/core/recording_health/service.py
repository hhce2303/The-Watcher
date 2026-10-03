from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Dict, Optional, Protocol, runtime_checkable

from loguru import logger

from app.core.recording_service.service import RecordingService, WorkerHealth


@runtime_checkable
class LivenessCheck(Protocol):
    """Minimal duck-typed contract for a background service RecordingHealthService
    can watch — anything with ``is_alive()`` (a thread-backed adapter). Kept as a
    local Protocol (not an import of a concrete adapter) so this stays core-only
    and does not reach into ``app/adapters``.
    """

    def is_alive(self) -> bool: ...


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
    - Also watches any ``background_services`` passed in (e.g. the
      live-inference/auto-event thread) via ``is_alive()`` — these have no
      FFmpeg process to poll, but a dead one silently ends all further
      automatic events/clips while raw capture keeps running normally, which
      is otherwise invisible without reading logs.
    - If a background service stays dead for ``hang_grace_seconds`` straight,
      fires ``on_hang_timeout`` once — the composition root (main.py) decides
      what that means (e.g. a hard process exit so the OS-level restart
      watchdog revives a clean process); this service only detects and
      reports, it never takes down or restarts anything itself.
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
        background_services: Optional[Dict[str, LivenessCheck]] = None,
        on_hang_timeout: Optional[Callable[[list[str]], None]] = None,
        hang_grace_seconds: Optional[float] = None,
    ) -> None:
        self._rs              = recording_service
        self._interval        = poll_interval_seconds
        self._on_degraded     = on_degraded
        self._on_recovered    = on_recovered
        self._background_services = dict(background_services or {})
        self._on_hang_timeout = on_hang_timeout
        self._hang_grace_polls = (
            max(1, round(hang_grace_seconds / poll_interval_seconds))
            if hang_grace_seconds else None
        )

        self._stop_event      = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._consecutive_degraded = 0
        self._was_degraded         = False
        self._consecutive_background_dead = 0
        self._hang_timeout_fired   = False

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

    def set_callbacks(
        self,
        on_degraded: Optional[Callable[[dict], None]] = None,
        on_recovered: Optional[Callable[[], None]] = None,
    ) -> None:
        """Wire the facade callbacks post-construction (main.py owns ``api``)."""
        self._on_degraded = on_degraded
        self._on_recovered = on_recovered

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

        dead_background = [
            name for name, svc in self._background_services.items() if not svc.is_alive()
        ]
        if dead_background:
            all_ok = False
            problems.extend(f"{name} DEAD" for name in dead_background)
            self._consecutive_background_dead += 1
            logger.critical(
                "[HEALTH] background service(s) dead (poll #{}): {}",
                self._consecutive_background_dead,
                ", ".join(dead_background),
            )
        else:
            self._consecutive_background_dead = 0
            self._hang_timeout_fired = False

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

            if (
                dead_background
                and self._hang_grace_polls is not None
                and not self._hang_timeout_fired
                and self._consecutive_background_dead >= self._hang_grace_polls
            ):
                self._hang_timeout_fired = True
                logger.critical(
                    "[HEALTH] background service(s) {} dead for {} consecutive poll(s) "
                    "(~{:.0f}s) — firing on_hang_timeout.",
                    ", ".join(dead_background),
                    self._consecutive_background_dead,
                    self._consecutive_background_dead * self._interval,
                )
                if self._on_hang_timeout is not None:
                    try:
                        self._on_hang_timeout(dead_background)
                    except Exception:
                        logger.exception("on_hang_timeout callback raised.")
