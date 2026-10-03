"""ScreeninfoMonitorAdapter — wraps the third-party screeninfo library.

Covers the three real branches: missing dependency (ImportError), successful
enumeration (sort order + sequential index assignment), and enumeration
failure (broad except, degrades to an empty list rather than crashing the
5-second MonitorDetectionService poll loop).
"""
from __future__ import annotations

import sys
from unittest.mock import patch

from app.adapters.monitor.screeninfo_adapter import ScreeninfoMonitorAdapter


class _FakeMonitor:
    def __init__(self, name, width, height, x, y, is_primary=False):
        self.name = name
        self.width = width
        self.height = height
        self.x = x
        self.y = y
        self.is_primary = is_primary


class TestScreeninfoMonitorAdapterMissingDependency:
    def test_returns_empty_list_when_screeninfo_not_installed(self) -> None:
        with patch.dict(sys.modules, {"screeninfo": None}):
            monitors = ScreeninfoMonitorAdapter().list_monitors()
        assert monitors == []


class TestScreeninfoMonitorAdapterEnumeration:
    def test_primary_sorts_first_then_left_to_right(self) -> None:
        raw = [
            _FakeMonitor("\\\\.\\DISPLAY2", 1920, 1080, 1920, 0, is_primary=False),
            _FakeMonitor("\\\\.\\DISPLAY1", 1920, 1080, 0, 0, is_primary=True),
            _FakeMonitor("\\\\.\\DISPLAY3", 1080, 1920, 3840, 0, is_primary=False),
        ]
        with patch("screeninfo.get_monitors", return_value=raw):
            monitors = ScreeninfoMonitorAdapter().list_monitors()

        assert [m.name for m in monitors] == [
            "\\\\.\\DISPLAY1", "\\\\.\\DISPLAY2", "\\\\.\\DISPLAY3",
        ]
        # Sequential position-based index, not the raw list order.
        assert [m.index for m in monitors] == [0, 1, 2]
        assert monitors[0].is_primary is True
        assert monitors[1].is_primary is False and monitors[2].is_primary is False

    def test_missing_name_falls_back_to_unknown(self) -> None:
        raw = [_FakeMonitor(None, 1920, 1080, 0, 0, is_primary=True)]
        with patch("screeninfo.get_monitors", return_value=raw):
            monitors = ScreeninfoMonitorAdapter().list_monitors()
        assert monitors[0].name == "Unknown"

    def test_missing_is_primary_attribute_defaults_false(self) -> None:
        class _BareMonitor:
            def __init__(self):
                self.name = "\\\\.\\DISPLAY1"
                self.width = 1920
                self.height = 1080
                self.x = 0
                self.y = 0
                # no is_primary attribute at all

        with patch("screeninfo.get_monitors", return_value=[_BareMonitor()]):
            monitors = ScreeninfoMonitorAdapter().list_monitors()
        assert monitors[0].is_primary is False


class TestScreeninfoMonitorAdapterEnumerationFailure:
    def test_returns_empty_list_when_get_monitors_raises(self) -> None:
        with patch("screeninfo.get_monitors", side_effect=RuntimeError("boom")):
            monitors = ScreeninfoMonitorAdapter().list_monitors()
        assert monitors == []
