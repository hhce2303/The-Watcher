"""
Tests for process_guard's batch governance (PoC-2 —
ffmpeg-pipeline-optimization-research.md §4/§8): the MAX_BATCH_FFMPEG
concurrency semaphore and the shared batch Job Object config.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time

import pytest

from app.adapters.ffmpeg import process_guard as pg


@pytest.fixture(autouse=True)
def _restore_batch_semaphore():
    """Tests in this module call configure_batch_concurrency(), which mutates
    module-level globals with no reset — without this, a test's concurrency
    setting leaks into whichever test (in this file or another) runs next."""
    prev_semaphore = pg._batch_semaphore
    prev_size = pg._batch_semaphore_size
    yield
    pg._batch_semaphore = prev_semaphore
    pg._batch_semaphore_size = prev_size


class TestBatchConcurrency:
    def test_batch_slot_caps_peak_concurrency(self):
        pg.configure_batch_concurrency(2)
        concurrent = 0
        peak = 0
        lock = threading.Lock()

        def worker():
            nonlocal concurrent, peak
            with pg.batch_slot():
                with lock:
                    concurrent += 1
                    peak = max(peak, concurrent)
                time.sleep(0.05)
                with lock:
                    concurrent -= 1

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert peak <= 2

    def test_configure_batch_concurrency_one_fully_serializes(self):
        pg.configure_batch_concurrency(1)
        concurrent = 0
        peak = 0
        lock = threading.Lock()

        def worker():
            nonlocal concurrent, peak
            with pg.batch_slot():
                with lock:
                    concurrent += 1
                    peak = max(peak, concurrent)
                time.sleep(0.03)
                with lock:
                    concurrent -= 1

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert peak == 1

    def test_configure_batch_concurrency_clamps_below_one(self):
        pg.configure_batch_concurrency(0)
        assert pg._batch_semaphore_size == 1
        pg.configure_batch_concurrency(-5)
        assert pg._batch_semaphore_size == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object governance is Windows-only")
class TestBatchGovernanceConfig:
    def test_weight_is_clamped_to_1_9(self):
        pg.configure_batch_governance(weight=99)
        assert pg._batch_weight == 9
        pg.configure_batch_governance(weight=0)
        assert pg._batch_weight == 1
        pg.configure_batch_governance(weight=5)
        assert pg._batch_weight == 5

    def test_memory_and_cpu_cap_clamped_non_negative(self):
        pg.configure_batch_governance(memory_limit_mb=-5, cpu_hard_cap_percent=-1)
        assert pg._batch_memory_limit_mb == 0
        assert pg._batch_cpu_hard_cap_percent == 0

    def test_cpu_hard_cap_clamped_to_100(self):
        pg.configure_batch_governance(cpu_hard_cap_percent=250)
        assert pg._batch_cpu_hard_cap_percent == 100


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object governance is Windows-only")
class TestAssignToBatchJobRealProcess:
    def test_assign_to_batch_job_on_real_process_does_not_raise(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(0.5)"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            pg.assign_to_batch_job(proc)  # must not raise
        finally:
            proc.wait(timeout=5)

    def test_assign_to_batch_job_tolerates_bad_pid(self):
        from unittest.mock import MagicMock

        fake_proc = MagicMock()  # .pid is an auto-mock, not a real int
        pg.assign_to_batch_job(fake_proc)  # must not raise or crash the interpreter


class TestRunBatchedFfmpeg:
    def test_caps_peak_concurrency(self):
        pg.configure_batch_concurrency(1)
        concurrent = 0
        peak = 0
        lock = threading.Lock()

        def worker():
            nonlocal concurrent, peak

            def on_started(_proc):
                nonlocal concurrent, peak
                with lock:
                    concurrent += 1
                    peak = max(peak, concurrent)

            def on_finished():
                nonlocal concurrent
                with lock:
                    concurrent -= 1

            pg.run_batched_ffmpeg(
                [sys.executable, "-c", "import time; time.sleep(0.05)"],
                label="test",
                on_started=on_started,
                on_finished=on_finished,
            )

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert peak == 1

    def test_returns_completed_process_with_returncode_and_stderr(self):
        result = pg.run_batched_ffmpeg(
            [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
            label="test",
        )
        assert result.returncode == 3
        assert result.stderr == b"boom"

    def test_on_started_and_on_finished_are_called(self):
        started = []
        finished = []
        pg.run_batched_ffmpeg(
            [sys.executable, "-c", "pass"],
            label="test",
            on_started=lambda proc: started.append(proc.pid),
            on_finished=lambda: finished.append(True),
        )
        assert len(started) == 1
        assert finished == [True]

    def test_timeout_kills_process_and_reraises(self):
        with pytest.raises(subprocess.TimeoutExpired):
            pg.run_batched_ffmpeg(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                label="test",
                timeout=0.2,
            )

    def test_on_finished_still_fires_when_timeout_kills_process(self):
        # on_finished runs in the `finally` block — builders rely on it firing
        # even on the timeout path to clear their _active_proc reference.
        finished = []
        with pytest.raises(subprocess.TimeoutExpired):
            pg.run_batched_ffmpeg(
                [sys.executable, "-c", "import time; time.sleep(5)"],
                label="test",
                timeout=0.2,
                on_finished=lambda: finished.append(True),
            )
        assert finished == [True]
