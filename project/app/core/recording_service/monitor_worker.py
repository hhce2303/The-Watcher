from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Optional

from loguru import logger

from app.core.ports.recorder_port import RecorderPort
from app.core.ports.storage_port import StoragePort
from app.core.recording_service.buffer_manager import BufferManager
from app.core.recording_service.models import MonitorInfo
from app.core.recording_service.supervisor import RecorderSupervisor


class MonitorWorker:
    """
    Self-contained recording unit for a single physical monitor.

    Owns a RecorderPort, BufferManager, and optionally a RecorderSupervisor.
    Always records to its own segment directory — independent of UI selection.

    Segment output: {segment_dir}/

    The UI selection only determines which workers' buffers are queried when
    building a clip.  Workers are never stopped or restarted on selection changes.
    """

    def __init__(
        self,
        monitor: MonitorInfo,
        recorder: RecorderPort,
        buffer_manager: BufferManager,
        storage: StoragePort,
        segment_dir: Path,
        supervisor: Optional[RecorderSupervisor] = None,
    ) -> None:
        self._monitor = monitor
        self._recorder = recorder
        self._buffer = buffer_manager
        self._storage = storage
        self._segment_dir = segment_dir
        self._supervisor = supervisor

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def monitor(self) -> MonitorInfo:
        return self._monitor

    @property
    def buffer(self) -> BufferManager:
        return self._buffer

    @property
    def segment_dir(self) -> Path:
        return self._segment_dir

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start recording and supervision for this monitor."""
        self._storage.ensure_directory(self._segment_dir)
        self._recorder.start(output_dir=self._segment_dir)
        if self._supervisor is not None:
            self._supervisor.start()
        logger.info(
            "MonitorWorker started: {} → {}",
            self._monitor.display_name,
            self._segment_dir,
        )

    def stop(self) -> None:
        """Stop supervision and recorder for this monitor."""
        if self._supervisor is not None:
            self._supervisor.stop()
        # Call stop() unconditionally: the recorder's stop() is idempotent
        # (it checks self._process internally).  Checking is_running() here
        # creates a race where the supervisor starts a new process after the
        # check but before we return, leaving an orphaned FFmpeg process.
        self._recorder.stop()
        logger.info("MonitorWorker stopped: {}", self._monitor.display_name)

    def is_running(self) -> bool:
        return self._recorder.is_running()

    def set_on_recording_failed(self, callback: Callable[[str], None]) -> None:
        """Wire a failure callback into the supervisor (thread-safe, call any time)."""
        if self._supervisor is not None:
            self._supervisor._on_recording_failed = callback  # noqa: SLF001
