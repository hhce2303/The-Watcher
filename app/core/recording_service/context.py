from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from typing import Optional

from app.core.recording_service.models import MonitorInfo


class WorkerHealth(Enum):
    """Real-time recording health of a monitor's worker."""

    RECORDING = auto()   # FFmpeg is running
    RECOVERING = auto()  # supervisor is restarting it
    STOPPED = auto()     # not started or permanently failed


class LifecycleState(Enum):
    """Where a monitor sits in the recording pipeline (F0→F5 methodology)."""

    DETECTED = auto()     # seen by detection, pipeline not built yet
    PROVISIONED = auto()  # worker created, not yet started
    CAPTURING = auto()    # recording active
    RECOVERING = auto()   # supervisor restarting after a crash
    RETIRED = auto()      # monitor disconnected / worker stopped


def new_session_id() -> str:
    """A short token that uniquely identifies one provisioning of a monitor.

    Changes on every (re)provision so logs can be split into "before" and
    "after" a supervisor restart.
    """
    return uuid.uuid4().hex[:8]


@dataclass
class MonitorContext:
    """Mutable single source of truth for one monitor's pipeline state.

    Companion to the *frozen* :class:`MonitorInfo`.  Unifies the per-monitor
    flags that previously lived scattered across ``RecordingService``
    (``_selected`` / ``_checkpoint``) and ``BufferManager`` (``_segment_floor``).

    The recording contract is preserved: ``is_active`` (clip selection) never
    starts or stops capture; ``is_recording`` is *derived* from the lifecycle,
    not a control switch.
    """

    info: MonitorInfo
    session_id: str
    lifecycle: LifecycleState = LifecycleState.PROVISIONED
    is_active: bool = False              # selected for event-clip building
    segment_floor: Optional[datetime] = None
    # ── audit counters ────────────────────────────────────────────────
    segments_written: int = 0
    restarts: int = 0

    @property
    def fingerprint(self) -> str:
        return self.info.fingerprint

    @property
    def index(self) -> int:
        return self.info.index

    @property
    def is_recording(self) -> bool:
        """Derived — recording is decoupled from selection (see contract)."""
        return self.lifecycle in (LifecycleState.CAPTURING, LifecycleState.RECOVERING)

    @property
    def mon_tag(self) -> str:
        """Short, log-friendly monitor tag (for ``logger.bind(mon=...)``)."""
        return f"m{self.index}"
