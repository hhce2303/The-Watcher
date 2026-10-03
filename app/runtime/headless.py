"""HeadlessRuntime - keep the daemon alive until asked to stop, then tear down once.

Rewritten for this repo: the monorepo version was coupled to ``ApiLayer`` and the
named-pipe IPC server (bind failure -> exit code 2).  Only the lifecycle logic
survives: signal handlers, a stop request, and an idempotent teardown that stops
the recording stack so no ffmpeg is orphaned.

Stop sources: SIGINT/SIGTERM, ``request_stop()``, or the ``daemon.stop`` file
written by ``daemon_root stop``.  The caller (``daemon_root.run_daemon``) removes
a stop file left over from a previous run *before* serving, so it cannot kill a
fresh daemon.
"""
from __future__ import annotations

import signal
import threading
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from app.runtime import instance

EXIT_OK = 0


class HeadlessRuntime:
    def __init__(
        self,
        state_dir: Path,
        *,
        on_stop: Optional[Callable[[], None]] = None,
        on_tick: Optional[Callable[[], None]] = None,
        install_signals: bool = True,
        poll_seconds: float = 1.0,
    ) -> None:
        self._state_dir = Path(state_dir)
        self._on_stop = on_stop
        self._on_tick = on_tick
        self._install_signals = install_signals
        self._poll = poll_seconds
        self._stop = threading.Event()
        self._stopped = False

    def request_stop(self) -> None:
        self._stop.set()

    def stop_requested(self) -> bool:
        return self._stop.is_set()

    def serve(self) -> int:
        if self._install_signals:
            self._install_signal_handlers()
        logger.info("[runtime] daemon serving (headless).")
        while not self._stop.is_set():
            if instance.stop_requested(self._state_dir):
                logger.info("[runtime] stop file found - shutting down.")
                instance.clear_stop(self._state_dir)
                self._stop.set()
                break
            if self._on_tick is not None:
                try:
                    self._on_tick()
                except Exception:  # noqa: BLE001 - a status hiccup must not stop recording
                    logger.exception("[runtime] tick failed")
            self._stop.wait(self._poll)
        self._teardown()
        return EXIT_OK

    def _teardown(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        logger.info("[runtime] shutting down.")
        if self._on_stop is not None:
            try:
                self._on_stop()
            except Exception:  # noqa: BLE001
                logger.exception("[runtime] on_stop failed")

    def _install_signal_handlers(self) -> None:
        def _handler(_signum, _frame) -> None:
            self._stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass  # not the main thread / unsupported
