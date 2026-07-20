# The Watcher — Agent Instructions

Screen-recording desktop app: Python 3.13 + FFmpeg headless backend (**hexagonal / ports &
adapters architecture**) + **Tauri 2.0 + React** UI over an authenticated named pipe. PySide6/QML
were removed in full (F3, 2026-07-06) — see [`docs/migration/`](docs/migration/README.md) for the
migration history and ADRs 0008-0012.
See [README.md](README.md) for product overview and high-level flow.

---

## Commands

```powershell
# Run (dev) — Python backend (role-aware --daemon/--sidecar) + `npm run tauri dev`
.\run.ps1
# or, from project/, the in-repo-venv fast loop:
.\run_dev.ps1

# Headless only, no UI
.\run.ps1 -Mode daemon      # Operator topology (ADR-0010)
.\run.ps1 -Mode sidecar     # IT/Supervisor topology

# Tests
python -m pytest tests/          # backend
npm run test                     # frontend (vitest)
cargo check                      # Rust shell (from src-tauri/)

# Build installer (headless backend only; Tauri packaging is future work)
.\installer\build.ps1
```

> All Python commands must be run from `project/` with the venv active.

---

## Architecture

```
core/               ← Zero external dependencies. No FFmpeg or filesystem imports (Qt was
                       already excluded before the migration and stays excluded).
  ports/            ← ABCs only. One file per boundary.
  recording_service/← Domain: MonitorWorker, BufferManager, RecorderSupervisor, ClipBuilder
  player/           ← Domain: PlayerService, ClipInfo, PlaybackState
  api/              ← core/api Facade + Pydantic DTOs (dto.py) + thread-safe event bus (ADR-0009)
                       — the ONLY entry port; adapters/ipc is the sole caller.
  event_service.py  ← Orchestrates recording triggers

adapters/
  ffmpeg/           ← Implements RecorderPort, ClipPort, Mp4ConverterPort, ClipInspectorPort
  filesystem/       ← Implements StoragePort
  monitor/          ← Implements MonitorPort (screeninfo + DXGI ctypes for ddagrab index)
  ws/               ← IT server / Supervisor client (asyncio `websockets`, Qt-free)
  ipc/              ← Named-pipe router (ADR-0011): dispatches frontend commands to core/api,
                       forwards bus events to the Tauri/React frontend

infrastructure/
  config.py         ← Settings from .env (python-dotenv + pydantic)
  logging_setup.py  ← loguru: stderr + rotating file + bus sink (`log_message` event, no Qt)
  autostart.py      ← Windows registry Run key

app/main.py         ← Wiring root only. Manual DI, no framework. Resolves daemon/sidecar mode
                       by role (runtime/mode.py) and starts the headless runtime.

src-tauri/          ← Rust shell: named-pipe IPC client, `watcher://` custom protocol (preview +
                       clip streaming with Range support, TD-5), tray, single-instance, window
                       close policy (operator window "indestructible" while daemon runs).
src/                ← React UI: role-aware router, features/ per view, lib/ipc.ts + lib/events.ts
                       as the only bridge to the backend, types/dto.ts hand-maintained to mirror
                       dto.py; types/dto.gen.ts is a generated snapshot used only by
                       `npm run gen:dto:check` (CI) to catch drift — no app code imports it.
```

### Rules
- **Never import FFmpeg or `screeninfo` inside `core/`.**
- New domain behavior → add/extend a port in `core/ports/`, implement it in `adapters/`.
- `main.py` is the only place that wires concrete adapters to ports.
- React never talks to `core/` directly — only through `src/lib/ipc.ts` (commands) and
  `src/lib/events.ts` (typed bus event subscriptions), which go over the Tauri named-pipe IPC.
- Live preview/video never goes over the JSON IPC channel — always the `watcher://` custom
  protocol (TD-5). After changing `dto.py`, mirror the shape by hand in `src/types/dto.ts` (the
  file app code actually imports), then run `npm run gen:dto:check` — it regenerates
  `src/types/dto.gen.ts` from `dto.py` and fails if that snapshot doesn't match what's committed,
  catching drift between the Python and hand-written TS shapes. CI runs this on every PR.

