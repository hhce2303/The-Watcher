# watcher_h264_encoder (SPIKE — not production)

Feasibility prototype for a Rust-native H.264 **encode** step, evaluated as a
possible replacement for the `libx264` encode inside `EditorExportPort`'s
re-encode path (`app/adapters/ffmpeg/editor_export_adapter.py::_reencode_trim`).
Mirrors the PyO3 + maturin shape of `native/watcher_segments/` (ADR-0006), as a
**sibling crate** (not an extension of `watcher_segments`, per the SPIKE doc's
scope decision).

See `docs/migration/SPIKE-editor-export-encoder.md` for the full feasibility
report: what was verified, what surprised us, effort estimate to productionize,
and the two flagged items (patent pass-through, ADR-0002 staleness) that need
human routing.

## Status

**Spike, not started toward production.** No `ENGINE_READY`-style flag exists
in this crate — that pattern is deliberately deferred until/unless this spike
is promoted (see the SPIKE doc's "effort to productionize" section). Nothing in
`editor_export_adapter.py` has been touched.

## Scope

Encodes already-decoded/scaled raw I420 (YUV420P) frames to an H.264 Annex-B
bitstream. Decode, scale/pad/fps-normalize, AAC audio, and MP4 mux stay on the
existing FFmpeg subprocess, unchanged — see `src/lib.rs` module docs for why.

## Build (this repo's dev box has the Rust toolchain + a C toolchain)

```bash
# From this directory:
cargo test              # unit tests + the synthetic-frame round-trip check
cargo build --release   # or: maturin build --release (produces a wheel)
```

There is no `maturin develop` install step documented here because this
box's venv has no `pip`/`uv` for maturin to invoke; the spike's Python smoke
test instead unzips a `maturin build --release` wheel directly into the venv's
`site-packages` (see the SPIKE doc for the exact commands used).
