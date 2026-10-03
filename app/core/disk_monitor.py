from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

import psutil
from loguru import logger

_CHECK_INTERVAL = 30  # seconds
_WARN_THRESHOLD_BYTES = 2 * 1024 ** 3   # 2 GB — emit WARNING
_STOP_THRESHOLD_BYTES = 512 * 1024 ** 2  # 512 MB — stop recording


class DiskSpaceMonitor:
    """
    Periodically checks available disk space on the segment directory drive.

    Milestone 6 — Reliability & Hardening.

    - Warns at < 2 GB free (logged to UI log panel via loguru sink).
    - Calls ``on_low_disk`` callback at < 512 MB free so the caller can
      stop the recorder and alert the user.

    Usage::

        monitor = DiskSpaceMonitor(segment_dir, on_low_disk=recording_service.stop)
        monitor.start()
        ...
        monitor.stop()
    """

    def __init__(
        self,
        segment_dir: Path,
        on_low_disk: Optional[Callable[[], None]] = None,
        check_interval: int = _CHECK_INTERVAL,
        warn_threshold_bytes: int = _WARN_THRESHOLD_BYTES,
        stop_threshold_bytes: int = _STOP_THRESHOLD_BYTES,
    ) -> None:
        self._segment_dir = segment_dir
        self._on_low_disk = on_low_disk
        self._check_interval = check_interval
        self._warn_threshold = warn_threshold_bytes
        self._stop_threshold = stop_threshold_bytes

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._critical_fired = False  # only fire on_low_disk once per breach

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop_event.clear()
        self._critical_fired = False
        self._thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="disk-monitor",
        )
        self._thread.start()
        logger.debug("DiskSpaceMonitor started. Watching: {}", self._segment_dir)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    # ------------------------------------------------------------------
    # Monitor loop
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        # Run an immediate first check, then on interval
        self._check()
        while not self._stop_event.wait(timeout=self._check_interval):
            self._check()

    def _check(self) -> None:
        try:
            # Resolve to an existing ancestor so psutil can stat the drive
            path = self._segment_dir
            while not path.exists() and path != path.parent:
                path = path.parent
            usage = psutil.disk_usage(str(path))
            free = usage.free
        except Exception:  # noqa: BLE001
            logger.warning("DiskSpaceMonitor: could not read disk usage.")
            return

        free_gb = free / 1024 ** 3
        if free <= self._stop_threshold:
            logger.critical(
                "DISK CRITICALLY LOW: {:.2f} GB free — stopping recording to prevent data loss.",
                free_gb,
            )
            if not self._critical_fired:
                self._critical_fired = True
                if self._on_low_disk is not None:
                    try:
                        self._on_low_disk()
                    except Exception:  # noqa: BLE001
                        logger.exception("on_low_disk callback raised an exception.")
        elif free <= self._warn_threshold:
            logger.warning(
                "Disk space low: {:.2f} GB free. Consider freeing disk space.",
                free_gb,
            )
            self._critical_fired = False  # reset if we recover above stop threshold
        else:
            self._critical_fired = False
            logger.debug("Disk OK: {:.2f} GB free.", free_gb)
