"""Rust-backed :class:`SegmentCompilerPort` + engine selector (R-6).

The Rust crate ``watcher_segments`` is compiled to a Python extension
(``.pyd``) via PyO3/maturin (see ``native/watcher_segments/`` and
docs/editing/adr/ADR-0006-rust-segment-engine.md).  This module wraps it and
provides :func:`make_segment_compiler`, which returns the Rust engine when it is
present **and** advertises ``ENGINE_READY = True``, otherwise the FFmpeg fallback.

Selecting Rust only when ``ENGINE_READY`` is true means a half-finished native
build can be present without the app silently using an incomplete engine.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from loguru import logger

from app.core.ports.segment_compiler_port import SegmentCompilerPort


def _load_native():
    """Return the imported ``watcher_segments`` module, or ``None`` if absent."""
    try:
        import watcher_segments  # type: ignore[import-not-found]

        return watcher_segments
    except Exception:  # noqa: BLE001  — ImportError or load-time DLL failure
        return None


def rust_engine_status() -> tuple[bool, bool]:
    """Return ``(present, ready)`` for the native engine.

    *present* — the ``.pyd`` imported.  *ready* — it advertises ``ENGINE_READY``.
    """
    mod = _load_native()
    if mod is None:
        return (False, False)
    return (True, bool(getattr(mod, "ENGINE_READY", False)))


class RustSegmentCompilerAdapter(SegmentCompilerPort):
    """Delegates compilation to the native ``watcher_segments`` extension."""

    def __init__(self) -> None:
        self._mod = _load_native()
        if self._mod is None:
            raise RuntimeError("watcher_segments native engine is not available.")

    @property
    def engine_name(self) -> str:
        return "rust"

    def compile(
        self,
        sources: Sequence[Path],
        output_path: Path,
        in_point_s: Optional[float] = None,
        out_point_s: Optional[float] = None,
    ) -> Path:
        srcs = [str(Path(s)) for s in sources]
        if not srcs:
            raise ValueError("compile() requires at least one source.")
        out = str(Path(output_path))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        result = self._mod.compile_clip(srcs, out, in_point_s, out_point_s)
        return Path(result)


def make_segment_compiler(
    codec: str = "h264", prefer_rust: bool = True
) -> SegmentCompilerPort:
    """Return the segment-compilation engine (Rust default, FFmpeg fallback).

    Imported lazily so the FFmpeg adapter is only constructed on the fallback
    path, and so ``main.py`` can wire this with a single call.
    """
    if prefer_rust:
        present, ready = rust_engine_status()
        if present and ready:
            logger.info("[segcompile] Using native Rust engine.")
            return RustSegmentCompilerAdapter()
        if present and not ready:
            logger.info(
                "[segcompile] Native engine present but not ready (ENGINE_READY=False) "
                "— using FFmpeg fallback."
            )
        else:
            logger.info("[segcompile] Native engine absent — using FFmpeg fallback.")

    from app.adapters.ffmpeg.segment_compiler_adapter import (  # noqa: PLC0415
        FFmpegSegmentCompilerAdapter,
    )

    return FFmpegSegmentCompilerAdapter(codec=codec)
