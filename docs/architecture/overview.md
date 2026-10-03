# Architecture overview

Short Arc42-style summary of what is implemented (sections 3, 5, 6). Decisions: ADR-0001..0003 and the inherited ADRs.

## Context (arc42 §3)

```text
Operator PC (Windows)                          LAN
+--------------------------------+   HTTPS/WSS  +----------------------+
| the-watcher-daemon             | <----------> | Supervisor browser   |
|  capture -> segments -> clips  |  (ADR-0021/22) | (Daily SIG Systems) |
|  live view (H.264 / MJPEG)     |              +----------------------+
+----------------+---------------+
                 | TLS bundle (operator-deployment.env + certs/)  <- the-watcher-certs
                 v
          C:\WatcherData\{segments,clips_raw,clips,clips_events}
```

## Building blocks (arc42 §5)

- `daemon_root` wires config -> `MonitorDetectionService` -> `RecordingService` (one `MonitorWorker` per display) +
  `RecordingHealthService` + `DiskSpaceMonitor` -> `LiveViewLanAdapter(settings, DaemonApi, TlsMaterialPort)`.
- Recording: `FFmpegRecorderAdapter` writes MPEG-TS segments and a `preview.jpg` per monitor; `HourlyRecordingBuilder`
  closes per-monitor clips; `CombinedClipBuilder` composes the multi-monitor clip (ADR-0006, 0013-0017).
- Streaming: `LiveViewLanAdapter` reads `segments/m{i}/preview.jpg` (MJPEG) or spawns on-demand H.264 capture
  (`h264_feed`), behind session tokens from `browser_local.auth`/`identity`.

## Runtime view (arc42 §6)

1. `start`: take `daemon.lock` (second instance exits 0) -> clear stale `daemon.stop` -> register watchdog
   (Scheduled Task, fallback Run key) -> build -> start live view -> **background thread**: recording, disk monitor,
   detection, clip recovery, health (last).
2. Loop: every ~2 s write `daemon-status.json` (pid, recording, monitors, live_view, `updated_at`).
3. Stop: SIGINT/SIGTERM or `daemon.stop` -> `Daemon.stop()`: health, detection, disk, recording (kills ffmpeg), builders,
   telemetry, live view. `atexit` kills stray ffmpeg children as a last resort.
4. Errors: no monitors -> exit 1 (watchdog retries); live view/TLS failure is logged and never blocks recording.
