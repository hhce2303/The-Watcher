"""
Regression test for the hot-plug remove_worker() contract.

Bug: MonitorDetectionService always fires _on_monitor_removed with a
MonitorInfo instance (core/monitor_detection/service.py), but
RecordingService.remove_worker used to take an int index. main.py wired the
callback directly (`detection_service._on_monitor_removed =
recording_service.remove_worker`), so on a real disconnect the MonitorInfo
never matched a dict key, worker.stop() was never called, and the orphaned
worker/ffmpeg process kept running (and could collide with a fresh worker
built on reconnect). remove_worker now takes the MonitorInfo directly to
match the callback's declared type.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.core.recording_service.models import MonitorInfo
from app.core.recording_service.service import RecordingService


def _make_monitor(index: int = 0) -> MonitorInfo:
    return MonitorInfo(
        name="\\\\.\\DISPLAY1",
        width=1920,
        height=1080,
        x=0,
        y=0,
        is_primary=True,
        index=index,
    )


def _make_worker(monitor: MonitorInfo) -> MagicMock:
    worker = MagicMock()
    worker.monitor = monitor
    worker.is_running.return_value = True
    return worker


class TestRemoveWorkerAcceptsMonitorInfo:
    def test_remove_worker_stops_and_evicts_worker(self):
        monitor = _make_monitor(index=0)
        worker = _make_worker(monitor)
        service = RecordingService(workers=[worker])

        service.remove_worker(monitor)

        worker.stop.assert_called_once()
        assert 0 not in service._workers

    def test_remove_worker_fires_on_worker_removed_callback(self):
        monitor = _make_monitor(index=0)
        worker = _make_worker(monitor)
        on_removed = MagicMock()
        service = RecordingService(workers=[worker], on_worker_removed=on_removed)

        service.remove_worker(monitor)

        on_removed.assert_called_once_with(monitor)

    def test_remove_worker_unknown_monitor_is_a_noop(self):
        """No worker registered for this index — must not raise."""
        known = _make_monitor(index=0)
        worker = _make_worker(known)
        service = RecordingService(workers=[worker])

        unknown = _make_monitor(index=1)
        service.remove_worker(unknown)

        worker.stop.assert_not_called()
        assert 0 in service._workers

    def test_hotplug_remove_then_readd_leaves_exactly_one_worker(self):
        """End-to-end: disconnect must fully retire the old worker before a
        reconnect provisions a new one — otherwise both stay alive and two
        ffmpeg processes end up running for the same physical monitor."""
        monitor = _make_monitor(index=0)
        old_worker = _make_worker(monitor)
        service = RecordingService(workers=[old_worker])
        service.start()

        service.remove_worker(monitor)
        old_worker.stop.assert_called_once()

        new_worker = _make_worker(monitor)
        service.add_worker(new_worker)

        assert list(service._workers.values()) == [new_worker]
