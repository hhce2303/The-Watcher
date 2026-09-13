# The Watcher — Agent Guide

## Product and current architecture

Windows-only screen-recording desktop application. The active stack is **Python 3.13 + FFmpeg headless backend**, **Tauri 2 Rust shell**, and **React/TypeScript** UI. React talks to Python only through a user-scoped authenticated Windows named pipe; preview/video use the `watcher://` protocol. QML/PySide6 were fully removed in F3 — do not recreate them.

Read [docs/spec-kit/README.md](docs/spec-kit/README.md) before substantial work. It records the product, live contracts, operational constraints, source precedence, and known gaps. Code and tests win over historical migration documents when they conflict.

## Layout and boundaries

```text
project/app/core/       domain logic and ABC ports; no FFmpeg/filesystem/Windows/UI imports
project/app/adapters/   FFmpeg, filesystem, SQLite, monitor, ML, cloud, WS, IPC, native adapters
project/app/core/api/   only input port: ApiLayer + specialized APIs + DTOs + EventBus
project/app/main.py     composition root / concrete DI only
project/app/runtime/    backend builder and daemon/sidecar lifecycle
src-tauri/              named-pipe client, tray/policy, watcher:// media protocol
src/                    React UI; hooks/store consume src/lib/ipc.ts and typed events
project/native/         optional Rust/PyO3 segment engine with FFmpeg fallback
```

Rules:

- New domain capability: define/extend a `*Port` under `core/ports`, implement it under `adapters`, wire it at the composition root.
- React components do not call Tauri or the core directly. Use hooks/store → `src/lib/ipc.ts`; subscribe through typed backend events.
- `IpcRouter` is the executable command contract. When changing DTOs, update `dto.py`, hand-maintained `src/types/dto.ts`, and run `npm run gen:dto:check`.
- Preview and clip data never travel over JSON IPC. Use `watcher://`, preserve Range support and the Rust path allowlist.
- Keep role capability decisions centralized in `project/app/core/policy.py`. Operator is daemon/always-on; IT/Supervisor are sidecars that stop through stdin, never `process.kill()`.

## Video, recording and security constraints

- FFmpeg is launched with `subprocess`; do not introduce `ffmpeg-python` usage.
- Segments are `seg_*.ts` in `segments/m{index}/`; monitor `ddagrab` indices come from DXGI, not `screeninfo` ordering.
- HEVC may not play in WebView2. Offer/on-demand use H.264 transcode; do not assume a software fallback.
- `<video>.currentTime` is not frame exact. Export remains server-side.
- The preview HTTP server is localhost-only. Do not expose it to LAN.
- `adapters/browser_local` is the separate external browser channel for the
  Daily SIG Systems iframe. It may call `ApiLayer` only for its narrow,
  read-only contract; never route browser traffic through `IpcRouter`, reuse
  `watcher://`, or broaden its fixed `127.0.0.1`/`::1` TLS bind. Keep
  assertions/capabilities out of URLs and logs. See ADR-0020.
- Never commit `.env`, NAS credentials, PINs, or token material. The default IT PIN is intentionally tracked as a security TODO.

## Commands

From repository root (`setup_env.ps1` uses `uv` to provision Python 3.13 and resolve/install `project/requirements.txt`; do not add a second dependency manifest without an explicit migration):

```powershell
.\setup_env.ps1
.\Start-TheWatcher.ps1
npm run lint
npx tsc --noEmit -p tsconfig.json
npm run test
npm run gen:dto:check
$env:PYTHONPATH = "project"
$twPython = Join-Path $env:LOCALAPPDATA "The Watcher\venv\Scripts\python.exe"
& $twPython -m pytest project/tests -q
cd src-tauri; cargo test
```

Run the relevant suite after a change. CI is Windows-only and runs pytest (with FFmpeg), frontend lint/types/tests/DTO sync, and Rust tests. Tauri installer/release packaging is not yet part of CI.

## Current facts that supersede stale notes

- `screeninfo` is already in `project/requirements.txt`.
- `FilesystemStorageAdapter.list_segments()` already globs `seg_*.ts`.
- There is no `core/api/facade.py`; the actual entry port is `ApiLayer` plus `recording_api.py`, `settings_api.py`, `editor_api.py`, `clips_api.py`, `requests_api.py`, and `delivery_api.py`.
- The native segment engine code advertises `ENGINE_READY=true`; it still safely falls back to FFmpeg if the extension is unavailable.

For deeper context, use the spec kit first, then `project/README.md`, ADRs in `docs/architecture/adr/`, `.env.example`, and focused code/tests.

## Architecture governance

- Domain terms: [`docs/architecture/glossary.md`](docs/architecture/glossary.md).
- Non-functional requirements (project-wide): [`docs/architecture/nfr.md`](docs/architecture/nfr.md);
  editor-tab-scoped ones live in [`docs/architecture/goals.md`](docs/architecture/goals.md).
- Contribution/decision conventions, ADR template, ID scheme: [`CONTRIBUTING.md`](CONTRIBUTING.md).
- Feature backlog (feedback → epic → story, Gherkin acceptance criteria): [`docs/backlog/`](docs/backlog/README.md).
- Open decisions and known risks, including the current resource-governance gaps:
  [`TODOS.md`](TODOS.md).
