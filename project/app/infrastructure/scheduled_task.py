"""Operator restart watchdog — a Windows Scheduled Task.

The operator station must keep recording 24/7, so the app must come back if its
process dies (Task Manager kill, crash).  Rather than spawn our own guardian
process (which could itself be killed), we let the OS do it: a per-user
Scheduled Task launches The Watcher at logon and **restarts it on failure**.

Why this distinguishes a kill from an intentional exit for free:

    intentional exit → app.exec() returns 0 → sys.exit(0) → task result 0
                       → "RestartOnFailure" does NOT fire (correct)
    kill / crash     → non-zero result
                       → "RestartOnFailure" fires, relaunches within ~1 min

``MultipleInstancesPolicy = IgnoreNew`` plus the app's own single-instance mutex
keep exactly one instance running; the operator's mutex-contention path exits 0
so a benign collision is never read as a crash.

This is a **crash/kill** watchdog, NOT a liveness watchdog — a hung-but-alive
process (frozen Qt loop) exits with no result and the scheduler won't restart it.
FFmpeg stalls are already handled in-process by RecorderSupervisor; full-app
hang detection is tracked as a TODO.

Windows-only; every entry point no-ops (and ``ensure_registered`` returns False)
on other platforms so the caller falls back to the HKCU Run key.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from loguru import logger

from app.infrastructure.launch_target import launch_argv

TASK_NAME = "TheWatcher-OperatorWatchdog"

# CREATE_NO_WINDOW so schtasks never flashes a console on the operator's screen.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _current_user() -> str:
    """``DOMAIN\\user`` for the task principal; falls back to the bare username."""
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    if domain and user:
        return f"{domain}\\{user}"
    if user:
        return user
    import getpass  # noqa: PLC0415
    return getpass.getuser()


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_task_xml(user: str | None = None) -> str:
    """Build the Task Scheduler XML (pure — unit-testable, no I/O).

    Encodes the three load-bearing settings: a logon trigger, restart-on-failure
    every minute, and IgnoreNew (no second instance).  The action is derived
    from ``launch_argv`` so it stays consistent with autostart and relaunch.
    """
    argv = launch_argv()
    command = _xml_escape(argv[0])
    arguments = _xml_escape(" ".join(argv[1:]))
    principal = _xml_escape(user if user is not None else _current_user())
    args_el = f"      <Arguments>{arguments}</Arguments>\n" if arguments else ""
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Description>Keeps The Watcher running for the operator role "
        "(restart on failure).</Description>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <LogonTrigger>\n"
        "      <Enabled>true</Enabled>\n"
        f"      <UserId>{principal}</UserId>\n"
        "    </LogonTrigger>\n"
        "  </Triggers>\n"
        "  <Principals>\n"
        '    <Principal id="Author">\n'
        f"      <UserId>{principal}</UserId>\n"
        "      <LogonType>InteractiveToken</LogonType>\n"
        "      <RunLevel>LeastPrivilege</RunLevel>\n"
        "    </Principal>\n"
        "  </Principals>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <RestartOnFailure>\n"
        "      <Interval>PT1M</Interval>\n"
        "      <Count>999</Count>\n"
        "    </RestartOnFailure>\n"
        "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
        "    <Enabled>true</Enabled>\n"
        "    <Hidden>false</Hidden>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{command}</Command>\n"
        f"{args_el}"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 — args are constant + our own XML path
        args,
        capture_output=True,
        text=True,
        creationflags=_NO_WINDOW,
    )


def is_registered() -> bool:
    """True if our task already exists (a quick ``schtasks /Query``)."""
    if sys.platform != "win32":
        return False
    try:
        return _run(["schtasks", "/Query", "/TN", TASK_NAME]).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def ensure_registered() -> bool:
    """Create the watchdog task if absent; idempotent. True on success.

    Fast path: if the task already exists we assume it is ours and return True
    without rewriting it (avoids a needless subprocess every launch).  Returns
    False on any failure (e.g. group policy blocks Task Scheduler) so the caller
    can fall back to the Run key.
    """
    if sys.platform != "win32":
        return False
    if is_registered():
        return True
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", encoding="utf-16", delete=False
        ) as fh:
            fh.write(build_task_xml())
            tmp = fh.name
        result = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", tmp, "/F"])
        if result.returncode == 0:
            logger.info("Operator watchdog scheduled task registered: {}", TASK_NAME)
            return True
        logger.warning(
            "schtasks /Create failed (rc={}): {}",
            result.returncode,
            (result.stderr or result.stdout or "").strip(),
        )
        return False
    except Exception:  # noqa: BLE001 — never crash startup over the watchdog
        logger.exception("ensure_registered: failed to create scheduled task.")
        return False
    finally:
        if tmp is not None:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass


def remove_task() -> None:
    """Delete the watchdog task (best-effort) — e.g. when leaving operator role."""
    if sys.platform != "win32":
        return
    try:
        if is_registered():
            _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"])
            logger.info("Operator watchdog scheduled task removed: {}", TASK_NAME)
    except Exception:  # noqa: BLE001
        logger.exception("remove_task: failed to delete scheduled task.")
