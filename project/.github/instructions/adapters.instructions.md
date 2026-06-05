---
description: >
  Use when creating or modifying adapters in app/adapters/. Covers FFmpeg subprocess
  patterns, PySide6 widget rules, port-adapter contracts, and file naming for this project.
applyTo: "app/adapters/**/*.py"
---

# Adapter Conventions — The Watcher

## Port Contract

Every adapter must inherit exactly one port ABC from `app/core/ports/` and implement all abstract methods.  
Do NOT inherit from `QObject` and an ABC at the same time — Qt metaclass and `ABCMeta` conflict.

```python
from app.core.ports.recorder_port import RecorderPort

class FFmpegRecorderAdapter(RecorderPort):  # one port, no QObject base
    ...
```

## FFmpeg Adapters (`adapters/ffmpeg/`)

- Call FFmpeg/ffprobe via `subprocess` — **never** via `ffmpeg-python`.
- Always pass command as a `list`, never `shell=True`.
- Capture stderr for diagnostics. Use `loguru.logger` to log it.
- Segment output format is **MPEG-TS** (`.ts`), not `.mp4`. This is intentional — `.ts` requires no `moov` atom and survives crashes.
- Hardware encoder is resolved once at process startup by `encoder_selector.py` (NVENC → QSV → libx264). Reuse the cached result; do not re-probe.
- Monitor capture index (`output_idx`) comes from `MonitorInfo.dxgi_index`, not from the position of the monitor in `screeninfo`'s list.

```python
# Correct subprocess pattern
import subprocess
cmd = ["ffmpeg", "-f", "ddagrab", f"output_idx={monitor.dxgi_index}", ...]
proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
```

## PySide6 UI Adapters (`adapters/ui/`)

- UI adapters are **not** domain objects. They must not contain business logic.
- For video rendering: use `QVideoWidget` as the output surface, not `QGraphicsVideoItem`.
- Call `QCoreApplication.addLibraryPath(pyside6_plugins_path)` before creating any `QMediaPlayer`.
- Widget signals carry only primitive types or stdlib types — never domain model objects.
- Use the `tw-*` design tokens (see `pencil/pencil-new.pen`) for any new color choices.

## Monitor Adapter (`adapters/monitor/`)

- `MonitorPort.list_monitors()` must return monitors in DXGI `EnumOutputs` order.
- Store both `screeninfo` display name (human-readable) and `dxgi_index` (for FFmpeg).
- Fingerprint monitors by `name + width + height + position` — indices can change after reboot.

## File Placement

| What | Where |
|------|-------|
| New FFmpeg-based adapter | `app/adapters/ffmpeg/{name}_adapter.py` |
| New UI widget | `app/adapters/ui/{widget_name}.py` |
| New port ABC | `app/core/ports/{domain}_port.py` |
| Wiring new adapter | `app/main.py` only |
