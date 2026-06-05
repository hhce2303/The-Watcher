"""
Tests for DiskSpaceMonitor (Milestone 6 — Reliability & Hardening).
"""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.disk_monitor import DiskSpaceMonitor


def _make_monitor(on_low_disk=None, warn_bytes=2 * 1024 ** 3, stop_bytes=512 * 1024 ** 2):
    return DiskSpaceMonitor(
        segment_dir=Path("segments"),
        on_low_disk=on_low_disk,
        check_interval=9999,  # disable automatic interval — we call _check() directly
        warn_threshold_bytes=warn_bytes,
        stop_threshold_bytes=stop_bytes,
    )


class TestDiskSpaceMonitor:
    def _mock_usage(self, free_bytes):
        mock = MagicMock()
        mock.free = free_bytes
        return mock

    def test_no_callback_when_disk_ok(self):
        callback = MagicMock()
        monitor = _make_monitor(on_low_disk=callback)
        with patch("psutil.disk_usage", return_value=self._mock_usage(5 * 1024 ** 3)):
            monitor._check()
        callback.assert_not_called()

    def test_no_callback_on_warn_threshold(self):
        """Warning is logged but callback is NOT called at warn level."""
        callback = MagicMock()
        monitor = _make_monitor(on_low_disk=callback)
        with patch("psutil.disk_usage", return_value=self._mock_usage(1 * 1024 ** 3)):
            monitor._check()
        callback.assert_not_called()

    def test_callback_fires_at_stop_threshold(self):
        callback = MagicMock()
        monitor = _make_monitor(on_low_disk=callback)
        with patch("psutil.disk_usage", return_value=self._mock_usage(100 * 1024 ** 2)):  # 100 MB
            monitor._check()
        callback.assert_called_once()

    def test_callback_fires_only_once_per_breach(self):
        """on_low_disk should not be called repeatedly while disk stays critical."""
        callback = MagicMock()
        monitor = _make_monitor(on_low_disk=callback)
        low = self._mock_usage(100 * 1024 ** 2)
        with patch("psutil.disk_usage", return_value=low):
            monitor._check()
            monitor._check()
            monitor._check()
        assert callback.call_count == 1

    def test_callback_resets_when_disk_recovers(self):
        """If disk recovers above stop threshold, a new breach should fire callback again."""
        callback = MagicMock()
        monitor = _make_monitor(on_low_disk=callback)

        low = self._mock_usage(100 * 1024 ** 2)
        ok = self._mock_usage(5 * 1024 ** 3)

        with patch("psutil.disk_usage", return_value=low):
            monitor._check()
        assert callback.call_count == 1

        # Recovery (above warn threshold)
        with patch("psutil.disk_usage", return_value=ok):
            monitor._check()

        # New breach
        with patch("psutil.disk_usage", return_value=low):
            monitor._check()
        assert callback.call_count == 2

    def test_start_and_stop(self):
        monitor = _make_monitor()
        monitor.check_interval = 1  # won't matter since we stop immediately
        monitor.start()
        time.sleep(0.1)
        monitor.stop()
        assert monitor._thread is None
