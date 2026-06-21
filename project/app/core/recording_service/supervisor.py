from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from loguru import logger

from app.core.ports.recorder_port import RecorderPort
from app.core.ports.storage_port import StoragePort

# Back-off constants (seconds): 2s, 4s, 8s, 16s, 30s cap
_INITIAL_BACKOFF = 2.0
_MAX_BACKOFF = 30.0
_MAX_RESTARTS = 10  # give up after this many consecutive crashes


class RecorderSupervisor:
    """
    Monitors the recorder adapter and automatically restarts it after a crash.

    Milestone 6 — Reliability & Hardening.

    The supervisor receives crash notifications via the ``notify_crash``
    callback (which the adapter calls through its ``on_crash`` hook).
    It restarts the recorder with exponential back-off and stops retrying
    after ``max_restarts`` consecutive failures.

    Usage::

        supervisor = RecorderSupervisor(recorder, storage, segment_dir)
        # Pass supervisor.notify_crash to the recorder adapter as on_crash=
        adapter = FFmpegRecorderAdapter(..., on_crash=supervisor.notify_crash)
        supervisor.start()
        ...
        supervisor.stop()
    """

    def __init__(
        self,
        recorder: RecorderPort,
        storage: StoragePort,
        segment_dir: Path,
        max_restarts: int = _MAX_RESTARTS,
        on_recording_failed: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._recorder = recorder
        self._storage = storage
        self._segment_dir = segment_dir
        self._max_restarts = max_restarts
        self._on_recording_failed = on_recording_failed

        self._active = False
        self._crash_event = threading.Event()
        self._lock = threading.Lock()
        self._restart_count = 0
        self._supervisor_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin supervision. Call after the recorder has been started."""
        with self._lock:
            self._active = True
            self._restart_count = 0
            self._crash_event.clear()
        self._supervisor_thread = threading.Thread(
            target=self._supervisor_loop,
            daemon=True,
            name="recorder-supervisor",
        )
        self._supervisor_thread.start()
        logger.debug("RecorderSupervisor started.")

    def stop(self) -> None:
        """Stop supervision without restarting the recorder."""
        with self._lock:
            self._active = False
        self._crash_event.set()  # unblock the wait if sleeping
        if self._supervisor_thread is not None:
            self._supervisor_thread.join(timeout=2)
            if self._supervisor_thread.is_alive():
                logger.warning(
                    "RecorderSupervisor: supervisor thread did not stop within 2s."
                )
            self._supervisor_thread = None
        logger.debug("RecorderSupervisor stopped.")

    # ------------------------------------------------------------------
    # Crash notification (called from recorder watchdog thread)
    # ------------------------------------------------------------------

    def notify_crash(self) -> None:
        """Called by the recorder adapter when FFmpeg exits or stalls."""
        logger.warning("RecorderSupervisor: crash notification received.")
        self._crash_event.set()

    def set_recorder(self, recorder: RecorderPort) -> None:
        """Update the recorder reference when RecordingService replaces it.

        Called via the on_recorder_created callback so the supervisor always
        restarts the correct (possibly composite) recorder after a crash.
        """
        self._recorder = recorder
        logger.debug("RecorderSupervisor: recorder reference updated.")

    # ------------------------------------------------------------------
    # Supervision loop
    # ------------------------------------------------------------------

    def _supervisor_loop(self) -> None:
        backoff = _INITIAL_BACKOFF
        while True:
            # Wait until a crash notification arrives (or supervisor stopped)
            self._crash_event.wait()
            self._crash_event.clear()

            with self._lock:
                if not self._active:
                    logger.debug("RecorderSupervisor: supervisor deactivated, exiting.")
                    break

                self._restart_count += 1
                count = self._restart_count
                if count > self._max_restarts:
                    logger.critical(
                        "RecorderSupervisor: reached max restarts ({}). "
                        "Recording will not restart automatically.",
                        self._max_restarts,
                    )
                    self._active = False
                    if self._on_recording_failed is not None:
                        try:
                            self._on_recording_failed(
                                f"La grabación se detuvo definitivamente tras "
                                f"{self._max_restarts} reinicios fallidos."
                            )
                        except Exception:  # noqa: BLE001
                            logger.debug("on_recording_failed callback raised.")
                    break

            logger.warning(
                "RecorderSupervisor: restarting recorder (attempt {}/{}) in {:.0f}s …",
                count,
                self._max_restarts,
                backoff,
            )
            # Sleep with back-off (interruptible by stop())
            deadline = time.monotonic() + backoff
            while time.monotonic() < deadline:
                if not self._active:
                    return
                time.sleep(0.5)

            # Attempt restart — re-check active under the lock right before
            # start() to close the window where MonitorWorker.stop() joins this
            # thread with a short timeout and then calls recorder.stop() while
            # we are about to call recorder.start().
            try:
                with self._lock:
                    if not self._active:
                        return
                if self._recorder.is_running():
                    self._recorder.stop()
                self._storage.ensure_directory(self._segment_dir)
                self._recorder.start(output_dir=self._segment_dir)
                logger.info(
                    "RecorderSupervisor: recorder restarted successfully (attempt {}).",
                    count,
                )
                # On success, reset back-off AND the consecutive-crash counter
                # so a future crash doesn't inherit the debt from past crashes.
                backoff = _INITIAL_BACKOFF
                with self._lock:
                    self._restart_count = 0
            except Exception:  # noqa: BLE001
                logger.exception(
                    "RecorderSupervisor: restart attempt {} failed.",
                    count,
                )
                backoff = min(backoff * 2, _MAX_BACKOFF)
                # Trigger the next cycle immediately with the new back-off
                self._crash_event.set()
