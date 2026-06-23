# watcher_segments (Rust native engine — R-6 / ADR-0006)

Lossless MPEG-TS → MP4 remux / concatenation / keyframe-trim, compiled to a
Python extension (`.pyd`) via [PyO3](https://pyo3.rs/) + [maturin](https://maturin.rs/).
It is the **default** engine behind `SegmentCompilerPort`; FFmpeg is the fallback.

## Status

**Scaffold.** `src/lib.rs` exposes `ENGINE_READY = false`, so the Python selector
(`app/adapters/native/rust_segment_compiler.py`) keeps using the FFmpeg engine.
The implementation (mpeg2ts-reader demux + muxide mux) is pending and must be
built + validated on a machine with the Rust toolchain — this repo's current dev
box has no `cargo`/`rustc`.

## Build (machine with Rust toolchain)

```powershell
# 1. Install Rust (rustup) + MSVC build tools, then maturin into the app venv:
pip install maturin

# 2. From this directory, build the extension into the active venv:
maturin develop --release        # dev: importable immediately
#   or, for packaging:
maturin build --release          # produces a wheel under target/wheels/

# 3. Run the native tests:
cargo test
```

After the implementation is complete and `cargo test` + the Python parity test
(`tests/test_segment_parity.py`, TODO) pass, set `ENGINE_READY = true` in
`src/lib.rs` and rebuild. The selector will then prefer Rust automatically.

## Packaging

`installer/build.ps1` must `maturin build --release` and `pip install` the wheel
into the clean build venv before PyInstaller runs, and `The Watcher.spec` must
bundle the `.pyd`. Because the crate is pure Rust (no external DLLs), no extra
binaries are needed. If the wheel is absent at build time, the app still runs on
the FFmpeg fallback.
