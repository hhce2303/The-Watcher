"""Single-instance lock, status file and stop request (daemon control plane)."""
from __future__ import annotations

import os
import time

from app.runtime import instance


def test_second_lock_on_same_dir_is_refused(tmp_path) -> None:
    first = instance.InstanceLock(tmp_path)
    second = instance.InstanceLock(tmp_path)
    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_status_roundtrip_and_freshness(tmp_path) -> None:
    assert instance.read_status(tmp_path) is None
    instance.write_status(tmp_path, {"recording": True, "monitors": 2})
    status = instance.read_status(tmp_path)
    assert status["recording"] is True and status["pid"] == os.getpid()
    assert instance.status_age_seconds(status, now=status["updated_at"] + 5) == 5


def test_status_ignores_corrupt_file(tmp_path) -> None:
    (tmp_path / instance.STATUS_FILE).write_text("{not json", encoding="utf-8")
    assert instance.read_status(tmp_path) is None


def test_stop_request_is_one_shot(tmp_path) -> None:
    assert instance.stop_requested(tmp_path) is False
    instance.request_stop(tmp_path)
    assert instance.stop_requested(tmp_path) is True
    instance.clear_stop(tmp_path)
    assert instance.stop_requested(tmp_path) is False


def test_pid_alive_detects_self_and_dead(tmp_path) -> None:
    assert instance.pid_alive(os.getpid()) is True
    assert instance.pid_alive(2 ** 22 + 12345) is False
    assert instance.pid_alive(None) is False
