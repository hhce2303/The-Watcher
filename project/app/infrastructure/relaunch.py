"""Relaunch the application in a fresh process.

Used after the role is chosen in the first-run wizard (and on any later role
change): the whole backend — recording stack, IT WebSocket server, Supervisor
WebSocket client — is wired only at startup based on the role, so the clean way
to apply a new role is to re-run ``main()`` from scratch.

The replacement is spawned **detached** so it survives the death of the current
process, and the single-instance mutex is released first so the new instance can
acquire it.
"""
from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable

from loguru import logger


def _relaunch_argv() -> list[str]:
    """Command line that re-launches this app.

    Delegates to ``launch_target.launch_argv`` — the single source of truth for
    frozen-vs-source launch, shared with autostart and the restart watchdog.
    """
    from app.infrastructure.launch_target import launch_argv  # noqa: PLC0415
    return launch_argv()


def relaunch_and_exit(
    teardown: Callable[[], None],
    release_lock: Callable[[], None],
) -> None:
    """Tear down the current instance, spawn a fresh one, and exit.

    Order matters:
      1. ``teardown()`` stops services — crucially the FFmpeg recorders — so we
         never leave orphaned processes or two instances recording at once.
      2. ``release_lock()`` frees the single-instance mutex BEFORE the new
         process tries to acquire it.
      3. The replacement is started detached and the current process exits.

    Both callbacks are best-effort: a failure in teardown or lock release must
    not prevent the relaunch (otherwise the app would be stuck recording with
    the wrong role).
    """
    logger.info("Relaunching application to apply role change…")

    try:
        teardown()
    except Exception:  # noqa: BLE001
        logger.exception("relaunch: teardown raised — continuing with relaunch.")

    try:
        release_lock()
    except Exception:  # noqa: BLE001
        logger.exception("relaunch: release_lock raised — continuing with relaunch.")

    argv = _relaunch_argv()
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: the child is not tied to this
    # process's console or lifetime, so it keeps running after we exit.
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )

    try:
        subprocess.Popen(  # noqa: S603 — argv is built from sys.executable, not user input
            argv,
            close_fds=True,
            creationflags=creationflags,
        )
        logger.info("New instance spawned: {}", " ".join(argv))
    except Exception:  # noqa: BLE001
        logger.exception("relaunch: failed to spawn new instance.")

    sys.exit(0)
