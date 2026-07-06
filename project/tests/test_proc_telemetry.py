"""
Tests for proc_telemetry (PoC-2): the psutil-based CPU/RSS sampler whose
output feeds the ADR-0007 Rust-port gate.
"""
from __future__ import annotations

import subprocess
import sys
import time

from app.infrastructure.proc_telemetry import ProcTelemetry


def _sleeper(seconds: float = 1.0) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


class TestProcTelemetry:
    def test_track_and_snapshot(self):
        proc = _sleeper()
        try:
            telemetry = ProcTelemetry(interval_seconds=1)
            telemetry.track(proc.pid, category="batch", label="test")
            assert telemetry.snapshot() == [
                {"pid": proc.pid, "category": "batch", "label": "test"}
            ]
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_untrack_removes_entry(self):
        proc = _sleeper()
        try:
            telemetry = ProcTelemetry()
            telemetry.track(proc.pid, category="batch", label="test")
            telemetry.untrack(proc.pid)
            assert telemetry.snapshot() == []
        finally:
            proc.kill()
            proc.wait(timeout=5)

    def test_track_swallows_bad_pid_type(self):
        telemetry = ProcTelemetry()
        telemetry.track("not-a-pid", category="batch", label="bad")  # must not raise
        assert telemetry.snapshot() == []

    def test_sample_reports_alive_then_evicts_dead_process(self):
        proc = _sleeper(seconds=2.0)
        telemetry = ProcTelemetry(interval_seconds=1)
        telemetry.track(proc.pid, category="recorder", label="m0")
        telemetry._sample()  # alive — must not raise or evict
        assert len(telemetry.snapshot()) == 1

        proc.kill()
        proc.wait(timeout=5)
        time.sleep(0.2)

        telemetry._sample()  # dead now — evicted on next sample
        assert telemetry.snapshot() == []

    def test_start_stop_thread_lifecycle(self):
        telemetry = ProcTelemetry(interval_seconds=0.2)
        telemetry.start()
        assert telemetry._thread is not None
        telemetry.start()  # idempotent — does not spawn a second thread
        telemetry.stop()
        assert telemetry._thread is None

    def test_set_interval_clamps_to_minimum(self):
        telemetry = ProcTelemetry(interval_seconds=10)
        telemetry.set_interval(0.01)
        assert telemetry._interval == 1.0
