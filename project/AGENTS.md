# The Watcher — Agent Instructions

Screen-recording desktop app (Python 3.13 + PySide6 + FFmpeg) with **hexagonal (ports & adapters) architecture**.  
See [README.md](README.md) for product overview and high-level flow.

---

## Commands

```powershell
# Run (dev)
.\run_dev.ps1

# Run (production-style — sets QT_PLUGIN_PATH before launching)
.\run.ps1

# Tests
python -m pytest tests/

# Build installer
.\installer\build.ps1
```

> All commands must be run from `project/` with the venv active.  
> `run.ps1` sets `$env:QT_PLUGIN_PATH` before Python starts — required for PySide6 multimedia to find its plugins on Windows.

---

## Architecture

```
core/               ← Zero external dependencies. No FFmpeg, Qt, or filesystem imports.
  ports/            ← ABCs only. One file per boundary.
  recording_service/← Domain: MonitorWorker, BufferManager, RecorderSupervisor, ClipBuilder
  player/           ← Domain: PlayerService, ClipInfo, PlaybackState
  event_service.py  ← Orchestrates recording triggers

adapters/
  ffmpeg/           ← Implements RecorderPort, ClipPort, Mp4ConverterPort, ClipInspectorPort
  filesystem/       ← Implements StoragePort
  monitor/          ← Implements MonitorPort (screeninfo + DXGI ctypes for ddagrab index)
  ui/               ← PySide6 widgets — NOT domain objects

infrastructure/
  config.py         ← Settings from .env (python-dotenv + pydantic)
  logging_setup.py  ← loguru: stderr + rotating file + Qt sink
  autostart.py      ← Windows registry Run key

app/main.py         ← Wiring root only. Manual DI, no framework.
```

### Rules
- **Never import Qt, FFmpeg, or `screeninfo` inside `core/`.**
- New domain behavior → add/extend a port in `core/ports/`, implement it in `adapters/`.
- `main.py` is the only place that wires concrete adapters to ports.

---

## Naming Conventions

| Type | Pattern | Example |
|------|---------|---------|
| Port (ABC) | `{Domain}Port` | `RecorderPort`, `ClipInspectorPort` |
| Adapter | `{Tool}{Domain}Adapter` | `FFmpegRecorderAdapter`, `ScreeninfoMonitorAdapter` |
| Domain model (recording) | Pydantic `BaseModel`, frozen | `Segment`, `MonitorInfo`, `Event` |
| Domain model (player) | stdlib `dataclass` / `Enum` | `ClipInfo`, `PlaybackState` |
| Segment files | `seg_YYYYMMDD_HHMMSS.ts` | Format used by buffer manager |
| Clip files | `YYYY-MM-DD_HH-MM-SS_event.mp4` | |
| Per-monitor segment dirs | `segments/m{index}/` | |

---

## Critical Pitfalls

### FFmpeg / Recording
- **FFmpeg is called via `subprocess` directly.** `ffmpeg-python` is in requirements but unused — do not use it.
- **Segments are `.ts` (MPEG-TS)**, not `.mp4`. `StorageAdapter.list_segments()` has a known bug — its glob pattern says `seg_*.mp4` but files are `.ts`. Fix the glob if working in that area.
- **Monitor indices for `ddagrab`** come from DXGI `EnumOutputs` (ctypes COM in `screeninfo_adapter.py`), **not** from `screeninfo` order. These can differ. Never assume they match.
- `RecorderSupervisor` uses exponential back-off (2s→4s→8s→30s cap, max 10 restarts). If it gives up, it logs and stops silently — monitor this in tests.

### PySide6 / Video
- **Use `QVideoWidget` as the video output target**, never `QGraphicsVideoItem`. `QGraphicsVideoItem` creates a `QVideoSink` requiring D3D11/RHI which fails silently on many machines.
- `QCoreApplication.addLibraryPath()` must be called before the first `QMediaPlayer` is instantiated to ensure multimedia plugins are found (done in `player_widget._bootstrap_multimedia_path()`).
- Qt metaclass conflict: Qt widgets (`QObject` subclasses) cannot also inherit from `ABCMeta`. Implement ports via duck typing on UI classes, not via ABC inheritance.

### Configuration
- `PySide6` and `screeninfo` are **missing from `requirements.txt`** — install them manually or add them if working in that area.
- `post_seconds` is duplicated in both `ClipBuilder` and `EventService`. The canonical value is `Settings.post_seconds` from `infrastructure/config.py`.

---

## Key Files

| File | Purpose |
|------|---------|
| `app/main.py` | Entry point and manual DI wiring — start here to understand the full object graph |
| `app/infrastructure/config.py` | All configurable values (`Settings`); sourced from `.env` |
| `app/core/ports/` | All port ABCs — defines every system boundary |
| `app/adapters/ffmpeg/recorder_adapter.py` | FFmpeg `ddagrab` segment loop with supervisor |
| `app/adapters/ffmpeg/encoder_selector.py` | NVENC → QSV → libx264 probe (cached, run once at startup) |
| `app/adapters/monitor/screeninfo_adapter.py` | Physical monitor discovery + DXGI index mapping |
| `app/adapters/ui/player_widget.py` | `ZoomableVideoWidget` — `QVideoWidget` + `QScrollArea` zoom/pan |
| `.env.example` | All supported environment variables |
