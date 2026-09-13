"""Startup mode resolution from the command line (ADR-0010).

QML is gone (F3): this process only ever runs headless. The Tauri UI (React)
is a separate process that connects over the named pipe — see
docs/migration/reference-target-architecture.md.
"""
from __future__ import annotations

from typing import Sequence

from app.core.role import OPERATOR

DAEMON = "daemon"
SIDECAR = "sidecar"


def resolve_mode(argv: Sequence[str], role: str = "") -> str:
    """Pick the startup mode from argv (+ the persisted role as a fallback).

    ``--daemon`` → daemon (Operator, decoupled, survives the Tauri window
    closing). ``--sidecar`` → sidecar (IT/Supervisor/unconfigured, stdin
    shutdown — TD-3: Tauri spawns and kills this process with the app).  If
    neither flag is present: the operator role always gets a daemon (it must
    keep recording regardless of who's watching); every other role — including
    unconfigured (``role == ""``, first-run) — gets a sidecar, since only a
    role-driven relaunch needs decoupling and the unconfigured machine needs
    the Tauri wizard's IPC connection to survive the same as any other UI
    session.  ``launch_argv()`` passes an explicit flag for every role-driven
    launch (watchdog/autostart/relaunch), so this fallback mostly covers a
    manual/dev launch. If both flags are present, ``--daemon`` wins.
    """
    args = set(argv or [])
    if "--daemon" in args:
        return DAEMON
    if "--sidecar" in args:
        return SIDECAR
    return DAEMON if role == OPERATOR else SIDECAR
