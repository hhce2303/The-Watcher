"""Native (Rust) adapters and the segment-compiler engine selector.

The Rust crate ``watcher_segments`` (built via PyO3/maturin) is the default
segment-compilation engine; FFmpeg is the fallback when the ``.pyd`` is absent
or not yet ready.  See docs/editing/adr/ADR-0006-rust-segment-engine.md.
"""
from __future__ import annotations

from app.adapters.native.rust_segment_compiler import (
    RustSegmentCompilerAdapter,
    make_segment_compiler,
    rust_engine_status,
)

__all__ = [
    "RustSegmentCompilerAdapter",
    "make_segment_compiler",
    "rust_engine_status",
]
