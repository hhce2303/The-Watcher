"""DaemonApi - the minimal facade the LAN adapters consume.

In the monorepo ``LiveViewLanAdapter`` received the whole ``ApiLayer`` but only
ever called ``api.recording.get_recording_state()`` and
``api.recording.get_monitors()``.  This module is exactly that contract and
nothing else (spec section 4).

Rule: if an adapter needs more, add the method here together with the port it
reads from.  Never grow this into a copy of ``ApiLayer``.

``MonitorView.resolution`` is ``"<w>x<h>"`` written with the multiplication sign
(U+00D7) because ``h264_feed.parse_resolution`` and the browser clients depend
on that shape; a bare ``MonitorInfo`` carries width/height but no ``resolution``
and would silently lose the capture size.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Sequence

from app.core.recording_service.models import MonitorInfo


class RecordingSource(Protocol):
    def is_recording(self) -> bool: ...

    def total_stored_duration_seconds(self) -> float: ...


@dataclass(frozen=True)
class RecordingState:
    is_recording: bool = False
    record_seconds: int = 0


@dataclass(frozen=True)
class MonitorView:
    index: int
    x: int
    y: int
    width: int
    height: int
    name: str
    is_primary: bool

    @property
    def resolution(self) -> str:
        return f"{self.width}\u00d7{self.height}"

    @classmethod
    def from_monitor(cls, m: MonitorInfo) -> "MonitorView":
        return cls(m.index, m.x, m.y, m.width, m.height, m.display_name, m.is_primary)


class RecordingFacade:
    def __init__(
        self,
        recording: Optional[RecordingSource],
        monitors: Callable[[], Sequence[MonitorInfo]],
    ) -> None:
        self._recording = recording
        self._monitors = monitors

    def get_recording_state(self) -> RecordingState:
        rec = self._recording
        if rec is None or not rec.is_recording():
            return RecordingState(False, 0)
        return RecordingState(True, int(rec.total_stored_duration_seconds()))

    def get_monitors(self) -> list[MonitorView]:
        # Polled on every call, so hot-plugged displays show up without wiring.
        return [MonitorView.from_monitor(m) for m in self._monitors()]


class DaemonApi:
    """Replaces ``ApiLayer`` for this repo: only ``.recording`` exists."""

    def __init__(
        self,
        recording: Optional[RecordingSource],
        monitors: Callable[[], Sequence[MonitorInfo]],
    ) -> None:
        self.recording = RecordingFacade(recording, monitors)