---

## Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Port (ABC) | `{Domain}Port` | `RecorderPort`, `ClipInspectorPort` |
| Adapter | `{Tool}{Domain}Adapter` | `FFmpegRecorderAdapter`, `ScreeninfoMonitorAdapter` |
| Domain model (recording) | Pydantic `BaseModel`, frozen | `Segment`, `MonitorInfo`, `Event` |
| Domain model (player) | stdlib `dataclass` / `Enum` | `ClipInfo`, `PlaybackState` |
| Segment files | `seg_YYYYMMDD_HHMMSS.ts` | Format used by buffer manager |
| Clip files | `YYYY-MM-DD_HH-MM-SS.mp4` (combined), `_m{idx}.mp4` (raw), `_event.mp4` (event) | Timestamp is the real wall-clock recording start, not a rounded window boundary |
| Per-monitor segment dirs | `segments/m{index}/` | |
| Clip output dirs | `clips/` (combined), `clips_raw/` (per-monitor), `clips_events/` (auto/manual events) | Event clips no longer share `clips/` with combined recordings |

---

## Critical Pitfalls

### FFmpeg / Recording
- **FFmpeg is called via `subprocess` directly.** `ffmpeg-python` is in requirements but unused — do not use it.
- **Segments are `.ts` (MPEG-TS)**, not `.mp4`. `StorageAdapter.list_segments()` has a known bug — its glob pattern says `seg_*.mp4` but files are `.ts`. Fix the glob if working in that area.
- **Monitor indices for `ddagrab`** come from DXGI `EnumOutputs` (ctypes COM in `screeninfo_adapter.py`), **not** from `screeninfo` order. These can differ. Never assume they match.
- `RecorderSupervisor` uses exponential back-off (2s→4s→8s→30s cap, max 10 restarts). If it gives up, it logs and stops silently — monitor this in tests.

### Video (WebView2 / Tauri)
- **HEVC decode in WebView2 is hardware-dependent with no software fallback** (TD-1) — if
  `<video>` fails to play a clip, transcode on-demand to H.264 (`mp4_converter_adapter.py` via the
  `transcode_clip` IPC command) or open externally, never assume HEVC always plays.
- **`<video>.currentTime` is not frame-exact** (TD-7) — never build frame-accurate scrub/export
  from the `<video>` element; export stays server-side (FFmpeg).
- **`process.kill()` does not kill the PyInstaller one-file bootloader child** (TD-3) — shut the
  sidecar down via stdin, not process kill, when adding new termination paths.

### Configuration
- `screeninfo` is **missing from `requirements.txt`** — install it manually or add it if working in that area.
- `post_seconds` is duplicated in both `ClipBuilder` and `EventService`. The canonical value is `Settings.post_seconds` from `infrastructure/config.py`.

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | Entry point and manual DI wiring — start here to understand the full object graph |
| `app/infrastructure/config.py` | All configurable values (`Settings`); sourced from `.env` |
| `app/core/ports/` | All port ABCs — defines every system boundary |
| `app/core/api/facade.py` + `dto.py` | The single entry port into core (ADR-0009) — Facade methods + typed bus events |
| `app/adapters/ipc/router.py` | Named-pipe command dispatch — the contract the React frontend depends on |
| `app/adapters/ffmpeg/recorder_adapter.py` | FFmpeg `ddagrab` segment loop with supervisor |
| `app/adapters/ffmpeg/encoder_selector.py` | NVENC → QSV → libx264 probe (cached, run once at startup) |
| `app/adapters/monitor/screeninfo_adapter.py` | Physical monitor discovery + DXGI index mapping |
| `app/runtime/mode.py` | Role-aware `--daemon`/`--sidecar` resolution (ADR-0010) |
| `src-tauri/src/media_protocol.rs` | `watcher://` protocol — preview + clip streaming, Range support, path allowlist |
| `src/lib/ipc.ts` / `src/lib/events.ts` | Typed frontend command client / bus event subscriptions |
| `.env.example` | All supported environment variables |
