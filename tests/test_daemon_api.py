"""DaemonApi: the minimal facade LiveViewLanAdapter consumes (spec section 4)."""
from __future__ import annotations

from app.adapters.live_view_lan.h264_feed import parse_resolution
from app.core.recording_service.models import MonitorInfo
from app.daemon_api import DaemonApi


class FakeRecording:
    def __init__(self, recording: bool, seconds: float = 0.0) -> None:
        self._recording = recording
        self._seconds = seconds

    def is_recording(self) -> bool:
        return self._recording

    def total_stored_duration_seconds(self) -> float:
        return self._seconds


def _monitors() -> list[MonitorInfo]:
    return [
        MonitorInfo(name="\\\\.\\DISPLAY1", width=1920, height=1080, x=0, y=0, is_primary=True, index=0),
        MonitorInfo(name="\\\\.\\DISPLAY2", width=2560, height=1440, x=1920, y=0, index=1),
    ]


def test_recording_state_reflects_the_service() -> None:
    api = DaemonApi(FakeRecording(True, 42.7), _monitors)
    state = api.recording.get_recording_state()
    assert state.is_recording is True
    assert state.record_seconds == 42


def test_recording_state_is_idle_when_stopped_or_missing() -> None:
    assert DaemonApi(FakeRecording(False, 99), _monitors).recording.get_recording_state().is_recording is False
    assert DaemonApi(None, _monitors).recording.get_recording_state().is_recording is False


def test_monitors_expose_what_the_live_view_adapter_reads() -> None:
    views = DaemonApi(FakeRecording(True), _monitors).recording.get_monitors()
    assert [(m.index, m.x, m.y) for m in views] == [(0, 0, 0), (1, 1920, 0)]
    # LiveViewLanAdapter derives the capture size from `resolution` ("W×H").
    assert views[0].resolution == "1920×1080"
    assert parse_resolution(views[1].resolution) == (2560, 1440)


def test_monitors_follow_hot_plug_because_the_source_is_polled() -> None:
    current = _monitors()
    api = DaemonApi(FakeRecording(True), lambda: current)
    assert len(api.recording.get_monitors()) == 2
    current = current[:1]
    assert len(api.recording.get_monitors()) == 1
