# Changelog

All notable changes to The Watcher are documented in this file.

## [Unreleased]

### Fixed
- Automatic (AI-detection) event clips now build through the same error-handling/retry path as manual events — a failed build used to fail silently (the exception died inside an unhandled timer thread with no log line at all). See [ADR-0019](docs/architecture/adr/ADR-0019-auto-event-clip-build-coalescing.md).
- Continuous detections (e.g. a person lingering in frame) no longer trigger a full multi-monitor clip re-encode roughly every 30 seconds — up to 8 heavily-overlapping clip builds could pile up for a single visit. Auto-event clip builds are now coalesced to at most one per clip-window duration (configurable via `EVENT_AUTO_BUILD_MIN_INTERVAL_SECONDS`); the event itself is still logged for analytics/timeline at the original cooldown.

## [0.1.0] - 2026-07-10

First versioned release. This lands the full desktop-shell migration (QML/PySide6 → Tauri 2.0 + React), a headless Python backend, the first native Rust engine port, and a batch of clip/export correctness fixes — plus a same-day fix for a recorder-crash regression found in production.

### Added
- New desktop UI built on Tauri 2.0 + React, replacing the old QML/PySide6 interface, with role-gated tabs (Operator/IT/Supervisor) and full parity across roles.
- Headless backend architecture: a single `core/api` facade (typed commands + a thread-safe event bus) that every UI surface — clips, recording, requests, delivery, settings, editor — goes through, instead of talking to adapters directly.
- Authenticated local IPC channel (named pipe, per-user) connecting the desktop shell to the backend, so the app can run as either an always-on Operator daemon or a Supervisor/IT sidecar that stops with the window.
- Native Rust engine for building clips (lossless TS/MP4 remux and concatenation, HEVC support) that automatically falls back to FFmpeg if the Rust build isn't present on a machine.
- OneDrive integration: clips can be shared straight to a OneDrive folder with a link, no manual upload.
- Operator-only live preview: an in-browser MJPEG feed of what's currently recording, with per-monitor snapshots.
- Multi-clip timeline editor with a real multi-clip sequence track and frame-exact cuts (re-encodes at cut points instead of snapping to the nearest keyframe).
- Recording health is now visible in the UI: a "degraded/retrying" notice appears the moment a recorder starts failing, and a "recovered" notice when it stabilizes — previously this only showed up in a log file nobody was watching live.
- Migration documentation covering the Tauri/React and Rust rewrite for future contributors.

### Changed
- Launching the app (`run.ps1` / `run_dev.ps1`) now starts the Tauri shell by default instead of the old QML prototype.
- FFmpeg batch encoding jobs (clip builds, timestamp burn-ins, trims) now share one concurrency-limited path, closing a gap where event-clip builds could spawn an unbounded number of FFmpeg processes at once.

### Fixed
- Exporting a reel from mixed codecs/resolutions is now rejected up front instead of silently producing a corrupted file.
- A clip pick that fails during export now shows up as failed/skipped instead of vanishing without explanation.
- Hourly recording files no longer come out truncated (a few minutes instead of a full hour) after a recorder crash and restart — a leftover in-progress file is now cleaned up automatically on the very next recording segment instead of lingering until the app is fully restarted.
- Hot-plugging a second monitor while another monitor is mid-recording could, in rare cases, delete that monitor's in-progress clip file — the cleanup logic is now scoped so it only ever touches its own monitor's files.
- A "recording recovered" notice could be silently dropped if the recovery happened during app startup, before the notification system had finished wiring up.
- The live-preview server's snapshot/stream endpoints could hang indefinitely on a truncated preview image; fixed to reject the incomplete frame and keep serving.

### Removed
- The QML/PySide6 UI layer and its prototype code are fully removed — Tauri + React is the only interface going forward.
