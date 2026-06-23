"""Unit tests for LocalShareAdapter — the active CloudSharePort today.

Folder operations are real (against a tmp_path root), so these verify that the
click → search → create flow actually creates the directory tree and that the
operation is idempotent.
"""
from __future__ import annotations

from app.adapters.cloud.local_share_adapter import LocalShareAdapter


class TestLocalShareAdapter:
    def test_creates_folder_and_parents(self, tmp_path) -> None:
        adapter = LocalShareAdapter(root=tmp_path)
        created = adapter.ensure_folder("SLC/clips-supervisor/2026-06")
        assert created is True
        assert (tmp_path / "SLC" / "clips-supervisor" / "2026-06").is_dir()

    def test_idempotent(self, tmp_path) -> None:
        adapter = LocalShareAdapter(root=tmp_path)
        assert adapter.ensure_folder("a/b") is True
        assert adapter.ensure_folder("a/b") is False
        assert (tmp_path / "a" / "b").is_dir()

    def test_share_link_is_file_uri_to_the_folder(self, tmp_path) -> None:
        adapter = LocalShareAdapter(root=tmp_path)
        adapter.ensure_folder("a/b")
        link = adapter.create_share_link("a/b")
        assert link.startswith("file:")
        assert link.endswith("/b")
        # Local mode: the share link IS the folder location.
        assert link == adapter.web_url("a/b")
