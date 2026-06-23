"""Single source of truth for *how to launch The Watcher*.

Three call sites need this and used to compute it independently (and slightly
differently): the HKCU Run-key autostart (``autostart.py``), the role-change
relaunch (``relaunch.py``), and the new operator restart watchdog
(``scheduled_task.py``).  Diverging copies are a maintenance trap — the frozen
vs source distinction must agree everywhere — so it lives here once.

  - Frozen (PyInstaller one-file/one-dir): ``sys.executable`` IS the app exe,
    so running it alone starts a new instance.
  - Source: re-run the module entry point with the same interpreter.

No Qt, no I/O.
"""
from __future__ import annotations

import sys


def launch_argv() -> list[str]:
    """Argument vector that starts a fresh instance (for ``subprocess``)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "app.main"]


def _quote(token: str) -> str:
    """Quote a token if it contains spaces (paths under e.g. 'Program Files')."""
    return f'"{token}"' if " " in token else token


def launch_command_string() -> str:
    """Single command line for HKCU Run (REG_SZ) and Task Scheduler (``/TR``).

    Tokens containing spaces are quoted so the OS parses the executable path
    correctly.  Frozen → ``"<exe>"``; source → ``"<python>" -m app.main``.
    """
    return " ".join(_quote(part) for part in launch_argv())
