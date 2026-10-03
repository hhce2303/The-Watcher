"""HeadlessRuntime: wait for signal / stop file, then tear down once, no IPC."""
from __future__ import annotations

import threading
import time

from app.runtime import instance
from app.runtime.headless import EXIT_OK, HeadlessRuntime


def _run_in_thread(rt: HeadlessRuntime) -> dict:
    result: dict = {}
    t = threading.Thread(target=lambda: result.setdefault("code", rt.serve()), daemon=True)
    t.start()
    result["thread"] = t
    return result


def test_request_stop_ends_serve_and_runs_teardown_once(tmp_path) -> None:
    calls: list[str] = []
    rt = HeadlessRuntime(tmp_path, on_stop=lambda: calls.append("stop"), install_signals=False, poll_seconds=0.02)
    res = _run_in_thread(rt)
    time.sleep(0.05)
    rt.request_stop()
    res["thread"].join(2)
    assert res["code"] == EXIT_OK
    assert calls == ["stop"]
    rt._teardown()  # idempotent
    assert calls == ["stop"]


def test_stop_file_triggers_graceful_stop_and_is_cleared(tmp_path) -> None:
    calls: list[str] = []
    rt = HeadlessRuntime(tmp_path, on_stop=lambda: calls.append("stop"), install_signals=False, poll_seconds=0.02)
    res = _run_in_thread(rt)
    instance.request_stop(tmp_path)
    res["thread"].join(2)
    assert res["code"] == EXIT_OK and calls == ["stop"]
    assert instance.stop_requested(tmp_path) is False


def test_teardown_failure_does_not_escape(tmp_path) -> None:
    def boom() -> None:
        raise RuntimeError("x")

    rt = HeadlessRuntime(tmp_path, on_stop=boom, install_signals=False, poll_seconds=0.02)
    rt.request_stop()
    assert rt.serve() == EXIT_OK


def test_periodic_tick_runs_while_serving(tmp_path) -> None:
    ticks: list[int] = []
    rt = HeadlessRuntime(tmp_path, on_tick=lambda: ticks.append(1), install_signals=False, poll_seconds=0.02)
    res = _run_in_thread(rt)
    time.sleep(0.12)
    rt.request_stop()
    res["thread"].join(2)
    assert len(ticks) >= 2
