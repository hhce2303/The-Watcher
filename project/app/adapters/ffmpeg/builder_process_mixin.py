"""Shared executor/process-tracking scaffolding for the FFmpeg clip builders.

``CombinedClipBuilder`` and ``RecordingClipBuilder`` each run a single-worker
``ThreadPoolExecutor`` and track the in-flight FFmpeg process so ``shutdown()``
can kill it fast instead of waiting for the encode to finish. This is the only
piece genuinely common between the two builders — temp-file purge cadence/scope,
retry bookkeeping, and the ffmpeg command itself all differ for reasons specific
to each builder (see their own docstrings), so those stay in each class.
"""
from __future__ import annotations

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

from loguru import logger


class FfmpegBuilderExecutorMixin:
    """Single-worker executor + in-flight-process tracking + a generic shutdown().

    Subclasses must call ``_init_ffmpeg_executor(...)`` from their own
    ``__init__`` before submitting any build to ``self._executor``.
    """

    _log_label: str
    _executor: ThreadPoolExecutor
    _proc_lock: threading.Lock
    _active_proc: Optional[subprocess.Popen]

    def _init_ffmpeg_executor(self, *, thread_name_prefix: str, log_label: str) -> None:
        self._log_label = log_label
        self._proc_lock = threading.Lock()
        self._active_proc = None
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=thread_name_prefix,
        )

    def _process_tracking_callbacks(
        self,
    ) -> "tuple[Callable[[subprocess.Popen], None], Callable[[], None]]":
        """Return (on_started, on_finished) callbacks for run_batched_ffmpeg().

        Both track the in-flight process under _proc_lock so shutdown() can
        kill it immediately instead of waiting for the encode to finish.
        """

        def _on_started(proc: subprocess.Popen) -> None:
            with self._proc_lock:
                self._active_proc = proc

        def _on_finished() -> None:
            with self._proc_lock:
                self._active_proc = None

        return _on_started, _on_finished

    def shutdown(self) -> None:
        """Cancel pending builds and kill the in-flight FFmpeg process, if any."""
        # Cancel pending futures immediately.
        self._executor.shutdown(wait=False, cancel_futures=True)
        # Kill the active FFmpeg process so the background thread unblocks and
        # Python's atexit handler (which joins all executor threads) can finish
        # instead of hanging until the encode completes.
        with self._proc_lock:
            if self._active_proc is not None:
                try:
                    self._active_proc.kill()
                except OSError:
                    pass
                self._active_proc = None
        logger.info("{} Executor shut down.", self._log_label)
