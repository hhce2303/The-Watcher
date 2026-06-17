# The Watcher

Always-on screen recorder with pre/post event capture. Built with Python + FFmpeg + PySide6/QML using a pragmatic Hexagonal (Ports & Adapters) architecture.

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
Supervisor UI
  → AppBridge.sendClipRequest()
  → ClipRequestClient (WS)
       → ClipRequestServer (WS) on IT machine
            → JsonRequestAdapter (persisted on disk)
            → ITInboxPanel (QML)
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
│   │   ├── ws/
│   │   │   ├── request_server.py    ← IT WebSocket server
│   │   │   └── request_client.py    ← Supervisor WebSocket client
│   │   └── ui/
│   │       ├── Main.qml             ← root window, tab navigation
│   │       ├── app_bridge.py        ← Python ↔ QML contract (QObject)
│   │       ├── settings_bridge.py   ← settings panel contract
│   │       ├── tray_icon.py         ← system tray
│   │       ├── screenshot_provider.py ← GDI monitor thumbnail provider
│   │       └── qml/
│   │           ├── Tokens.qml           ← design tokens (singleton)
│   │           ├── BufferTimeline.qml   ← segment timeline visualization
│   │           ├── PreRollOverlay.qml   ← pre-roll countdown overlay
│   │           ├── AnnotationModal.qml  ← clip annotation dialog
│   │           ├── MiniMode.qml         ← compact always-on-top mode
│   │           ├── SettingsView.qml     ← encoder / path / role settings
│   │           ├── HealthBadge.qml      ← recording health indicator
│   │           ├── ClipBrowser.qml      ← file browser (local + UNC/NAS)
│   │           ├── SupervisorView.qml   ← operator list + request form
│   │           ├── ITInboxPanel.qml     ← clip request inbox (IT role)
│   │           ├── Statusbar.qml
│   │           └── Components/
│   │               ├── WDropdown.qml
│   │               ├── WHotkey.qml
│   │               ├── WPathInput.qml
│   │               ├── WStepper.qml
│   │               ├── WToggle.qml
│   │               └── WSeg.qml
│   │
│   ├── infrastructure/
│   │   ├── config.py        ← Pydantic settings (.env)
│   │   ├── logging_setup.py ← loguru configuration
│   │   └── autostart.py     ← Windows registry autostart
│   │
│   └── main.py              ← startup wiring (services → bridge → QML engine)
│
├── installer/
│   ├── build.ps1            ← PyInstaller build script
│   ├── install.ps1          ← install to %LOCALAPPDATA%
│   └── The Watcher.iss      ← Inno Setup config
│
└── tests/
```

---

## UI Architecture (QML + AppBridge)

The UI was migrated from a legacy `QWidgets`-based `MainWindow` to a **PySide6 QML** interface in the current implementation.

### AppBridge

`AppBridge` is the single Python ↔ QML contract (`QObject` registered as a context property). It exposes:

**Properties (QML reads, Python notifies via signals):**

| Property | Type | Description |
|---|---|---|
| `isRecording` | `bool` | Whether the recorder is active |
| `recordSec` | `int` | Total seconds of buffered footage |
| `monitors` | `list` | All detected monitors with selection state |
| `clips` | `list` | Recent MP4 clips, newest first |
| `eventCount` | `int` | Events triggered this session |
| `currentClipPath` | `str` | Path of the clip loaded in the player |
| `currentClipInfo` | `map` | Codec / resolution / fps / bitrate |

**Slots (QML calls Python):**

| Slot | Description |
|---|---|
| `triggerEvent()` | Mark an event; respects cooldown |
| `toggleMonitor(fingerprint)` | Toggle clip-selection for a screen |
| `refreshClips()` | Reload clip list from disk |
| `loadClip(path)` | Load a clip into the player |
| `mediaUrl(path)` | Convert local/UNC path → media URL |
| `listDirectory(path)` | Browse local dirs or UNC shares |
| `identifyMonitors()` | Force monitor re-detection |
| `sendClipRequest(json)` | Send a clip request (Supervisor role) |
| `getMyRequests()` | Supervisor outbox |
| `getInboxRequests()` | IT inbox |
| `updateRequestStatus(id, status)` | IT: update request + broadcast via WS |
| `listAllOperators()` | Enumerate operator folders across all storage shares |

**Signals (Python → QML):**

| Signal | Description |
|---|---|
| `recordingFailed(msg)` | Worker crash notification |
| `clipFailed(msg)` | Clip build failure |
| `logMessage(msg)` | Log forwarding to QML console panel |
| `requestShowWindow()` | Tray icon → show window |
| `requestReceived()` | New clip request arrived (IT role) |
| `requestStatusChanged(id, status)` | Status update from IT (Supervisor role) |

### Preview system

The recorder FFmpeg process writes a JPEG at 2fps via `filter_complex` split — the same process as the recording. `AppBridge` polls these files every 500ms on the Qt main thread and pushes frames to `QVideoSink` instances registered by QML.

No separate screen-capture process = no screen flickering during preview.

### Monitor detection

`MonitorDetectionService` polls `screeninfo` every 5 seconds in a background thread. Hot-plug events (monitor connected/disconnected) are forwarded to `RecordingService` (to add/remove workers) and to `AppBridge` via a thread-safe signal bridge (the signal is emitted from the detection thread, handled in the Qt main thread).

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
9. QApplication + QQmlApplicationEngine
10. AppBridge + SettingsBridge registered as QML context properties
11. Main.qml loaded
12. WebSocket server (IT) or client (Supervisor) started
13. TrayIcon created
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
- `build.ps1` creates a clean venv at `C:\TW_Venv` and a junction at `C:\TW_Build` to work around a PyInstaller/PySide6 bug where `QLibraryInfo.path()` mis-parses plugin paths when the venv path contains a comma.
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
| M5 | PySide6 QML operator UI (AppBridge, tab layout) | Done |
| Monitor | Multi-monitor support + hot-plug detection | Done |
| M6 | Reliability & hardening (supervisor, disk monitor, health checks) | Done |
| M7 | Performance optimization (hardware encoder selector, embedded preview) | Done |
| M8 | Packaging & deployment (PyInstaller, installer scripts) | Done |
| M9 | Role system (operator / IT / supervisor) | Done |
| M10 | Clip request system (WebSocket IT↔Supervisor, outbox/inbox UI) | Done |
| M11 | Clip browser with UNC/NAS support | Done |
| M12 | Combined multi-monitor grid clip + hourly rolling raw clips | Done |

---

End of README.
