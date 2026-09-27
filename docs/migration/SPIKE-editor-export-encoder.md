# SPIKE — Rust encoder for `EditorExportPort`'s re-encode path (discardable)

> **Status: SPIKE, not started.** This branch/worktree exists only to isolate the experiment.
> No crate code has been written yet — the specific Rust encoder crate is being evaluated by a
> separate research task running in parallel. This note exists so a backend engineer can pick up
> the spike with full context once that research lands. If the encoder doesn't pan out, discard
> per the rollback plan below — nothing outside this branch is affected.

## Goal

Replace the FFmpeg **subprocess** call in `_reencode_trim` — the frame-exact trim + resolution/fps
normalization path used when `EditorExportPort` cannot stream-copy — with a pure-Rust (or at least
PyInstaller-clean, no-external-DLL) H.264 encoder crate, following the exact same pattern already
proven for the segment engine ([ADR-0006](../architecture/adr/ADR-0006-rust-segment-engine.md)):

crate → compile to `.pyd` via PyO3 + maturin → `ENGINE_READY`-style activation flag → parity tests
against the existing FFmpeg output as oracle → Python/FFmpeg subprocess kept as automatic fallback.

This is the next port in the [ADR-0012](../architecture/adr/ADR-0012-rust-hexagon-endgame.md)
sequence: `RecorderPort` + `ClipPort` (done — see below) → **`EditorExportPort`** →
`PlayerPort`/`MonitorPort` → `Storage`/`EventStore`/`UserConfig` → `RequestPort` → `CloudSharePort`.

## Scope of the gap (what this spike targets)

`EditorExportPort`'s **stream-copy** path already reuses the Rust segment compiler (no gap there).
The **re-encode** path is the one remaining piece still shelling out to FFmpeg:

- File: `project/app/adapters/ffmpeg/editor_export_adapter.py`
- Function: `_reencode_trim` (roughly lines 184–213 as of this writing, base commit `17ada1d` on
  `main`)
- What it does today: input-side `-ss` trim (frame-exact) + `scale`/`pad`/`fps` normalization via
  an FFmpeg subprocess, `-c:v libx264 -preset veryfast -crf 18 -pix_fmt yuv420p`, plus AAC audio
  passthrough-encode. Output must stay bit-for-bit reproducible enough to concatenate cleanly with
  other normalized clips (see `_target_format` just above it in the same file, which picks the
  common width/height/fps).
- **Not touched by this spike:** `_reencode_trim` and the rest of `editor_export_adapter.py` are
  unmodified on `main` and remain unmodified on this branch too, until/unless the spike is
  deliberately promoted and merged.

## Precedent: how `ClipPort` did this (reuse this pattern, don't reinvent it)

- Crate: `project/native/watcher_segments/` — pure-Rust (`mpeg2ts-reader` + `shiguredo_mp4`, both
  pinned exact versions in `Cargo.toml`), deliberately avoiding external DLLs because those break
  PyInstaller packaging (see `docs/migration/howto-port-to-rust.md`'s troubleshooting section).
- Compiled to a `.pyd` via PyO3 + maturin.
- Loaded by `project/app/adapters/native/rust_segment_compiler.py`, which gates on the crate's
  exported `ENGINE_READY` constant (currently `true` in `project/native/watcher_segments/src/lib.rs`,
  validated end-to-end per that file's own status comment) — if the `.pyd` is missing or
  `ENGINE_READY` is false, the Python/FFmpeg adapter is used instead. Same selector shape to copy
  for the encoder.
- Step-by-step how-to for porting a port this way: `docs/migration/howto-port-to-rust.md`.

## What the (separate, parallel) research task still needs to answer

Not this spike's job — a backend engineer will implement once the finding lands — but flagging so
whoever picks this up knows what's still open:

- Which specific Rust crate (or combination) does H.264 encode with acceptable quality/perf and
  **no external DLL dependency** (openh264 has an external binary-download story worth checking
  carefully; hardware-encode crates may pull in vendor DLLs — both are exactly the kind of footgun
  `howto-port-to-rust.md` warns about for PyInstaller bundling).
- Whether frame-exact trim (today's input-side `-ss`) and the `scale`/`pad`/`fps` normalization
  belong in the same crate or stay composed with a separate pure-Rust decode/filter step.
- Parity bar vs. today's FFmpeg output (visual + duration/frame-count) for the existing test
  fixtures around `editor_export_adapter.py`.

## Rollback plan

Nothing on `main` changes as a result of this spike existing. If the encoder crate doesn't pan out,
or the research task concludes no viable no-DLL crate exists:

1. `git worktree remove .worktrees/editor-export-rust-encoder` (from the main checkout).
2. `git branch -D spike/editor-export-rust-encoder`.
3. Done — `_reencode_trim` was never touched, so there is nothing to revert in `editor_export_adapter.py`
   or anywhere else in `main`.

## Pointers

- ADR-0006 — Rust segment engine (the pattern this spike replicates): `docs/architecture/adr/ADR-0006-rust-segment-engine.md`
- ADR-0012 — Rust hexagon endgame (this spike is the `EditorExportPort` step in that sequence): `docs/architecture/adr/ADR-0012-rust-hexagon-endgame.md`
- How-to — porting a port to Rust via PyO3: `docs/migration/howto-port-to-rust.md`
- Existing Rust crate to mirror the shape of (not to extend — a sibling crate is expected):
  `project/native/watcher_segments/`
- Existing Python selector/adapter to mirror: `project/app/adapters/native/rust_segment_compiler.py`
- File this spike targets (unmodified so far): `project/app/adapters/ffmpeg/editor_export_adapter.py`
  (`_reencode_trim`, `_target_format`)

## Build check (this worktree, no code changes)

`cargo check` on the existing `project/native/watcher_segments` crate was run from this worktree
right after creation, before any spike code was added, purely to confirm the toolchain and existing
crate are in a healthy starting state. See governor's report for the exact result.
