"""Daemon control plane on disk: single-instance lock, status file, stop request.

There is no IPC pipe in this repo.  ``start`` runs in the foreground; ``stop``,
``status`` and ``health`` talk to it through small files in the state directory
(``<segment_dir parent>``, i.e. ``C:\\WatcherData`` by default).  Files are used
instead of signals because ``os.kill`` on Windows hard-terminates the process
and would orphan the ffmpeg children.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

LOCK_FILE = "daemon.lock"
STATUS_FILE = "daemon-status.json"
STOP_FILE = "daemon.stop"


class InstanceLock:
    """Exclusive, process-lifetime file lock (released by the OS if we die)."""

    def __init__(self, state_dir: Path) -> None:
        self._path = Path(state_dir) / LOCK_FILE
        self._fh = None

    def acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._path, "a+b")
        try:
            if os.name == "nt":
                import msvcrt  # noqa: PLC0415

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            if os.name == "nt":
                import msvcrt  # noqa: PLC0415

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl  # noqa: PLC0415

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def write_status(state_dir: Path, fields: dict[str, Any]) -> None:
    """Atomically publish a status snapshot (pid + timestamp added here)."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {**fields, "pid": os.getpid(), "updated_at": time.time()}
    tmp = state_dir / (STATUS_FILE + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, state_dir / STATUS_FILE)


def read_status(state_dir: Path) -> Optional[dict[str, Any]]:
    try:
        data = json.loads((Path(state_dir) / STATUS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def status_age_seconds(status: dict[str, Any], now: Optional[float] = None) -> float:
    return (time.time() if now is None else now) - float(status.get("updated_at", 0))


def request_stop(state_dir: Path) -> None:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / STOP_FILE).write_text(str(time.time()), encoding="utf-8")


def stop_requested(state_dir: Path) -> bool:
    return (Path(state_dir) / STOP_FILE).exists()


def clear_stop(state_dir: Path) -> None:
    try:
        (Path(state_dir) / STOP_FILE).unlink()
    except FileNotFoundError:
        pass


def pid_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    import psutil  # noqa: PLC0415

    return psutil.pid_exists(int(pid))
