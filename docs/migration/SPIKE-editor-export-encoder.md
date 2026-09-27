# SPIKE — Rust encoder for `EditorExportPort`'s re-encode path (discardable)

> **Status: feasibility check DONE, go/no-go decision is the user's, not resolved here.**
> The crate builds cleanly, `cargo test` passes (including a real openh264 encode round-trip),
> and a Python round-trip through the compiled `.pyd`-equivalent (`.so` on this Linux dev box)
> also passes. Two items are flagged below for human routing (legal + architecture) and are
> **not** resolved by this spike. Nothing is wired into `editor_export_adapter.py`; no
> `ENGINE_READY`-style flag was added or flipped. See "Findings" below for the full report.

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

## Findings (this pass)

### Crate decision (from the prior research pass — acted on, not re-derived here)

**`openh264` v0.9.8 (crates.io), default `source` feature.** FFI to Cisco's OpenH264 C/C++
library, BSD-2-Clause (wrapper and C core both). The `source` feature statically compiles Cisco's
source at build time via the `cc` crate — no runtime DLL. Ruled out and not reconsidered:
`ffmpeg-next` (libav* DLLs at runtime, TD-4), `x264` crate (GPL-2.0 copyleft), pure-Rust H.264
encoders (too immature, tracked for 2027 re-evaluation).

Scope stays exactly as directed: this crate encodes already-decoded/scaled raw I420 (YUV420P)
frames to an H.264 Annex-B bitstream. Decode, scale/pad/fps-normalize, AAC audio, and MP4 mux all
stay on the existing FFmpeg subprocess in `_reencode_trim`, unchanged.

### Where it lives

`project/native/watcher_h264_encoder/` — a **sibling** crate to `native/watcher_segments/` (not an
extension of it), per the pattern in `howto-port-to-rust.md` step 2 and this doc's own original
pointer ("a sibling crate is expected"). Mirrors `watcher_segments`' shape: PyO3 + maturin,
`crate-type = ["cdylib", "rlib"]` (rlib so the pure logic is `cargo test`-able without a Python
runtime), gitignored `target/`/`Cargo.lock`/`*.so`/`*.pyd`.

### Build verification — did it actually build cleanly?

**Yes, and faster than expected.** On this dev box (Linux, `rustc 1.98.1`, `cargo 1.98.1`, system
`cc`/`gcc 16.2.1`, `maturin 1.15.0`, no prior crates.io cache for `openh264`):

- `cargo check`: 10.7s wall time (cold — fetched `openh264` v0.9.8 + `openh264-sys2` v0.9.8 from
  crates.io, no cache hit). Zero warnings from our code or the direct dependency.
- `cargo build --release` (clean, `cargo clean` first): **13.9s** wall time. This compiles Cisco's
  OpenH264 C/C++ source via the `cc` crate into four static libs (`libopenh264_common.a`,
  `_processing.a`, `_decoder.a`, `_encoder.a`, confirmed present under `target/release/build/…/out/`)
  and links them into `libwatcher_h264_encoder.so` (1.36 MB, no external `.so`/`.dll` dependency —
  confirmed via the linked artifact, not just asserted).
- `cargo test --release`: all 6 tests pass, including `encode_frames_round_trips_synthetic_frames`
  — three synthetic 64×64 I420 frames fed to a real `openh264::encoder::Encoder`, producing a
  non-empty, Annex-B-start-code-prefixed H.264 bitstream.
- `cargo fmt --check` clean; `cargo clippy --release` has **one** residual warning
  (`clippy::useless_conversion` on the `#[pyfunction]`-generated wrapper for a
  `PyResult<Bound<'py, PyBytes>>` return) confirmed to be a false positive — `cargo clippy --fix`
  finds nothing to actually change. Documented inline with `#[allow(...)]` rather than chased
  further; not wired into any CI gate in this repo today (none found for Rust fmt/clippy).
- **Friction found:** the `nasm` binary is not installed on this box. `openh264-sys2`'s build
  script printed `Failed to compile NASM files, not using any assembly.` and transparently fell
  back to portable C/C++ (build still succeeded, tests still passed). This means the SIMD-optimized
  assembly paths are **not** exercised on this box — correctness is unaffected, but production
  encode performance here is a lower bound, not representative of a box with `nasm` installed.
  Worth installing `nasm` before any real perf benchmarking.
- **Windows/MSVC — NOT verified.** This dev box is Linux. openh264-rs's own platform table lists
  `x86_64-pc-windows-msvc` as compiled+tested, but that is a single-sourced claim from the crate's
  own CI, not independently re-verified here. The Watcher ships on Windows — this is a real gap
  before any go decision, not a formality.

### Python round-trip — did it actually work?

**Yes, after fixing one real bug the round-trip caught.** `maturin build --release` produced a
wheel (`target/wheels/watcher_h264_encoder-0.1.0-cp313-cp313-manylinux_2_34_x86_64.whl`). This
venv (`.venv`) has no `pip`/`uv`, so `maturin develop` isn't available here; the wheel was manually
unzipped into `.venv/lib/python3.13/site-packages/` to install it for the smoke test (and removed
again afterward — see "Housekeeping" below).

First attempt: `encode_frames(...)` returned a Python **`list[int]`**, not `bytes`. This is a real,
non-obvious PyO3 default: `Vec<u8>` converts to a Python `list` (one boxed `int` per byte) unless
you explicitly build a `PyBytes`. Fixed by changing the signature to return
`PyResult<Bound<'py, PyBytes>>` via `PyBytes::new_bound`. After the fix: `import
watcher_h264_encoder` loads, `encode_frames(frames, 64, 64)` on 3 synthetic I420 frames returned
193 bytes of proper `bytes` starting with an Annex-B start code, and the negative path (a
malformed 10-byte "frame") correctly raised `ValueError` with a descriptive message instead of
segfaulting or silently corrupting output.

