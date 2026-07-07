# The Watcher

Always-on screen recorder with pre/post event capture. Built with a Python + FFmpeg headless
backend (Hexagonal / Ports & Adapters) and a **Tauri 2.0 + React** UI talking to it over an
authenticated named pipe. PySide6/QML has been fully removed (F3, 2026-07-06) — see
[`docs/migration/`](docs/migration/README.md) for the migration history.

---

## Overview

Key characteristics:

- Continuous rolling buffer — captures the last N hours of every connected monitor
- Event clip — marks a moment and produces a `[pre] + [post]` MP4 automatically
- Multi-monitor — one FFmpeg worker per physical screen; combined grid clip + per-monitor raw clips
- Always-on — starts recording at login; the UI is optional and can be closed
- Role-aware — three modes: **Operator** (records), **IT** (records + receives clip requests), **Supervisor** (sends clip requests, no recording)

---

## Architecture

### Hexagonal (Ports & Adapters)

```
Core (Business Logic)
 └── Ports (Interfaces)
      └── Adapters (FFmpeg / filesystem / UI / WebSocket)
```

The recording service is a self-contained inner hexagon. The UI is a pure adapter — it calls services and observes their state but contains no business logic.

### Role system

| Role | Records | Receives requests | Sends requests |
|---|---|---|---|
| `operator` | yes | no | no |
| `it` | yes | yes (WS server) | no |
| `supervisor` | no | no | yes (WS client) |

Role is configured via `USER_ROLE` in `.env`. The `supervisor` role skips the entire recording stack at startup.

### Request flow (IT ↔ Supervisor)

```
Supervisor UI (React)
  → ipc.sendClipRequest() (named pipe)
  → RequestsApi.on_request_received
  → ClipRequestClient (websockets)
       → ClipRequestServer (websockets) on IT machine
            → JsonRequestAdapter (persisted on disk)
            → ITInboxPanel (React), via `request_received` bus event
```

---

## Project Structure

```
project/
├── app/
│   ├── core/
│   │   ├── recording_service/       ← rolling buffer, clip builder, segment index
│   │   │   ├── service.py           ← RecordingService (multi-monitor workers)
│   │   │   ├── buffer_manager.py    ← circular segment retention
│   │   │   ├── clip_builder.py      ← trim + concat pipeline
│   │   │   ├── segment_index.py     ← time-range lookup
│   │   │   ├── monitor_worker.py    ← per-monitor recording unit
│   │   │   ├── supervisor.py        ← crash-recovery / auto-restart
│   │   │   └── models.py
│   │   ├── event_service.py         ← event trigger + cooldown + scheduling
│   │   ├── monitor_detection/       ← hot-plug detection (background thread)
│   │   ├── recording_health/        ← health checks + watchdog
│   │   ├── player/                  ← clip inspection (ffprobe)
│   │   ├── disk_monitor.py          ← low-disk protection
│   │   ├── role.py                  ← role constants + enforcement
│   │   └── ports/                   ← abstract interfaces
│   │
│   ├── adapters/
│   │   ├── ffmpeg/
│   │   │   ├── recorder_adapter.py      ← gdigrab capture + embedded 2fps preview
│   │   │   ├── trim_adapter.py          ← event clip trimming
│   │   │   ├── encoder_selector.py      ← NVENC / QuickSync / AMF / CPU auto-detect
│   │   │   ├── combined_clip_builder.py ← multi-monitor grid + timestamp overlay
│   │   │   ├── hourly_recording_builder.py ← rolling hourly raw clips
│   │   │   ├── mp4_converter_adapter.py
│   │   │   └── timestamp_adapter.py
│   │   ├── filesystem/
│   │   │   ├── storage_adapter.py
│   │   │   ├── request_adapter.py   ← JSON persistence for clip requests
│   │   │   └── user_config_adapter.py
│   │   ├── monitor/
│   │   │   └── screeninfo_adapter.py
│   │   └── ws/
│   │       ├── request_server.py    ← IT server (asyncio `websockets`, Qt-free)
│   │       └── request_client.py    ← Supervisor client (asyncio `websockets`, Qt-free)
│   │
│   ├── infrastructure/
│   │   ├── config.py        ← Pydantic settings (.env)
│   │   ├── logging_setup.py ← loguru configuration (bus sink, no Qt)
│   │   └── autostart.py     ← Windows registry autostart
│   │
│   └── main.py              ← startup wiring (services → core/api Facade → IPC pipe)
│
├── src-tauri/                ← Tauri 2.0 Rust shell
│   └── src/
│       ├── lib.rs            ← app builder, single-instance, tray, window close policy
│       ├── ipc.rs            ← named-pipe client, connects to `core/api` router
│       ├── media_protocol.rs ← `watcher://` custom protocol (preview + clip streaming, Range support)
│       ├── tray.rs           ← role-aware tray menu
│       └── policy.rs         ← `AppPolicy` (role/window-close rules)
│
├── src/                       ← React UI (TypeScript, Vite)
│   ├── App.tsx                ← role-aware router (wizard / AppShell / ITEditorView / MiniMode)
│   ├── shell/                 ← AppShell, TabBar, Statusbar, HealthBadge, WindowControls
│   ├── features/               ← recording, clips, player, settings, supervisor, delivery, mini, editor, it
│   ├── lib/                    ← ipc.ts (typed command client), events.ts (typed bus events)
│   └── types/dto.gen.ts        ← generated from `core/api/dto.py` (Pydantic → JSON Schema → TS)
│
├── installer/
│   ├── build.ps1            ← PyInstaller build script (headless backend only)
│   ├── install.ps1          ← install to %LOCALAPPDATA%
│   └── The Watcher.iss      ← Inno Setup config
│
└── tests/
```

---

## UI Architecture (Tauri + React over named-pipe IPC)

The UI is **Tauri 2.0 + React**, talking to the headless Python backend over an authenticated
named pipe (`\\.\pipe\TheWatcher.<username>`, ADR-0011). QML/PySide6 were removed in full during
F3 (2026-07-06); see [`docs/migration/`](docs/migration/README.md) for the rationale (ADR-0008)
and [`docs/migration/reference-target-architecture.md`](docs/migration/reference-target-architecture.md)
for the current contract.

### `core/api` — the single entry port

`core/api` (Facade + Pydantic DTOs + thread-safe event bus, ADR-0009) is the only door into the
core. `adapters/ipc/router.py` dispatches ~40 named commands from the frontend to Facade methods;
the Facade publishes typed DTO events (`dto.py`) on the bus, which the router forwards to the
frontend as IPC events. React never talks to `core/` directly — only through
`src/lib/ipc.ts` (commands) and `src/lib/events.ts` (typed event subscriptions).

### Preview system

The recorder FFmpeg process writes a JPEG at 2fps via `filter_complex` split — the same process as
the recording. The Tauri `watcher://` custom protocol (`media_protocol.rs`) serves those frames
(and clip video, with HTTP Range support) directly to `<img>`/`<video>` elements — never through
the JSON IPC channel (TD-5).

