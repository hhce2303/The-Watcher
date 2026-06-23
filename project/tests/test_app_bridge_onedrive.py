"""Tests for the OneDrive delivery slot on AppBridge.

The bridge marshals the share flow off the UI thread; for deterministic tests
we override the thread-spawn helper so the flow runs inline (the queued
``_share_done`` signal then dispatches directly on the same thread).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.adapters.cloud.local_share_adapter import LocalShareAdapter
from app.adapters.ui.app_bridge import AppBridge
from app.core.cloud_share_service import CloudShareService


def _make_bridge(tmp_path, service=None) -> AppBridge:
    detection = MagicMock()
    detection.get_monitors.return_value = []
    bridge = AppBridge(
        recording_service=None,
        event_service=MagicMock(),
        detection_service=detection,
        player_service=MagicMock(),
        clips_dir=tmp_path / "clips",
        user_config_port=None,
        cloud_share_service=service,
    )
    # Run the "background" share inline for determinism.
    bridge._run_share_async = bridge._do_share  # type: ignore[assignment]
    return bridge


class _BoomService:
    def ensure_folder_and_link(self, folder_path: str):
        raise RuntimeError("boom while sharing")


class TestEnsureFolderLink:
    def test_success_sets_linked_state(self, qt_app, tmp_path) -> None:
        svc = CloudShareService(LocalShareAdapter(root=tmp_path / "od"))
        bridge = _make_bridge(tmp_path, svc)

        bridge.ensureFolderLink("SLC/clips-supervisor/2026-06")

        assert bridge.oneDriveState == "linked"
        assert bridge.oneDriveFolder == "SLC/clips-supervisor/2026-06"
        assert bridge.oneDriveLink.startswith("file:")
        assert (tmp_path / "od" / "SLC" / "clips-supervisor" / "2026-06").is_dir()

    def test_empty_path_is_derived_from_config(self, qt_app, tmp_path) -> None:
        svc = CloudShareService(LocalShareAdapter(root=tmp_path / "od"))
        bridge = _make_bridge(tmp_path, svc)

        bridge.ensureFolderLink("")  # no operator wired → <base>/<YYYY-MM>

        assert bridge.oneDriveState == "linked"
        assert bridge.oneDriveFolder.startswith("SLC/clips-supervisor/")

    def test_failure_sets_error_state_and_emits(self, qt_app, tmp_path) -> None:
        bridge = _make_bridge(tmp_path, _BoomService())
        failures: list[str] = []
        bridge.oneDriveFailed.connect(failures.append)

        bridge.ensureFolderLink("a/b")

        assert bridge.oneDriveState == "error"
        assert failures and "boom" in failures[0]

    def test_missing_service_errors_gracefully(self, qt_app, tmp_path) -> None:
        bridge = _make_bridge(tmp_path, service=None)
        bridge.ensureFolderLink("a/b")
        assert bridge.oneDriveState == "error"

    def test_reset_clears_state(self, qt_app, tmp_path) -> None:
        svc = CloudShareService(LocalShareAdapter(root=tmp_path / "od"))
        bridge = _make_bridge(tmp_path, svc)
        bridge.ensureFolderLink("a/b")
        assert bridge.oneDriveState == "linked"

        bridge.resetOneDrive()
        assert bridge.oneDriveState == "idle"
        assert bridge.oneDriveFolder == ""
        assert bridge.oneDriveLink == ""

    def test_copy_to_clipboard_no_crash(self, qt_app, tmp_path) -> None:
        # Under QCoreApplication there is no clipboard; the slot must no-op safely.
        bridge = _make_bridge(tmp_path)
        bridge.copyToClipboard("https://share.example/x")
