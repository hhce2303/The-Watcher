# Backend scope — The Watcher

This directory inherits the repository guide at [`../AGENTS.md`](../AGENTS.md) and the detailed specification at [`../docs/spec-kit/README.md`](../docs/spec-kit/README.md). Read those first; this file adds backend-local reminders.

- Run Python tests from the repository root with `$env:PYTHONPATH = "project"; $twPython = Join-Path $env:LOCALAPPDATA "The Watcher\venv\Scripts\python.exe"; & $twPython -m pytest project/tests -q`. The venv is provisioned by `uv`; do not rely on a global `python` command.
- `app/core/` stays dependency-free. Add driven boundaries under `app/core/ports/`, adapters under `app/adapters/`, and construct concrete objects only in `app/main.py` / the runtime builder.
- `app/core/api/ApiLayer` is the sole input boundary. The named-pipe `IpcRouter` is its desktop caller; the external Daily browser adapter is a separate read-only caller and must never expose the router. Keep command names, `dto.py`, `src/types/dto.ts`, and `src/lib/ipc.ts` synchronized for named-pipe cross-boundary changes.
- Preserve role topology: Operator is a detached daemon and IT/Supervisor are stdin-managed sidecars. Sidecar termination must be graceful because PyInstaller children can outlive a kill.
- Recording uses direct FFmpeg subprocesses, DXGI-backed `ddagrab` with `gdigrab` fallback, `.ts` segments, and a shared governance path for batch encodes. Do not couple ML or batch work to the live recorder path.
- Treat `project/.env.example` and `app/infrastructure/config.py` as the configuration contract; never store secrets in source control.
- `adapters/browser_local` listens only on TLS loopback (`127.0.0.1` / `::1`) for the Daily iframe. It is Operator-only, feature-flagged, authenticated by short Daily assertions, and intentionally does not share the Tauri protocol or UI. See `../docs/architecture/adr/ADR-0020-browser-local-daily-channel.md`.