### Surprises vs. the research's on-paper claims

- **Positive:** build time (cold, including compiling Cisco's C/C++ core) was ~14s, not the kind
  of C-toolchain slog that might have been feared for a "not pure Rust" FFI crate.
  `openh264-sys2`'s BSD-2-Clause claim and the "no runtime DLL via the `source` feature" claim both
  checked out empirically (static libs confirmed, `.so` has no external OpenH264 dependency).
- **Negative/friction:** the `Vec<u8>` → `list[int]` PyO3 default (see above) — a production
  adapter that skipped the Python round-trip check and only ran `cargo test` would have shipped a
  broken adapter. This is exactly why the task asked for the Python call, not just `cargo test`.
- **Negative/friction:** no `nasm` on this box → silent fallback to non-SIMD C paths. Not a
  blocker, but a real perf caveat for any future benchmark numbers taken on this box.
- **Unverified, not "negative" but worth being honest about:** the MSVC/Windows build path,
  which is where this ships in production, was not exercised at all in this pass.

### What a parity oracle would need (not built in this pass, per the task's instruction)

Unlike the stream-copy path (`project/tests/test_parity_segment_compiler.py`), there is no oracle
here yet. A future PR would need, at minimum:

- **Visual/quality tolerance**: a checksum-exact match against `libx264 -preset veryfast -crf 18`
  is unrealistic (different encoder, different rate-control internals even at a similar CRF-like
  setting); a perceptual metric (SSIM/VMAF) with an explicit tolerance band is more realistic.
  Openh264's default rate control and quality knobs differ enough from libx264 that the tolerance
  band needs to be chosen deliberately, not assumed.
- **Duration / frame count**: exact match expected (same input frames in, same count out) — this
  is the part that should be a hard equality check, not a tolerance.
- **Container-level checks**: since this crate only does the encode step, the parity target is the
  *raw bitstream* feeding back into the existing FFmpeg mux, not a full MP4 — the oracle should
  compare the re-muxed output end-to-end (decode both with ffprobe, compare frame count / duration /
  resolution / a perceptual metric), not just diff encoder bytes directly.
- **Concat compatibility**: multi-clip reels concatenate normalized parts (see `_target_format` in
  `editor_export_adapter.py`) — the oracle needs at least one multi-clip case, not just single-clip.

### Flagged, not resolved here (per the task's explicit instruction)

1. **Legal: patent pass-through.** The `source` build compiles Cisco's OpenH264 source directly and
   gets **no** MPEG-LA/Cisco patent pass-through, unlike Cisco's separately-downloaded prebuilt
   binary (see openh264.org/BINARY_LICENSE.txt). This is a licensing/patent question for legal
   review — not an engineering decision, and not resolved by this spike either way.
2. **Architecture: ADR-0002 is stale vs. shipped behavior.**
   `docs/architecture/adr/ADR-0002-smart-trim-copy-vs-encode.md:20-27` describes a "smart trim"
   strategy (stream-copy-most + re-encode-only-the-boundary-GOP). What `_reencode_trim` actually
   does today (confirmed by reading `editor_export_adapter.py` lines 184-219 in this pass) is a
   **full-clip re-encode**, every time `reencode=True` is set — which per `main.py`'s
   `_build_player_editor_services` (around lines 445-457) is unconditional for every real editor
   export. ADR-0002 needs reconciliation with shipped behavior; this is unrelated to the crate
   choice and out of scope to fix in this pass.

### Effort estimate to reach the full ADR-0006 production pattern

Rough, in the same spirit as `howto-port-to-rust.md`'s "prerequisites" framing — not a commitment:

- **Parity oracle** (checksum/SSIM tolerance + duration/frame-count + multi-clip concat case,
  designed per "What a parity oracle would need" above): the largest unknown-sized piece. Likely
  multi-day given no perceptual-metric tooling currently in the test suite (would need to add one,
  e.g. an SSIM library or shell out to `ffmpeg`'s own SSIM filter).
- **`EncoderConfig` tuning** (bitrate/profile/level/complexity) to actually match `-preset veryfast
  -crf 18` quality/size characteristics closely enough to pass the oracle: iterative, depends on
  the oracle above existing first.
- **Windows/MSVC build verification**: unverified in this pass (see above) — must happen before any
  go decision, on a real Windows box with the project's actual MSVC toolchain.
- **`ENGINE_READY`-style flag + Python adapter + FFmpeg fallback wiring**: small and mechanical,
  directly mirrors `rust_segment_compiler.py` — half a day once the above is settled.
- **PyInstaller packaging validation**: per `howto-port-to-rust.md` troubleshooting, confirm the
  `.pyd` bundles cleanly (expected clean, since no external DLL, but not yet verified end-to-end
  through `installer/build.ps1`).
- **`nasm` on build machines**: install for representative perf numbers before any performance
  claims are made.

Overall: this pass answers "does it build and round-trip" (yes, on Linux) — turning it into a
production port is comparable in shape to the original `watcher_segments` port, gated on legal
sign-off for the patent question above.

### Housekeeping from this pass

The Python smoke test unzipped the `maturin build --release` wheel directly into this box's shared
`.venv/lib/python3.13/site-packages/` (that venv has no `pip`/`uv`, so `maturin develop` wasn't
available). Those files were removed again after the round-trip check passed — the shared venv is
outside this spike's isolated worktree and was left as found, not committed to, beyond the
transient smoke test.

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
