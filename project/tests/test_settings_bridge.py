"""Tests for SettingsBridge read-only config properties exposed to QML.

These back the "externalize all hardcoded values" requirement: QML reads the
NAS root and capture dimensions from SettingsBridge instead of hardcoding them.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _fake_port(**overrides):
    """A UserConfigPort stub whose load() returns a config with sane defaults."""
    cfg = SimpleNamespace(
        clips_dir=overrides.get("clips_dir", ""),
        driver=overrides.get("driver", "auto"),
        codec=overrides.get("codec", "hevc"),
        autorecord=overrides.get("autorecord", False),
        role=overrides.get("role", "it"),
        it_ws_hosts=overrides.get("it_ws_hosts", []),
    )
    return SimpleNamespace(load=lambda: cfg, save=lambda c: None)


def _make_bridge(settings):
    from app.adapters.ui.settings_bridge import SettingsBridge
    return SettingsBridge(_fake_port(), settings)


@pytest.fixture
def settings():
    from app.infrastructure.config import Settings
    s = Settings()
    s.slc_storage_host = r"\\TEST-NAS"
    s.output_width = 2560
    s.output_height = 1440
    s.capture_framerate = 25
    return s


class TestConfigProperties:
    def test_slc_storage_host_from_settings(self, qt_app, settings):
        bridge = _make_bridge(settings)
        assert bridge.slcStorageHost == r"\\TEST-NAS"

    def test_output_width_height(self, qt_app, settings):
        bridge = _make_bridge(settings)
        assert bridge.outputWidth == 2560
        assert bridge.outputHeight == 1440

    def test_capture_framerate_is_string(self, qt_app, settings):
        # Exposed as str for direct QML display.
        bridge = _make_bridge(settings)
        assert bridge.captureFramerate == "25"

    def test_output_resolution_composes_dims(self, qt_app, settings):
        bridge = _make_bridge(settings)
        assert bridge.outputResolution == "2560×1440"

    def test_storage_host_default_when_unset(self, qt_app):
        # The .env default ships a real UNC host, never an empty string.
        from app.infrastructure.config import Settings
        s = Settings()
        assert s.slc_storage_host.startswith("\\\\")
        bridge = _make_bridge(s)
        assert bridge.slcStorageHost == s.slc_storage_host
