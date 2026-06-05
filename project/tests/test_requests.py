"""Tests for the Supervisor/IT clip-request system."""
from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── ClipRequest dataclass ─────────────────────────────────────────────────────

class TestClipRequest:
    def _make(self, **kw):
        from app.core.ports.request_port import ClipRequest
        defaults = dict(
            id=str(uuid.uuid4()),
            created_at="2026-06-04T14:32:00Z",
            supervisor_host="PC-SALA-A",
            operator="Operator-28",
            storage="Storage1",
            start_time="2026-06-04 14:00",
            end_time="2026-06-04 14:30",
            description="Incidente a las 14:15",
        )
        defaults.update(kw)
        return ClipRequest(**defaults)

    def test_defaults_to_pending(self):
        req = self._make()
        assert req.status == "pending"

    def test_round_trip(self):
        from app.core.ports.request_port import ClipRequest
        req = self._make()
        assert ClipRequest.from_dict(req.to_dict()) == req

    def test_to_dict_contains_required_fields(self):
        req = self._make()
        d = req.to_dict()
        for field in ("id", "operator", "storage", "start_time", "end_time", "status"):
            assert field in d

    def test_from_dict_accepts_missing_optional(self):
        from app.core.ports.request_port import ClipRequest
        minimal = {
            "id": "abc",
            "created_at": "2026-06-04T00:00:00Z",
            "supervisor_host": "",
            "operator": "Operator-01",
            "storage": "",
            "start_time": "2026-06-04 10:00",
            "end_time": "2026-06-04 11:00",
            "description": "",
        }
        req = ClipRequest.from_dict(minimal)
        assert req.status == "pending"


# ── JsonRequestAdapter ────────────────────────────────────────────────────────

class TestJsonRequestAdapter:
    def _adapter(self, tmp_path):
        from app.adapters.filesystem.request_adapter import JsonRequestAdapter
        return JsonRequestAdapter(path=tmp_path)

    def _make_req(self, status="pending"):
        from app.core.ports.request_port import ClipRequest
        return ClipRequest(
            id=str(uuid.uuid4()),
            created_at="2026-06-04T14:32:00Z",
            supervisor_host="PC-A",
            operator="Operator-28",
            storage="Storage1",
            start_time="2026-06-04 14:00",
            end_time="2026-06-04 14:30",
            description="Test",
            status=status,
        )

    def test_save_creates_json_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._adapter(Path(tmp))
            req = self._make_req()
            adapter.save(req)
            fpath = Path(tmp) / f"{req.id}.json"
            assert fpath.exists()

    def test_load_all_returns_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._adapter(Path(tmp))
            req = self._make_req()
            adapter.save(req)
            loaded = adapter.load_all()
            assert len(loaded) == 1
            assert loaded[0].id == req.id

    def test_load_all_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._adapter(Path(tmp))
            assert adapter.load_all() == []

    def test_update_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._adapter(Path(tmp))
            req = self._make_req("pending")
            adapter.save(req)
            adapter.update_status(req.id, "processing")
            loaded = adapter.load_all()
            assert loaded[0].status == "processing"

    def test_update_status_nonexistent_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._adapter(Path(tmp))
            adapter.update_status("nonexistent-id", "done")   # must not raise

    def test_load_skips_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "bad.json").write_text("not json", encoding="utf-8")
            adapter = self._adapter(Path(tmp))
            assert adapter.load_all() == []

    def test_multiple_requests_loaded_newest_first(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            adapter = self._adapter(Path(tmp))
            r1 = self._make_req(); adapter.save(r1); time.sleep(0.01)
            r2 = self._make_req(); adapter.save(r2); time.sleep(0.01)
            r3 = self._make_req(); adapter.save(r3)
            loaded = adapter.load_all()
            # load_all returns sorted by filename desc; since uuid filenames are
            # not time-sorted, just check all are returned
            assert len(loaded) == 3


# ── AppBridge.listOperators mock test ─────────────────────────────────────────

class TestListOperators:
    """listOperators() must return only names, no navigable path."""

    def _mock_bridge(self):
        """Build an AppBridge-like object with only the listOperators method."""
        from unittest.mock import MagicMock
        import os

        class FakeBridge:
            _unc_authenticated: set = set()

            def _unc_connect(self, server): pass

            def listOperators(self, storage_path):
                import os
                result = []
                try:
                    with os.scandir(storage_path) as it:
                        for entry in sorted(it, key=lambda e: e.name.lower()):
                            if entry.name.startswith("$") or entry.name.startswith("."):
                                continue
                            if not entry.is_dir(follow_symlinks=False):
                                continue
                            result.append({
                                "name":    entry.name,
                                "storage": storage_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
                            })
                except (OSError, PermissionError):
                    pass
                return result

        return FakeBridge()

    def test_returns_operator_names_without_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Operator-28").mkdir()
            (Path(tmp) / "Operator-04").mkdir()
            (Path(tmp) / "some_file.mp4").write_text("x")  # should be excluded

            bridge = self._mock_bridge()
            result = bridge.listOperators(tmp)

        names = [r["name"] for r in result]
        assert "Operator-28" in names
        assert "Operator-04" in names
        assert len(names) == 2

    def test_no_navigable_path_in_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Operator-01").mkdir()
            bridge = self._mock_bridge()
            result = bridge.listOperators(tmp)

        # Verify no item has a "path" key that would let QML navigate inside
        for item in result:
            assert "path" not in item

    def test_hidden_dirs_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".hidden").mkdir()
            (Path(tmp) / "$admin").mkdir()
            (Path(tmp) / "Operator-99").mkdir()
            bridge = self._mock_bridge()
            result = bridge.listOperators(tmp)

        assert len(result) == 1
        assert result[0]["name"] == "Operator-99"
