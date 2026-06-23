"""Tests for the operator restart watchdog scheduled task.

The XML construction is the part most likely to be misconfigured (and the part
that can't be exercised on a non-Windows CI), so it is unit-tested directly.
The actual "Task Scheduler restarts after a kill" behaviour is covered by the
manual Windows checklist in the plan, not here.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


class TestBuildTaskXml:
    def _xml(self, monkeypatch):
        # Pin a frozen exe path so the action is deterministic.
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", r"C:\Watcher\watcher.exe")
        from app.infrastructure.scheduled_task import build_task_xml
        return build_task_xml(user="DOMAIN\\op")

    def test_has_restart_on_failure_every_minute(self, monkeypatch):
        xml = self._xml(monkeypatch)
        assert "<RestartOnFailure>" in xml
        assert "<Interval>PT1M</Interval>" in xml

    def test_does_not_start_new_instance(self, monkeypatch):
        xml = self._xml(monkeypatch)
        assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml

    def test_logon_trigger_and_least_privilege(self, monkeypatch):
        xml = self._xml(monkeypatch)
        assert "<LogonTrigger>" in xml
        assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
        assert "<UserId>DOMAIN\\op</UserId>" in xml

    def test_no_execution_time_limit(self, monkeypatch):
        # Always-on: the task action must not be killed for running too long.
        xml = self._xml(monkeypatch)
        assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in xml

    def test_action_uses_launch_target_frozen(self, monkeypatch):
        xml = self._xml(monkeypatch)
        assert "<Command>C:\\Watcher\\watcher.exe</Command>" in xml
        assert "<Arguments>" not in xml  # frozen exe has no args

    def test_action_includes_module_args_in_source_mode(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.setattr(sys, "executable", r"C:\Py\python.exe")
        from app.infrastructure.scheduled_task import build_task_xml
        xml = build_task_xml(user="DOMAIN\\op")
        assert "<Command>C:\\Py\\python.exe</Command>" in xml
        assert "<Arguments>-m app.main</Arguments>" in xml

    def test_xml_escapes_special_chars(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", r"C:\a&b\watcher.exe")
        from app.infrastructure.scheduled_task import build_task_xml
        xml = build_task_xml(user="DOM&IN\\op")
        assert "&amp;" in xml
        assert "C:\\a&b" not in xml  # raw ampersand must be escaped


class TestEnsureRegistered:
    def test_noop_off_windows(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        from app.infrastructure import scheduled_task
        assert scheduled_task.ensure_registered() is False

    def test_fast_path_when_already_registered(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        from app.infrastructure import scheduled_task
        with patch.object(scheduled_task, "is_registered", return_value=True), \
             patch.object(scheduled_task, "_run") as run:
            assert scheduled_task.ensure_registered() is True
            run.assert_not_called()  # no /Create when it already exists

    def test_creates_when_absent_and_returns_true_on_rc0(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        from app.infrastructure import scheduled_task
        ok = MagicMock(returncode=0, stderr="", stdout="")
        with patch.object(scheduled_task, "is_registered", return_value=False), \
             patch.object(scheduled_task, "_run", return_value=ok) as run:
            assert scheduled_task.ensure_registered() is True
            args = run.call_args[0][0]
            assert args[:3] == ["schtasks", "/Create", "/TN"]
            assert "/XML" in args and "/F" in args

    def test_returns_false_when_schtasks_fails(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        from app.infrastructure import scheduled_task
        fail = MagicMock(returncode=1, stderr="Access denied (GPO)", stdout="")
        with patch.object(scheduled_task, "is_registered", return_value=False), \
             patch.object(scheduled_task, "_run", return_value=fail):
            assert scheduled_task.ensure_registered() is False
