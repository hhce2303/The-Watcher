"""Tests for the per-role capability policy (app/core/policy.py)."""
from __future__ import annotations

import dataclasses

import pytest


class TestPolicyFor:
    def test_operator_is_locked_down(self):
        from app.core.policy import policy_for
        p = policy_for("operator")
        assert p.can_close_window is False
        assert p.can_minimize_window is False
        assert p.can_exit_from_tray is False
        assert p.can_stop_recording is False
        assert p.can_open_settings is False
        assert p.can_change_role is False
        assert p.records is True
        assert p.records_on_launch_forced is True
        assert p.recording_indicator_locked is True
        assert p.watchdog_enabled is True
        assert p.visible_tabs == (0,)

    def test_supervisor(self):
        from app.core.policy import policy_for
        p = policy_for("supervisor")
        assert p.records is False
        assert p.records_on_launch_forced is False
        assert p.watchdog_enabled is False
        assert p.recording_indicator_locked is False
        assert p.can_change_role is False
        assert p.visible_tabs == (1,)

    def test_it(self):
        from app.core.policy import policy_for
        p = policy_for("it")
        assert p.records is True
        assert p.records_on_launch_forced is False  # honours toggle, not forced
        assert p.can_change_role is True
        assert p.watchdog_enabled is False
        assert p.visible_tabs == ()

    def test_unconfigured_is_default(self):
        from app.core.policy import policy_for
        empty = policy_for("")
        unknown = policy_for("nonsense")
        assert empty == unknown
        assert empty.records is False
        assert empty.records_on_launch_forced is False
        assert empty.watchdog_enabled is False
        assert empty.can_change_role is True  # first-run wizard needs it

    def test_only_operator_has_watchdog_and_locked_indicator(self):
        from app.core.policy import policy_for
        for role in ("supervisor", "it", ""):
            p = policy_for(role)
            assert p.watchdog_enabled is False
            assert p.recording_indicator_locked is False
        op = policy_for("operator")
        assert op.watchdog_enabled is True
        assert op.recording_indicator_locked is True


class TestImmutability:
    def test_frozen(self):
        from app.core.policy import policy_for
        p = policy_for("operator")
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.can_close_window = True  # type: ignore[misc]


class TestAsDict:
    def test_camelcase_keys_for_qml(self):
        from app.core.policy import policy_for
        d = policy_for("operator").as_dict()
        assert d["canMinimizeWindow"] is False
        assert d["recordingIndicatorLocked"] is True
        assert d["watchdogEnabled"] is True
        assert d["visibleTabs"] == [0]  # list, not tuple, for QML

    def test_dict_covers_all_capability_fields(self):
        from app.core.policy import policy_for, RolePolicy
        d = policy_for("it").as_dict()
        # one camelCase key per dataclass field
        assert len(d) == len(dataclasses.fields(RolePolicy))

    def test_should_autorecord_formula_matches_role_helper(self):
        # records_on_launch_forced OR (records AND autorecord) must equal the
        # existing should_autorecord_on_launch truth table for every role.
        from app.core.policy import policy_for
        from app.core.role import should_autorecord_on_launch
        for role in ("operator", "supervisor", "it", ""):
            p = policy_for(role)
            for autorecord in (True, False):
                expected = should_autorecord_on_launch(role, autorecord)
                got = p.records_on_launch_forced or (p.records and autorecord)
                assert got is expected, f"{role}/{autorecord}"
