"""daemon_root: composition root, lifecycle and CLI (replaces main.py + runtime/backend.py)."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from app import daemon_root
from app.core.ports.monitor_port import MonitorPort
from app.core.recording_service.models import MonitorInfo
from app.infrastructure.config import Settings
from app.runtime import instance


class FakeMonitorPort(MonitorPort):
    def __init__(self, monitors=None) -> None:
        self.monitors = monitors if monitors is not None else [
            MonitorInfo(name="D1", width=1920, height=1080, x=0, y=0, is_primary=True, index=0),
            MonitorInfo(name="D2", width=1280, height=720, x=1920, y=0, index=1),
        ]

    def list_monitors(self):
        return list(self.monitors)


class FakeLiveView:
    def __init__(self) -> None:
        self.events: list[str] = []

    def start(self):
        self.events.append("start")
        return True

    def stop(self):
        self.events.append("stop")


@pytest.fixture()
def settings(tmp_path) -> Settings:
    s = Settings()
    s.segment_dir = tmp_path / "data" / "segments"
    s.clips_dir = tmp_path / "data" / "clips"
    s.raw_clips_dir = tmp_path / "data" / "clips_raw"
    s.event_clips_dir = tmp_path / "data" / "clips_events"
    s.live_view_enabled = False
    return s


def _build(settings, **kw):
    return daemon_root.build_daemon(settings, monitor_port=kw.pop("monitor_port", FakeMonitorPort()), segment_compiler=None, **kw)


def test_build_wires_one_worker_per_monitor_and_creates_dirs(settings) -> None:
    d = _build(settings)
    assert [w.monitor.index for w in d.backend.workers] == [0, 1]
    assert d.backend.recording_service is not None
    assert d.backend.health_service is not None and d.backend.disk_monitor is not None
    for p in (settings.segment_dir, settings.clips_dir, settings.raw_clips_dir, settings.event_clips_dir):
        assert p.is_dir()
    assert d.live_view is None
    assert d.api.recording.get_recording_state().is_recording is False
    assert [m.index for m in d.api.recording.get_monitors()] == [0, 1]


def test_build_fails_fast_without_monitors(settings) -> None:
    with pytest.raises(daemon_root.NoMonitorsError):
        _build(settings, monitor_port=FakeMonitorPort(monitors=[]))


def test_live_view_receives_the_daemon_api_and_tls_bundle(settings) -> None:
    settings.live_view_enabled = True
    seen = {}

    def factory(s, api, tls):
        seen.update(settings=s, api=api, tls=tls)
        return FakeLiveView()

    d = _build(settings, live_view_factory=factory, tls_factory=lambda s: "tls-material")
    assert seen["api"] is d.api and seen["tls"] == "tls-material"
    assert isinstance(d.live_view, FakeLiveView)


def test_live_view_failure_never_blocks_recording(settings) -> None:
    settings.live_view_enabled = True

    def boom(*_a):
        raise RuntimeError("no tls")

    d = _build(settings, live_view_factory=boom, tls_factory=lambda s: None)
    assert d.live_view is None and d.backend.recording_service is not None


def test_start_stop_lifecycle_order(settings) -> None:
    settings.live_view_enabled = True
    lv = FakeLiveView()
    d = _build(settings, live_view_factory=lambda *_: lv, tls_factory=lambda s: None)
    d.start(start_recording=False, background=False)
    assert lv.events == ["start"]
    assert d.backend.health_service.is_running()
    assert d.detection.is_running()
    d.stop()
    assert lv.events == ["start", "stop"]
    assert not d.backend.health_service.is_running()
    assert not d.detection.is_running()
    d.stop()  # idempotent
    assert lv.events == ["start", "stop"]


def test_hot_plug_adds_a_recording_worker(settings) -> None:
    d = _build(settings)
    extra = MonitorInfo(name="D3", width=800, height=600, x=3200, y=0, index=2)
    d.detection._on_monitor_added(extra)  # noqa: SLF001 - what detection fires on hot-plug
    assert sorted(d.backend.recording_service._workers) == [0, 1, 2]  # noqa: SLF001
    d.detection._on_monitor_removed(extra)  # noqa: SLF001
    assert sorted(d.backend.recording_service._workers) == [0, 1]  # noqa: SLF001


def test_launcher_prefers_scheduled_task_then_falls_back_to_run_key() -> None:
    calls = []
    ok = SimpleNamespace(ensure_registered=lambda: True)
    auto = SimpleNamespace(set_autostart=lambda enabled, launch_args=None: calls.append((enabled, launch_args)))
    assert daemon_root.ensure_launcher(auto, ok) == "task"
    assert calls == [(False, None)]
    calls.clear()
    bad = SimpleNamespace(ensure_registered=lambda: False)
    assert daemon_root.ensure_launcher(auto, bad) == "runkey"
    assert calls == [(True, ["--daemon"])]


def test_run_daemon_serves_until_stop_file_and_reports_status(settings, tmp_path) -> None:
    state = settings.segment_dir.parent
    instance.request_stop(state)  # stale request from a previous run must be ignored
    code = {}
    t = threading.Thread(target=lambda: code.setdefault("c", daemon_root.run_daemon(
        settings, monitor_port=FakeMonitorPort(), segment_compiler=None, start_recording=False,
        install_signals=False, poll_seconds=0.05, register_launcher=False)), daemon=True)
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline and instance.read_status(state) is None:
        time.sleep(0.02)
    status = instance.read_status(state)
    assert status is not None and status["monitors"] == 2 and status["recording"] is False
    assert t.is_alive()
    instance.request_stop(state)
    t.join(5)
    assert code["c"] == 0


def test_run_daemon_exits_zero_when_another_instance_holds_the_lock(settings) -> None:
    state = settings.segment_dir.parent
    state.mkdir(parents=True, exist_ok=True)
    held = instance.InstanceLock(state)
    assert held.acquire()
    try:
        assert daemon_root.run_daemon(settings, monitor_port=FakeMonitorPort(), install_signals=False,
                                      register_launcher=False) == 0
    finally:
        held.release()


def test_run_daemon_exits_nonzero_without_monitors_so_the_watchdog_retries(settings) -> None:
    assert daemon_root.run_daemon(settings, monitor_port=FakeMonitorPort(monitors=[]), install_signals=False,
                                  register_launcher=False) == daemon_root.EXIT_NO_MONITORS


# ── CLI ───────────────────────────────────────────────────────────────

def test_cli_status_and_health_without_daemon(settings, capsys) -> None:
    assert daemon_root.main(["status"], settings=settings) == daemon_root.EXIT_NOT_RUNNING
    assert daemon_root.main(["health"], settings=settings) == 1
    out = capsys.readouterr().out
    assert "not running" in out


def test_cli_health_ok_when_fresh_and_recording(settings, capsys) -> None:
    state = settings.segment_dir.parent
    instance.write_status(state, {"recording": True, "monitors": 2, "live_view": False})
    assert daemon_root.main(["status"], settings=settings) == 0
    assert json.loads(capsys.readouterr().out)["monitors"] == 2
    assert daemon_root.main(["health"], settings=settings) == 0


def test_cli_health_fails_when_status_is_stale_or_not_recording(settings) -> None:
    state = settings.segment_dir.parent
    instance.write_status(state, {"recording": False})
    assert daemon_root.main(["health"], settings=settings) == 1
    instance.write_status(state, {"recording": True})
    s = instance.read_status(state)
    s["updated_at"] -= 600
    (state / instance.STATUS_FILE).write_text(json.dumps(s), encoding="utf-8")
    assert daemon_root.main(["health"], settings=settings) == 1


def test_cli_stop_writes_the_stop_request(settings) -> None:
    state = settings.segment_dir.parent
    assert daemon_root.main(["stop"], settings=settings) == 0
    assert instance.stop_requested(state) is True


def test_cli_rejects_unknown_commands(settings) -> None:
    with pytest.raises(SystemExit) as e:
        daemon_root.main(["frobnicate"], settings=settings)
    assert e.value.code == 2


def test_legacy_daemon_flag_is_an_alias_of_start() -> None:
    assert daemon_root.parse_args(["--daemon"]).command == "start"
    assert daemon_root.parse_args([]).command == "start"
