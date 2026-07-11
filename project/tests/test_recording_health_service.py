"""RecordingHealthService — degraded/recovered callback wiring.

set_callbacks() lets main.py wire on_degraded/on_recovered onto an
already-constructed service (backend.py builds it before the RecordingApi
facade exists — see build_recording_backend / main.py's post-hoc wiring
block, same pattern as MonitorWorker.set_on_recording_failed).
"""
from __future__ import annotations

from app.core.recording_health.service import RecordingHealthService
from app.core.recording_service.service import WorkerHealth


class FakeRecordingService:
    def __init__(self, workers: dict[int, str]) -> None:
        self._workers = workers

    def health_report(self):
        return {"workers": self._workers}


def test_check_fires_on_degraded_once_then_on_recovered() -> None:
    svc = FakeRecordingService({0: WorkerHealth.RECOVERING.name})
    health = RecordingHealthService(recording_service=svc, poll_interval_seconds=30.0)

    degraded_calls: list[dict] = []
    recovered_calls: list[None] = []
    health.set_callbacks(
        on_degraded=degraded_calls.append,
        on_recovered=lambda: recovered_calls.append(None),
    )

    health._check()
    assert len(degraded_calls) == 1
    assert degraded_calls[0]["workers"] == {0: WorkerHealth.RECOVERING.name}
    assert len(recovered_calls) == 0

    svc._workers = {0: WorkerHealth.RECORDING.name}
    health._check()
    assert len(recovered_calls) == 1
    assert len(degraded_calls) == 1  # no extra degraded call once healthy


def test_no_callbacks_wired_is_a_silent_noop() -> None:
    svc = FakeRecordingService({0: WorkerHealth.STOPPED.name})
    health = RecordingHealthService(recording_service=svc, poll_interval_seconds=30.0)
    health._check()  # must not raise even with on_degraded/on_recovered unset
