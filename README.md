# the-watcher-daemon

Operator recording + LAN live-view daemon extracted from the `The-Watcher` monorepo (see
[`docs/extraction.md`](docs/extraction.md) and [ADR-0001](docs/architecture/adr/ADR-0001-recording-streaming-source-of-truth.md)).
Sibling of `the-watcher-certs`, which provisions the TLS bundle (`docs/architecture/tls-provisioning-contract.md`).

Scope: continuous multi-monitor screen recording (ffmpeg, optional Rust segment engine) and the authenticated LAN live view
(H.264 over WebSocket, MJPEG fallback). No roles, no IPC pipe, no Tauri/Qt, no editor/player/analytics.

## Develop

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest -q          # includes the import-purity gate
```

Python 3.13 is the CI/bundle version. Tests that drive Windows-only code are skipped on Linux (reason shown with `-rs`).

## Run

```text
python -m app.daemon_root start      # foreground; default command (alias: --daemon)
python -m app.daemon_root status     # JSON status, exit 3 when not running
python -m app.daemon_root health     # exit 0 only if running, fresh and recording
python -m app.daemon_root stop       # graceful stop request (stop file)
```

Frozen build: `The Watcher.exe` (windowed daemon) and `watcherctl.exe` (console CLI). Configuration: `.env`
(copy `.env.example`). The state directory is the parent of `SEGMENT_DIR` (`C:\WatcherData` by default).

## Layout

| Path | Contents |
|---|---|
| `app/daemon_root.py`, `app/daemon_api.py` | composition root, minimal facade (ADR-0002) |
| `app/core/` | recording service, health, disk monitor, monitor detection, 8 ports |
| `app/adapters/` | ffmpeg, native (Rust), monitor, filesystem storage, live_view_lan, tls_provisioning, browser_local auth/identity |
| `app/runtime/` | headless lifecycle, single-instance lock + status/stop files |
| `app/infrastructure/` | config, logging, autostart, scheduled task, relaunch, process telemetry |
| `installer/`, `.github/workflows/` | PyInstaller spec, Inno Setup, build/update scripts, CI |
| `docs/` | ADRs, extraction record, pending verification, known-issues backlog |

## Status

Linux pytest green; the Windows bundle, ddagrab capture and live stream are **not verified yet** — see
[`docs/pending-verification.md`](docs/pending-verification.md).
