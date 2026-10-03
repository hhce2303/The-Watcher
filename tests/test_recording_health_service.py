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


class FakeLiveness:
    """Duck-typed background_services entry (e.g. LiveInferenceService)."""

    def __init__(self, alive: bool = True) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class TestBackgroundServiceLiveness:
    """A3: RecordingHealthService also watches background threads (e.g.
    live-inference) that have no FFmpeg process to poll — a dead one used to
    be invisible (raw capture keeps running fine) unless someone read logs."""

    def test_dead_background_service_marks_degraded(self) -> None:
        svc = FakeRecordingService({0: WorkerHealth.RECORDING.name})
        dead = FakeLiveness(alive=False)
        health = RecordingHealthService(
            recording_service=svc,
            poll_interval_seconds=30.0,
            background_services={"live-inference": dead},
        )
        degraded_calls: list[dict] = []
        health.set_callbacks(on_degraded=degraded_calls.append)

        health._check()

        assert len(degraded_calls) == 1

    def test_background_service_recovery_fires_on_recovered(self) -> None:
        svc = FakeRecordingService({0: WorkerHealth.RECORDING.name})
        live = FakeLiveness(alive=False)
        health = RecordingHealthService(
            recording_service=svc,
            poll_interval_seconds=30.0,
            background_services={"live-inference": live},
        )
        recovered_calls: list[None] = []
        health.set_callbacks(on_recovered=lambda: recovered_calls.append(None))

        health._check()
        assert recovered_calls == []

        live._alive = True
        health._check()
        assert len(recovered_calls) == 1

    def test_healthy_ffmpeg_workers_unaffected_by_healthy_background(self) -> None:
        svc = FakeRecordingService({0: WorkerHealth.RECORDING.name})
        live = FakeLiveness(alive=True)
        health = RecordingHealthService(
            recording_service=svc,
            poll_interval_seconds=30.0,
            background_services={"live-inference": live},
        )
        degraded_calls: list[dict] = []
        health.set_callbacks(on_degraded=degraded_calls.append)

        health._check()

        assert degraded_calls == []


class TestHangTimeout:
    """A4: after the operator-confirmed design, a background service dead for
    hang_grace_seconds straight fires on_hang_timeout exactly once (main.py
    wires this to a hard process exit so the Scheduled Task watchdog revives
    a clean process — this service only detects, never restarts anything)."""

    def test_fires_once_after_grace_period_then_stays_quiet(self) -> None:
        svc = FakeRecordingService({0: WorkerHealth.RECORDING.name})
        dead = FakeLiveness(alive=False)
        hang_calls: list[list[str]] = []
        health = RecordingHealthService(
            recording_service=svc,
            poll_interval_seconds=30.0,
            background_services={"live-inference": dead},
            on_hang_timeout=hang_calls.append,
            hang_grace_seconds=90.0,  # 3 polls @ 30s
        )

        health._check()  # poll 1
        assert hang_calls == []
        health._check()  # poll 2
        assert hang_calls == []
        health._check()  # poll 3 — grace reached
        assert hang_calls == [["live-inference"]]
        health._check()  # poll 4 — must not fire again
        assert len(hang_calls) == 1

    def test_resets_and_can_fire_again_after_a_fresh_death(self) -> None:
        svc = FakeRecordingService({0: WorkerHealth.RECORDING.name})
        live = FakeLiveness(alive=False)
        hang_calls: list[list[str]] = []
        health = RecordingHealthService(
            recording_service=svc,
            poll_interval_seconds=30.0,
            background_services={"live-inference": live},
            on_hang_timeout=hang_calls.append,
            hang_grace_seconds=60.0,  # 2 polls @ 30s
        )

        health._check()
        health._check()
        assert len(hang_calls) == 1

        live._alive = True
        health._check()  # recovers — clears the hang-timeout latch

        live._alive = False
        health._check()
        health._check()
        assert len(hang_calls) == 2

    def test_no_grace_period_configured_never_fires(self) -> None:
        svc = FakeRecordingService({0: WorkerHealth.RECORDING.name})
        dead = FakeLiveness(alive=False)
        hang_calls: list[list[str]] = []
        health = RecordingHealthService(
            recording_service=svc,
            poll_interval_seconds=30.0,
            background_services={"live-inference": dead},
            on_hang_timeout=hang_calls.append,
            # hang_grace_seconds omitted — feature opt-in only.
        )

        for _ in range(10):
            health._check()

        assert hang_calls == []

    def test_healthy_service_never_fires_hang_timeout(self) -> None:
        svc = FakeRecordingService({0: WorkerHealth.RECORDING.name})
        live = FakeLiveness(alive=True)
        hang_calls: list[list[str]] = []
        health = RecordingHealthService(
            recording_service=svc,
            poll_interval_seconds=30.0,
            background_services={"live-inference": live},
            on_hang_timeout=hang_calls.append,
            hang_grace_seconds=30.0,
        )

        for _ in range(5):
            health._check()

        assert hang_calls == []
