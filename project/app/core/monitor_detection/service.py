from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import Enum, auto
from typing import List, Optional

from loguru import logger

from app.core.ports.monitor_port import MonitorPort
from app.core.recording_service.models import MonitorInfo


class DetectionHealth(Enum):
    HEALTHY   = auto()   # polling normally
    DEGRADED  = auto()   # thread crashed, recovering
    FAILED    = auto()   # max restarts exceeded, gave up


_INITIAL_BACKOFF = 2.0
_MAX_BACKOFF     = 30.0


class MonitorDetectionService:
    """
    Core service: continuously discovers physical monitors via MonitorPort.

    Responsibilities
    ----------------
    - Poll MonitorPort every ``poll_interval_seconds``.
    - Fire callbacks for added / removed / changed monitors.
    - Own its lifecycle (start / stop) independently of the UI.
    - Self-supervise: if the polling thread crashes, a watchdog restarts it
      with exponential back-off; after ``max_restarts`` consecutive failures
      the service marks itself FAILED and logs CRITICAL.

    The UI (AppBridge) and RecordingService register callbacks here.
    Neither of them drives detection — they only *react* to it.
    """

    def __init__(
        self,
        monitor_port: MonitorPort,
        poll_interval_seconds: float = 5.0,
        max_restarts: int = 10,
        on_monitor_added:   Optional[Callable[[MonitorInfo], None]] = None,
        on_monitor_removed: Optional[Callable[[MonitorInfo], None]] = None,
        on_monitors_changed: Optional[Callable[[List[MonitorInfo]], None]] = None,
    ) -> None:
        self._port             = monitor_port
        self._poll_interval    = poll_interval_seconds
        self._max_restarts     = max_restarts

        self._on_monitor_added    = on_monitor_added
        self._on_monitor_removed  = on_monitor_removed
        self._on_monitors_changed = on_monitors_changed

        self._lock    = threading.Lock()
        self._monitors: List[MonitorInfo] = []
        self._health  = DetectionHealth.HEALTHY
        self._restart_count = 0

        self._stop_event = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────

    def detect_now(self) -> List[MonitorInfo]:
        """Blocking first detection — call before start() to seed initial state."""
        monitors = self._do_poll()
        return monitors

    def start(self) -> None:
        """Start background polling + watchdog. Call after detect_now()."""
        self._stop_event.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="monitor-detection-watchdog",
        )
        self._watchdog_thread.start()
        logger.info(
            "MonitorDetectionService started — polling every {}s, max_restarts={}.",
            self._poll_interval, self._max_restarts,
        )

    def stop(self) -> None:
        """Gracefully stop detection."""
        self._stop_event.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=5)
            self._watchdog_thread = None
        logger.info("MonitorDetectionService stopped.")

    def get_monitors(self) -> List[MonitorInfo]:
        """Return last confirmed monitor list (thread-safe)."""
        with self._lock:
            return list(self._monitors)

    def is_running(self) -> bool:
        return (
            self._watchdog_thread is not None
            and self._watchdog_thread.is_alive()
            and not self._stop_event.is_set()
        )

    @property
    def health(self) -> DetectionHealth:
        return self._health

    def health_report(self) -> dict:
        with self._lock:
            monitors = list(self._monitors)
        return {
            "status":        self._health.name,
            "running":       self.is_running(),
            "monitor_count": len(monitors),
            "monitors":      [
                {
                    "name":    m.display_name,
                    "idx":     m.index,
                    "res":     f"{m.width}×{m.height}",
                    "pos":     f"({m.x},{m.y})",
                    "primary": m.is_primary,
                }
                for m in monitors
            ],
        }

    # ── Watchdog loop (outer) ─────────────────────────────────────────

    def _watchdog_loop(self) -> None:
        backoff = _INITIAL_BACKOFF
        consecutive = 0

        while not self._stop_event.is_set():
            try:
                self._detection_loop()
                # Clean exit: detection loop stopped via _stop_event
                if consecutive > 0:
                    self._health = DetectionHealth.HEALTHY
                    logger.info(
                        "MonitorDetectionService: recovered after {} restart(s).",
                        consecutive,
                    )
                break
            except Exception:
                if self._stop_event.is_set():
                    break
                consecutive += 1
                self._restart_count += 1

                if consecutive > self._max_restarts:
                    self._health = DetectionHealth.FAILED
                    logger.critical(
                        "MonitorDetectionService: detection loop crashed {} consecutive times. "
                        "Monitor detection is permanently stopped. "
                        "Restart the application to recover.",
                        consecutive,
                    )
                    return

                self._health = DetectionHealth.DEGRADED
                logger.error(
                    "MonitorDetectionService: detection loop crashed (restart {}/{}). "
                    "Retrying in {:.0f}s.",
                    consecutive, self._max_restarts, backoff,
                )
                self._stop_event.wait(timeout=backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF)

    # ── Detection loop (inner) ────────────────────────────────────────

    def _detection_loop(self) -> None:
        logger.debug("MonitorDetectionService: detection loop running.")
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._poll_interval)
            if self._stop_event.is_set():
                break
            self._do_poll()

    # ── Core poll ────────────────────────────────────────────────────

    def _do_poll(self) -> List[MonitorInfo]:
        """Query MonitorPort, compute diff, fire callbacks, update state."""
        new_monitors = self._port.list_monitors()

        with self._lock:
            old_by_fp = {m.fingerprint: m for m in self._monitors}
            new_by_fp = {m.fingerprint: m for m in new_monitors}

            added   = [m for fp, m in new_by_fp.items() if fp not in old_by_fp]
            removed = [m for fp, m in old_by_fp.items() if fp not in new_by_fp]

            self._monitors = list(new_monitors)

        if added or removed:
            logger.info(
                "MonitorDetectionService: change detected — "
                "+{} added, -{} removed. Total: {}.",
                len(added), len(removed), len(new_monitors),
            )
        else:
            logger.debug(
                "MonitorDetectionService: no change — {} monitor(s) stable.",
                len(new_monitors),
            )

        for m in added:
            logger.info(
                "  [MONITOR+] {} | {}×{} @ ({},{}) | primary={} | index={}",
                m.display_name, m.width, m.height, m.x, m.y, m.is_primary, m.index,
            )
            self._fire(self._on_monitor_added, m)

        for m in removed:
            logger.warning(
                "  [MONITOR-] {} | {}×{} @ ({},{}) | index={} — DISCONNECTED",
                m.display_name, m.width, m.height, m.x, m.y, m.index,
            )
            self._fire(self._on_monitor_removed, m)

        if (added or removed) and self._on_monitors_changed is not None:
            self._fire(self._on_monitors_changed, list(new_monitors))

        return list(new_monitors)

    @staticmethod
    def _fire(callback, *args) -> None:
        if callback is None:
            return
        try:
            callback(*args)
        except Exception:
            logger.exception("MonitorDetectionService: callback raised an exception.")