### Monitor detection

`MonitorDetectionService` polls `screeninfo` every 5 seconds in a background thread. Hot-plug
events (monitor connected/disconnected) are forwarded to `RecordingService` (to add/remove
workers) and published on the event bus as `monitors_changed`, consumed by React via
`useBackendEvent`.

### Tab layout

| Tab | Ctrl shortcut | Shown for |
|---|---|---|
| Grabación (Recording) | `Ctrl+1` | operator, IT |
| Clips | `Ctrl+2` | all roles |
| Supervisor | `Ctrl+3` | supervisor only |
| IT Inbox | — | IT only |
| Mini-modo | `Ctrl+4` | operator, IT |
| Ajustes | `Ctrl+5` | all roles |

---

## Recording pipeline

```
MonitorDetectionService
  → one MonitorWorker per physical screen
       → FFmpegRecorderAdapter  (gdigrab → MPEG-TS segments + preview.jpg)
       → BufferManager           (rolling retention, prunes old segments)
       → HourlyRecordingBuilder  (assembles rolling hourly raw clips)

EventService.trigger_manual_event()
  → ClipBuilder.build_clip()
       → FFmpegTrimAdapter       (trims pre/post from segments)
       → FFmpegTimestampAdapter  (burns timestamp into final clip)
  → CombinedClipBuilder          (grid layout of all selected monitors)
```

### Output directories

```
WatcherData/
  clips/       ← combined multi-monitor MP4 (timestamp overlay)
  clips_raw/   ← per-monitor raw clips (one file per screen per hour)
  segments/    ← rolling TS segments (auto-pruned, never committed)
    m0/        ← monitor 0 segments + preview.jpg
    m1/        ← monitor 1 segments + preview.jpg
```

---

## Startup sequence

```
1. Acquire single-instance mutex (prevents duplicate instances)
2. Load settings (.env) + user config (user_config.json)
3. Enforce role (autorecord forced on for operator/IT)
4. Auto-detect hardware encoder (NVENC / QuickSync / AMF / CPU)
5. MonitorDetectionService.detect_now()
6. Build one MonitorWorker per detected screen (skipped for supervisor)
7. RecordingService.start() (if autorecord=true)
8. RecordingHealthService.start() + DiskSpaceMonitor.start()
9. core/api Facade built (`api.start()`), event bus wired to loguru sink
10. Requests server (IT) or client (Supervisor) started via `websockets`, `api.requests.configure(...)`
11. Named-pipe IPC server bound; mode resolved by role (ADR-0010): `--daemon` (Operator, survives
    UI close) or `--sidecar` (IT/Supervisor, dies with the app via stdin shutdown)
12. Tauri shell connects over the pipe (unless run headless via `run.ps1 -Mode daemon|sidecar`)
```

