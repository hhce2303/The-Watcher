# Backlog — known recording / streaming issues

Carried over from the monorepo (`TODOS.md` @ `ed5fd98`) and re-scoped to what exists in this repo (spec §6: "las fallas
conocidas de grabación se registran como backlog del repo nuevo"). **Nothing here was fixed by the extraction**; the
copied code keeps these defects. Original item numbers are in brackets.

| ID | Issue | Where (this repo) | Note |
|----|-------|-------------------|------|
| B-1 [#1] | Hung-but-alive daemon is never restarted: the Scheduled Task only restarts on non-zero *exit*. | `app/infrastructure/scheduled_task.py` | `status`/`health` now expose `updated_at` staleness, but nothing consumes it automatically. |
| B-2 [#2] | Degraded watchdog (fell back to HKCU Run key) is only logged. | `app/daemon_root.py::ensure_launcher` | IT request channel does not exist here; surface it in `status` or the LAN `/api/v1/health`. |
| B-3 [#7] | Manual QA never run live: orphaned `.tmp.mp4` purge after killing a build; `RECOVERING` degraded/recovered notices. | `hourly_recording_builder._purge_stale_temps`, `recording_health/service.py` | Covered only by unit tests. Run on watcher-win. |
| B-4 [#11] | Resource governance gaps: batch Job memory ceiling never forced against a real OOM; recorder intentionally unbounded; `ProcTelemetry` swallows errors. | `process_guard.py`, `proc_telemetry.py`, ADR-0015 | Needs the pilot telemetry window of ADR-0015/0017. |
| B-5 [#15] | A corrupt/ABI-mismatched `watcher_segments` `.pyd` is logged like "not installed". | `adapters/native/rust_segment_compiler.py` | Log non-`ImportError` at `warning`. |
| B-6 [#16] | `on_recording_failed` last-resort callback swallows its own exceptions at `debug`. | `core/recording_service/supervisor.py` | In the daemon nothing is wired to it yet (no event bus): decide the escalation channel. |
| B-7 [#17] | `DiskSpaceMonitor` goes silent when `psutil.disk_usage` fails (unplugged share). | `core/disk_monitor.py` | Escalate after N consecutive failures. |
| B-8 [#19] | If recording start-up raises, the health service is never armed and the process stays alive and broken (no exit, so no watchdog restart). | `Daemon._start_services` (ported verbatim from `main.py::_start_recording_async`) | Fix direction: exit non-zero so the Scheduled Task restarts it. Not applied: the extraction is a copy. |
| B-9 [#20] | Job Object assignment failures logged at `debug`: ffmpeg children can lose "die with the app". | `adapters/ffmpeg/process_guard.py` | Raise to `warning`/`error`. |
| B-10 [#21] | `RecordingService._workers/_contexts` mutated without a lock (hot-plug vs health/status threads). | `core/recording_service/service.py` | `status()` and `DaemonApi` read these from the control thread. |
| B-11 [#25] | Device-identity key ACL hardening (`icacls`) is best-effort and not retried. | `adapters/browser_local/identity.py` | Re-apply on every start. |
| B-12 [#27] | No ffmpeg start-up self-test; a bad encoder kills recording and live view silently. | `adapters/ffmpeg/recorder_adapter.py`, `encoder_selector.py` | Seen 2026-09-29 (bundled Chocolatey shim; packaging fixed in `e0d1b2a`). |
| B-13 [#28] | Live view: `ddagrab` fails as a second capture (`Invalid argument -22`), falls back to gdigrab + software x264; CPU unmeasured. | `adapters/live_view_lan/h264_feed.py` | Blocks judging NFR-Perf-7 (<=5% CPU/monitor). Linux cannot reproduce it. |
| B-14 [#29] | Watchdog did not relaunch the daemon after it died (cause not established). | `scheduled_task.py` | Reproduce with/without a manual `schtasks /end`. |
| B-15 [#30] | CI never ran pytest and skipped builds on `app/` changes. | `.github/workflows/` | **Addressed structurally here** (`ci.yml`, widened paths); unverified until it runs remotely. |
| B-16 | Firewall rule in `The Watcher.iss` opens TCP **8767** while `LIVE_VIEW_PORT` defaults to **8766** (`.env.example`, `config.py`). | `installer/The Watcher.iss` | Found during extraction; inherited inconsistency, not changed. Verify which port is real on watcher-win. |

Not carried (their code is out of scope, ADR-0003): #22 `LivePreviewService` watchdog, #23 MJPEG stream catch-all,
#26 `BatchClipAnalyzer` retry, #8 truncated-preview negative test for the MJPEG preview server.
