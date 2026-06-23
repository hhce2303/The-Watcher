"""
Unit tests — Fase 0 (R-6): native engine selector + Rust wrapper.

No real ``.pyd`` is built here; the native module is simulated with a fake
module injected into sys.modules to exercise the Rust delegation path.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from app.adapters.ffmpeg.segment_compiler_adapter import FFmpegSegmentCompilerAdapter
from app.adapters.native import rust_segment_compiler as rsc


def _fake_native(ready: bool = True) -> types.ModuleType:
    mod = types.ModuleType("watcher_segments")
    mod.ENGINE_READY = ready  # type: ignore[attr-defined]

    def compile_clip(sources, out, in_s=None, out_s=None):
        return out

    mod.compile_clip = compile_clip  # type: ignore[attr-defined]
    return mod


class TestStatus:
    def test_absent_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "watcher_segments", raising=False)
        # Ensure import fails (no such module on this machine).
        assert rsc.rust_engine_status() == (False, False)

    def test_present_and_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "watcher_segments", _fake_native(ready=True))
        assert rsc.rust_engine_status() == (True, True)

    def test_present_not_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "watcher_segments", _fake_native(ready=False))
        assert rsc.rust_engine_status() == (True, False)


class TestFactory:
    def test_falls_back_to_ffmpeg_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "watcher_segments", raising=False)
        engine = rsc.make_segment_compiler()
        assert isinstance(engine, FFmpegSegmentCompilerAdapter)
        assert engine.engine_name == "ffmpeg"

    def test_prefer_rust_false_uses_ffmpeg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "watcher_segments", _fake_native(ready=True))
        engine = rsc.make_segment_compiler(prefer_rust=False)
        assert engine.engine_name == "ffmpeg"

    def test_not_ready_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "watcher_segments", _fake_native(ready=False))
        engine = rsc.make_segment_compiler()
        assert engine.engine_name == "ffmpeg"

    def test_uses_rust_when_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "watcher_segments", _fake_native(ready=True))
        engine = rsc.make_segment_compiler()
        assert engine.engine_name == "rust"


class TestRustAdapter:
    def test_delegates_to_native(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setitem(sys.modules, "watcher_segments", _fake_native(ready=True))
        adapter = rsc.RustSegmentCompilerAdapter()
        out = tmp_path / "out.mp4"
        result = adapter.compile([tmp_path / "a.mp4"], out)
        assert Path(result) == out
        assert adapter.engine_name == "rust"

    def test_raises_when_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delitem(sys.modules, "watcher_segments", raising=False)
        with pytest.raises(RuntimeError):
            rsc.RustSegmentCompilerAdapter()
