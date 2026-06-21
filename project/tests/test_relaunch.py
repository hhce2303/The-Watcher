"""Tests for the relaunch argv builder (frozen vs source)."""
from __future__ import annotations

import sys


def test_relaunch_argv_source(monkeypatch):
    # Not frozen → re-run the module entry point with the interpreter.
    monkeypatch.delattr(sys, "frozen", raising=False)
    from app.infrastructure.relaunch import _relaunch_argv
    argv = _relaunch_argv()
    assert argv == [sys.executable, "-m", "app.main"]


def test_relaunch_argv_frozen(monkeypatch):
    # Frozen (PyInstaller) → the executable IS the app; run it alone.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    from app.infrastructure.relaunch import _relaunch_argv
    argv = _relaunch_argv()
    assert argv == [sys.executable]
