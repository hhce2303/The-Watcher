"""Runtime lifecycle — mode resolution + headless daemon/sidecar (ADR-0010).

Edge cases the ADR calls out for F1: crash-free start/stop, respawn guard when
the pipe cannot bind, sidecar shutdown via stdin (TD-3), and a clean teardown
that stops the recording stack (no orphan ffmpeg).
"""
from __future__ import annotations

import io
import threading
import time

from app.runtime.headless import EXIT_OK, EXIT_PIPE_BIND_FAILED, HeadlessRuntime
from app.runtime.mode import DAEMON, QML, SIDECAR, resolve_mode


# ── Mode resolution ───────────────────────────────────────────────────

def test_resolve_mode_daemon():
    assert resolve_mode(["app", "--daemon"]) == DAEMON


def test_resolve_mode_sidecar():
    assert resolve_mode(["app", "--sidecar"]) == SIDECAR


def test_resolve_mode_default_qml():
    assert resolve_mode(["app"]) == QML


def test_resolve_mode_daemon_wins_over_sidecar():
    assert resolve_mode(["app", "--sidecar", "--daemon"]) == DAEMON


# ── Fakes ─────────────────────────────────────────────────────────────

class FakeApi:
    def __init__(self):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakePipe:
    def __init__(self, bound=True, raise_on_start=False, name="pipe"):
        self._bound = bound
        self._raise = raise_on_start
        self.pipe_name = name
        self.started = False
        self.stopped = False

    def start(self):
        if self._raise:
            raise RuntimeError("pywin32 missing")
        self.started = True

    def stop(self):
        self.stopped = True

    def is_bound(self):
        return self._bound


def _runtime(api, pipe, on_stop=None):
    # install_signals=False: tests run off the main thread.
    return HeadlessRuntime(api, pipe, on_stop=on_stop, install_signals=False)


# ── Daemon ────────────────────────────────────────────────────────────

def test_daemon_starts_and_stops_cleanly():
    api, pipe = FakeApi(), FakePipe()
    stopped = []
    rt = _runtime(api, pipe, on_stop=lambda: stopped.append(True))

    result = {}
    t = threading.Thread(target=lambda: result.setdefault("code", rt.serve_daemon()))
    t.start()
    # Wait until it is serving, then request stop.
    deadline = time.monotonic() + 3
    while not pipe.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pipe.started and api.started
    rt.request_stop()
    t.join(timeout=3)
    assert not t.is_alive()
    assert result["code"] == EXIT_OK
    assert pipe.stopped and api.stopped and stopped == [True]


def test_pipe_bind_failure_returns_guard_code():
    api, pipe = FakeApi(), FakePipe(bound=False)
    rt = _runtime(api, pipe)
    assert rt.serve_daemon() == EXIT_PIPE_BIND_FAILED
    assert api.stopped  # cleaned up
    assert pipe.stopped


def test_pipe_start_exception_returns_guard_code():
    api, pipe = FakeApi(), FakePipe(raise_on_start=True)
    rt = _runtime(api, pipe)
    assert rt.serve_daemon() == EXIT_PIPE_BIND_FAILED


# ── Sidecar (stdin shutdown — TD-3) ───────────────────────────────────

def test_sidecar_stops_on_stdin_shutdown_command():
    api, pipe = FakeApi(), FakePipe()
    orphan_guard = []
    rt = _runtime(api, pipe, on_stop=lambda: orphan_guard.append("stopped"))
    stdin = io.StringIO("shutdown\n")
    code = rt.serve_sidecar(stdin=stdin)
    assert code == EXIT_OK
    # Teardown stopped the recording stack → no orphan ffmpeg (TD-3).
    assert orphan_guard == ["stopped"]
    assert pipe.stopped and api.stopped


def test_sidecar_stops_on_stdin_eof():
    api, pipe = FakeApi(), FakePipe()
    rt = _runtime(api, pipe)
    stdin = io.StringIO("")  # immediate EOF
    assert rt.serve_sidecar(stdin=stdin) == EXIT_OK
    assert pipe.stopped


def test_sidecar_ignores_unrelated_stdin_then_shuts_down():
    api, pipe = FakeApi(), FakePipe()
    rt = _runtime(api, pipe)
    stdin = io.StringIO("ping\nstatus\nshutdown\n")
    assert rt.serve_sidecar(stdin=stdin) == EXIT_OK


def test_teardown_is_idempotent():
    api, pipe = FakeApi(), FakePipe()
    calls = []
    rt = _runtime(api, pipe, on_stop=lambda: calls.append(1))
    stdin = io.StringIO("")
    rt.serve_sidecar(stdin=stdin)
    rt._teardown()  # second call must be a no-op
    assert calls == [1]
