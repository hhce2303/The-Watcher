"""
Tests for RecorderSupervisor (Milestone 6 — Reliability & Hardening).
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.recording_service.supervisor import RecorderSupervisor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_supervisor(recorder=None, storage=None, max_restarts=3):
    recorder = recorder or MagicMock()
    storage = storage or MagicMock()
    return RecorderSupervisor(
        recorder=recorder,
        storage=storage,
        segment_dir=Path("segments"),
        max_restarts=max_restarts,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecorderSupervisorLifecycle:
    def test_start_and_stop_without_crash(self):
        sup = _make_supervisor()
        sup.start()
        time.sleep(0.05)
        sup.stop()
        assert not sup._active

    def test_notify_crash_triggers_restart(self):
        recorder = MagicMock()
        recorder.is_running.return_value = True
        storage = MagicMock()
        sup = RecorderSupervisor(
            recorder=recorder,
            storage=storage,
            segment_dir=Path("segments"),
            max_restarts=3,
        )
        sup.start()
        sup.notify_crash()
        # Give supervisor time to process the event (back-off = 2s, but we patch it)
        time.sleep(3.5)
        sup.stop()
        recorder.stop.assert_called()
        recorder.start.assert_called()

    def test_stop_before_crash_does_not_restart(self):
        recorder = MagicMock()
        storage = MagicMock()
        sup = _make_supervisor(recorder=recorder, storage=storage)
        sup.start()
        sup.stop()
        sup.notify_crash()  # should be ignored — supervisor already stopped
        time.sleep(0.2)
        recorder.start.assert_not_called()


class TestRecorderSupervisorMaxRestarts:
    def test_gives_up_after_max_restarts(self):
        """After max_restarts consecutive failures, supervisor deactivates."""
        recorder = MagicMock()
        recorder.is_running.return_value = False
        # Make every restart raise so the supervisor keeps failing
        recorder.start.side_effect = RuntimeError("simulated crash")
        storage = MagicMock()

        sup = RecorderSupervisor(
            recorder=recorder,
            storage=storage,
            segment_dir=Path("segments"),
            max_restarts=2,
        )
        # Patch _INITIAL_BACKOFF to 0 so the test runs fast
        with patch("app.core.recording_service.supervisor._INITIAL_BACKOFF", 0.01):
            with patch("app.core.recording_service.supervisor._MAX_BACKOFF", 0.05):
                sup.start()
                sup.notify_crash()
                time.sleep(2.0)  # enough for 2 attempts

        sup.stop()
        assert not sup._active
        assert sup._restart_count >= 2
