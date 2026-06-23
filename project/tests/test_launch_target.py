"""Tests for the shared launch-target resolution (frozen vs source)."""
from __future__ import annotations

import sys


def test_launch_argv_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    from app.infrastructure.launch_target import launch_argv
    assert launch_argv() == [sys.executable, "-m", "app.main"]


def test_launch_argv_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    from app.infrastructure.launch_target import launch_argv
    assert launch_argv() == [sys.executable]


def test_command_string_source_includes_module(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    from app.infrastructure.launch_target import launch_command_string
    cmd = launch_command_string()
    assert cmd.endswith("-m app.main")
    assert "app.main" in cmd


def test_command_string_quotes_paths_with_spaces(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\The Watcher\watcher.exe")
    from app.infrastructure.launch_target import launch_command_string
    # exe path has spaces → must be quoted as a single token
    assert launch_command_string() == '"C:\\Program Files\\The Watcher\\watcher.exe"'


def test_command_string_no_quotes_when_no_spaces(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Watcher\watcher.exe")
    from app.infrastructure.launch_target import launch_command_string
    assert launch_command_string() == r"C:\Watcher\watcher.exe"


def test_relaunch_argv_delegates_to_launch_target(monkeypatch):
    # relaunch._relaunch_argv must now produce the same thing as launch_argv.
    monkeypatch.delattr(sys, "frozen", raising=False)
    from app.infrastructure.relaunch import _relaunch_argv
    from app.infrastructure.launch_target import launch_argv
    assert _relaunch_argv() == launch_argv()
