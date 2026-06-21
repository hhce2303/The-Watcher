"""Tests for AppBridge NAS browsing: _unc_connect success signalling and the
auth-cache fix (a failed auth must stay retryable, not poison the cache).

We exercise the REAL methods on a bare AppBridge instance (created via
__new__ to skip the heavy service wiring in __init__), patching only the
external boundaries (subprocess / settings).
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _bare_bridge():
    """An AppBridge with no services wired — only NAS-browsing state set."""
    from app.adapters.ui.app_bridge import AppBridge
    b = AppBridge.__new__(AppBridge)
    b._last_list_failed = False
    return b


# ── _unc_connect: returns True/False so the caller can decide whether to cache ──

class TestUncConnect:
    def _patch_settings(self, username="csoperator", password="pw"):
        cfg = SimpleNamespace(nas_username=username, nas_password=password)
        return patch("app.infrastructure.config.get_settings", lambda: cfg)

    def test_returns_true_on_success(self):
        b = _bare_bridge()
        with self._patch_settings(), patch("subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=0, stderr=b"")
            assert b._unc_connect(r"\\SERVER") is True

    def test_returns_false_on_failure(self):
        b = _bare_bridge()
        with self._patch_settings(), patch("subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=2, stderr=b"System error 53")
            assert b._unc_connect(r"\\SERVER") is False

    def test_returns_false_on_timeout(self):
        import subprocess
        b = _bare_bridge()
        with self._patch_settings(), patch("subprocess.run", side_effect=subprocess.TimeoutExpired("net", 5)):
            assert b._unc_connect(r"\\SERVER") is False

    def test_no_credentials_skips_net_use(self):
        b = _bare_bridge()
        with self._patch_settings(username=""), patch("subprocess.run") as run:
            # No username → let the OS use the current token; never shell out.
            assert b._unc_connect(r"\\SERVER") is True
            run.assert_not_called()


# ── listDirectory: failed auth must NOT be cached (Retry must re-auth) ──────────

class TestListDirectoryAuthCache:
    def setup_method(self):
        from app.adapters.ui.app_bridge import AppBridge
        AppBridge._unc_authenticated = set()  # reset shared cache

    def test_failed_auth_not_cached_and_flags_failure(self):
        from app.adapters.ui.app_bridge import AppBridge
        b = _bare_bridge()
        b._unc_connect = lambda server: False  # simulate auth failure
        out = b.listDirectory(r"\\DEADHOST\share")
        assert out == []
        assert r"\\DEADHOST" not in AppBridge._unc_authenticated  # retry can re-auth
        assert b.lastListFailed() is True

    def test_successful_auth_is_cached(self):
        from app.adapters.ui.app_bridge import AppBridge
        b = _bare_bridge()
        b._unc_connect = lambda server: True
        b._list_unc_server = lambda server: []   # bare-server enumeration stub
        b.listDirectory(r"\\LIVEHOST")
        assert r"\\LIVEHOST" in AppBridge._unc_authenticated

    def test_local_dir_lists_entries_without_failure(self):
        b = _bare_bridge()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "clip_a.mp4").write_text("x")
            (Path(tmp) / "sub").mkdir()
            out = b.listDirectory(tmp)
        names = sorted(i["name"] for i in out)
        assert names == ["clip_a.mp4", "sub"]
        assert b.lastListFailed() is False

    def test_missing_local_dir_flags_failure(self):
        b = _bare_bridge()
        out = b.listDirectory(str(Path(tempfile.gettempdir()) / "no_such_dir_xyz_123"))
        assert out == []
        assert b.lastListFailed() is True
