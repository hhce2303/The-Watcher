"""Unit tests for CloudShareService (pure core orchestration).

The service is exercised against an in-memory fake port, so no filesystem or
network is touched — this verifies the search→create→link contract and the
idempotency / normalization / error-propagation behaviour in isolation.
"""
from __future__ import annotations

import pytest

from app.core.cloud_share_service import CloudShareService
from app.core.ports.cloud_share_port import CloudSharePort, ShareResult


class FakeSharePort(CloudSharePort):
    def __init__(self) -> None:
        self.folders: set[str] = set()
        self.link_calls: list[str] = []

    def ensure_folder(self, folder_path: str) -> bool:
        created = folder_path not in self.folders
        self.folders.add(folder_path)
        return created

    def create_share_link(self, folder_path: str) -> str:
        self.link_calls.append(folder_path)
        return f"https://share.example/{folder_path}"

    def web_url(self, folder_path: str) -> str:
        return f"https://drive.example/{folder_path}"


class TestEnsureFolderAndLink:
    def test_creates_when_absent(self) -> None:
        svc = CloudShareService(FakeSharePort())
        res = svc.ensure_folder_and_link("SLC/clips-supervisor/2026-06")
        assert isinstance(res, ShareResult)
        assert res.created is True
        assert res.folder_path == "SLC/clips-supervisor/2026-06"
        assert res.share_link.endswith("2026-06")
        assert res.web_url

    def test_idempotent_when_present(self) -> None:
        svc = CloudShareService(FakeSharePort())
        first = svc.ensure_folder_and_link("a/b")
        second = svc.ensure_folder_and_link("a/b")
        assert first.created is True
        assert second.created is False

    def test_normalizes_messy_path(self) -> None:
        port = FakeSharePort()
        svc = CloudShareService(port)
        res = svc.ensure_folder_and_link("  SLC \\ clips-supervisor / 2026-06 / ")
        assert res.folder_path == "SLC/clips-supervisor/2026-06"
        # The port only ever sees the normalized form.
        assert port.link_calls == ["SLC/clips-supervisor/2026-06"]

    def test_empty_path_raises(self) -> None:
        svc = CloudShareService(FakeSharePort())
        with pytest.raises(ValueError):
            svc.ensure_folder_and_link("   /// ")

    def test_port_error_propagates(self) -> None:
        class Boom(FakeSharePort):
            def ensure_folder(self, folder_path: str) -> bool:
                raise RuntimeError("graph 500")

        svc = CloudShareService(Boom())
        with pytest.raises(RuntimeError, match="graph 500"):
            svc.ensure_folder_and_link("a/b")
