"""Tests for the role system — enforce_role(), SettingsBridge PIN validation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


# ── enforce_role ──────────────────────────────────────────────────────────────

class TestEnforceRole:
    """enforce_role() applies per-role constraints to user_config in-place."""

    def _make_config(self, **kwargs):
        from app.core.ports.user_config_port import UserConfig
        return UserConfig(**kwargs)

    def _fake_autostart(self, enabled_at_start: bool = False):
        m = MagicMock()
        m.is_enabled = enabled_at_start
        return m

    def test_operator_forces_autorecord(self):
        from app.core.role import enforce_role
        cfg = self._make_config(autorecord=False, role="operator")
        auto = self._fake_autostart()
        enforce_role("operator", cfg, auto)
        assert cfg.autorecord is True

    def test_operator_calls_set_autostart(self):
        from app.core.role import enforce_role
        cfg = self._make_config(role="operator")
        auto = self._fake_autostart()
        enforce_role("operator", cfg, auto)
        auto.set_autostart.assert_called_once_with(True)

    def test_supervisor_forces_autorecord_off(self):
        from app.core.role import enforce_role
        cfg = self._make_config(autorecord=True, role="supervisor")
        auto = self._fake_autostart()
        enforce_role("supervisor", cfg, auto)
        assert cfg.autorecord is False

    def test_supervisor_does_not_touch_autostart(self):
        from app.core.role import enforce_role
        cfg = self._make_config(role="supervisor")
        auto = self._fake_autostart()
        enforce_role("supervisor", cfg, auto)
        auto.set_autostart.assert_not_called()

    def test_it_leaves_autorecord_unchanged(self):
        from app.core.role import enforce_role
        cfg = self._make_config(autorecord=False, role="it")
        auto = self._fake_autostart()
        enforce_role("it", cfg, auto)
        assert cfg.autorecord is False

    def test_it_does_not_touch_autostart(self):
        from app.core.role import enforce_role
        cfg = self._make_config(role="it")
        auto = self._fake_autostart()
        enforce_role("it", cfg, auto)
        auto.set_autostart.assert_not_called()

    def test_empty_role_is_no_op(self):
        from app.core.role import enforce_role
        cfg = self._make_config(autorecord=True, role="")
        auto = self._fake_autostart()
        enforce_role("", cfg, auto)
        assert cfg.autorecord is True
        auto.set_autostart.assert_not_called()


# ── role helpers ──────────────────────────────────────────────────────────────

class TestRoleHelpers:
    def test_role_label(self):
        from app.core.role import role_label
        assert role_label("operator")  == "Operador"
        assert role_label("supervisor") == "Supervisor"
        assert role_label("it")        == "IT"
        assert "Desconocido" in role_label("unknown")

    def test_role_description_not_empty(self):
        from app.core.role import role_description, VALID_ROLES
        for r in VALID_ROLES:
            assert len(role_description(r)) > 10

    def test_valid_roles_set(self):
        from app.core.role import VALID_ROLES, OPERATOR, SUPERVISOR, IT
        assert OPERATOR in VALID_ROLES
        assert SUPERVISOR in VALID_ROLES
        assert IT in VALID_ROLES
        assert "" not in VALID_ROLES


# ── SettingsBridge PIN ────────────────────────────────────────────────────────

class TestSettingsBridgePin:
    """SettingsBridge.unlockIT validates against settings.it_pin."""

    def _make_bridge(self, it_pin="4321"):
        from unittest.mock import MagicMock
        from app.infrastructure.config import Settings

        # Build a minimal Settings-like object without loading .env
        settings = MagicMock(spec=Settings)
        settings.it_pin = it_pin
        settings.clips_dir = "/tmp/clips"
        settings.video_codec = "h264"
        settings.capture_framerate = 30
        settings.output_width = 1920
        settings.output_height = 1080
        settings.segment_duration = 300
        settings.retention_hours = 8
        settings.event_pre_seconds = 120
        settings.event_post_seconds = 120
        settings.event_cooldown_seconds = 30

        port = MagicMock()
        from app.core.ports.user_config_port import UserConfig
        port.load.return_value = UserConfig(role="operator")

        from app.adapters.ui.settings_bridge import SettingsBridge
        bridge = SettingsBridge.__new__(SettingsBridge)
        bridge._port = port
        bridge._settings = settings
        bridge._clips_dir = "/tmp/clips"
        bridge._driver = "auto"
        bridge._codec = "h264"
        bridge._autorecord = True
        bridge._role = "operator"
        bridge._it_unlocked = False
        bridge._restart_state = "idle"
        bridge._restart_cb = None
        return bridge

    def test_correct_pin_unlocks(self):
        bridge = self._make_bridge(it_pin="4321")
        with patch.object(bridge, "roleChanged"):
            result = bridge.unlockIT("4321")
        assert result is True
        assert bridge._it_unlocked is True

    def test_wrong_pin_does_not_unlock(self):
        bridge = self._make_bridge(it_pin="4321")
        result = bridge.unlockIT("0000")
        assert result is False
        assert bridge._it_unlocked is False

    def test_set_role_blocked_without_unlock(self):
        bridge = self._make_bridge()
        bridge._role = "operator"
        bridge._it_unlocked = False
        with patch.object(bridge, "roleChanged"):
            bridge.setRole("it")
        assert bridge._role == "operator"   # unchanged

    def test_set_role_allowed_when_unlocked(self):
        bridge = self._make_bridge()
        bridge._role = "operator"
        bridge._it_unlocked = True
        with patch.object(bridge, "roleChanged"), \
             patch.object(bridge, "_persist"):
            bridge.setRole("it")
        assert bridge._role == "it"

    def test_set_role_allowed_for_first_run(self):
        bridge = self._make_bridge()
        bridge._role = ""
        bridge._it_unlocked = False
        with patch.object(bridge, "roleChanged"), \
             patch.object(bridge, "_persist"):
            bridge.setRole("supervisor")
        assert bridge._role == "supervisor"

    def test_set_role_rejects_invalid(self):
        bridge = self._make_bridge()
        bridge._role = "it"
        with patch.object(bridge, "roleChanged"), \
             patch.object(bridge, "_persist"):
            bridge.setRole("admin")
        assert bridge._role == "it"