---

## Configuration

Copy `.env.example` to `.env` and adjust:

```env
# Role: operator | it | supervisor
USER_ROLE=operator

# Recording
SEGMENT_DURATION=10
RETENTION_HOURS=2
CAPTURE_FRAMERATE=30
OUTPUT_WIDTH=1920
OUTPUT_HEIGHT=1080
VIDEO_CODEC=hevc_nvenc   # or hevc_qsv / hevc_amf / libx265

# Event clip
EVENT_PRE_SECONDS=120
EVENT_POST_SECONDS=120
EVENT_COOLDOWN_SECONDS=30

# Storage
SEGMENT_DIR=C:/WatcherData/segments
CLIPS_DIR=C:/WatcherData/clips

# IT / Supervisor
IT_WS_PORT=9000
IT_WS_HOSTS=192.168.1.10,192.168.1.11
SLC_STORAGE_HOST=\\SIG-SLC-Storage

# NAS credentials (optional — for UNC share access)
NAS_USERNAME=
NAS_PASSWORD=
```

---

## Build & Install

Requirements: Python 3.13, FFmpeg installed via winget (`Gyan.FFmpeg`), project venv set up.

```powershell
# From project/ directory:
.\installer\build.ps1
```

**Output:**
- `dist\The Watcher\The Watcher.exe` — standalone executable
- `dist\The Watcher-<version>.zip` — distributable package (version from `app/__init__.py`)

**Install on target machine:**
```powershell
# Extract the zip, then:
.\install.ps1
```

Installs to `%LOCALAPPDATA%\The Watcher`. Optionally enables auto-start at Windows login. No desktop shortcut.

**Build notes:**
- `build.ps1` creates a clean venv at `C:\TW_Venv` and a junction at `C:\TW_Build` to work around a PyInstaller bug where paths containing a comma break dependency discovery. The backend is packaged headless-only (no QML/PySide6 data files since F3); the Tauri shell is launched separately in dev (`run.ps1`/`run_dev.ps1`) — a production Tauri installer bundling the backend as `externalBin` is future work.
- Delete `C:\TW_Venv` to force a full dependency reinstall on the next build.

---

## Milestone Status

| Milestone | Description | Status |
|---|---|---|
| M0 | Project bootstrap (venv, structure, logging) | Done |
| M1 | FFmpeg gdigrab recorder adapter | Done |
| M2 | Segment index + buffer manager | Done |
| M3 | Clip builder (trim + concat) | Done |
| M4 | Event service + cooldown logic | Done |
| M5 | PySide6 QML operator UI (AppBridge, tab layout) | Superseded by F2/F3 (React/Tauri) |
| Monitor | Multi-monitor support + hot-plug detection | Done |
| M6 | Reliability & hardening (supervisor, disk monitor, health checks) | Done |
| M7 | Performance optimization (hardware encoder selector, embedded preview) | Done |
| M8 | Packaging & deployment (PyInstaller, installer scripts) | Done |
| M9 | Role system (operator / IT / supervisor) | Done |
| M10 | Clip request system (WebSocket IT↔Supervisor, outbox/inbox UI) | Done |
| M11 | Clip browser with UNC/NAS support | Done |
| M12 | Combined multi-monitor grid clip + hourly rolling raw clips | Done |
| M13 | Editing tools (multi-clip evidence-reel timeline, trim, spatial zoom, lossless fullscreen, smart export) | Done (React editor, F2/M9) |
| M14 | Native Rust segment-compilation engine (PyO3/maturin, lossless TS→MP4 remux/concat/trim) behind `SegmentCompilerPort`, FFmpeg fallback | Done (Track R, `ENGINE_READY=true`) |
| F2/F3 | UI migration to Tauri 2.0 + React (full parity by role) + total removal of QML/PySide6 | Done (2026-07-06) |

---

## Future Scalability

The editing tab is being designed with seams toward a future YOLO-based event-detection +
analytics pipeline (decoupled inference, `DetectorPort` / `EventStorePort`, event sidecars,
timeline markers — Frigate-style). Goals, traceability matrix, ADRs and the phased roadmap live in
[`docs/editing/`](docs/editing/) (start with [`docs/editing/roadmap.md`](docs/editing/roadmap.md)).

---

End of README.
