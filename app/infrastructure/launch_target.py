"""Single source of truth for *how to launch The Watcher*.

Three call sites need this and used to compute it independently (and slightly
differently): the HKCU Run-key autostart (``autostart.py``), the role-change
relaunch (``relaunch.py``), and the operator restart watchdog
(``scheduled_task.py``).  Diverging copies are a maintenance trap — the frozen
vs source distinction must agree everywhere — so it lives here once.

  - Frozen (PyInstaller one-file/one-dir): ``sys.executable`` IS the app exe,
    so running it alone starts a new instance.
  - Source: re-run the module entry point with the same interpreter.

No Qt, no I/O — callers pass ``extra_args`` (e.g. ``["--daemon"]``) rather than
this module reading the persisted role itself, since resolve_mode()'s bare
fallback now defaults to daemon for a configured role (C4, ADR-0010): every
role-driven relaunch must pass an explicit flag, or it would headless-launch
instead of relaunching into the UI it used to.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence


def launch_argv(extra_args: Optional[Sequence[str]] = None) -> list[str]:
    """Argument vector that starts a fresh instance (for ``subprocess``)."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        # The console CLI twin (watcherctl.exe) must never become the launcher:
        # it would open a console window on the operator's screen at every logon.
        if exe.stem.lower() == "watcherctl":
            exe = exe.with_name("The Watcher.exe")
        base = [str(exe)]
    else:
        base = [sys.executable, "-m", "app.daemon_root"]
    return base + list(extra_args or [])


def _quote(token: str) -> str:
    """Quote a token if it contains spaces (paths under e.g. 'Program Files')."""
    return f'"{token}"' if " " in token else token


def launch_command_string(extra_args: Optional[Sequence[str]] = None) -> str:
    """Single command line for HKCU Run (REG_SZ) and Task Scheduler (``/TR``).

    Tokens containing spaces are quoted so the OS parses the executable path
    correctly.  Frozen → ``"<exe>" [extra_args]``; source →
    ``"<python>" -m app.daemon_root [extra_args]``.
    """
    return " ".join(_quote(part) for part in launch_argv(extra_args))
