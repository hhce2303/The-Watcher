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
| B-16 | **Resolved:** `LIVE_VIEW_PORT` default and `.env.example` aligned to **8767**, matching the firewall rule in `The Watcher.iss` and the `the-watcher-certs` deployment profile. | `app/infrastructure/config.py`, `.env.example` | Still confirm on watcher-win (V-10) that the port is reachable on the LAN. |

Not carried (their code is out of scope, ADR-0003): #22 `LivePreviewService` watchdog, #23 MJPEG stream catch-all,
#26 `BatchClipAnalyzer` retry, #8 truncated-preview negative test for the MJPEG preview server.

## Findings of the extraction review (new code, not yet fixed)

An independent read-only review of the extraction found these; the blocking ones (CI env for the purity test, lock
wait, stop robustness, signal handlers before start, `watcherctl` as launcher, relative-import scan) were fixed.
Remaining:

| ID | Issue | Where |
|----|-------|-------|
| B-17 | `daemon-status.json` write (`os.replace`) and read can race on Windows (no FILE_SHARE_DELETE): spurious tick errors / `health` "not running". Retry both sides. | `app/runtime/instance.py` |
| B-18 | `status`/`health` trust `psutil.pid_exists`; a recycled pid with an old status file reads as alive. Record process start time or delete the file on exit. | `app/runtime/instance.py`, `daemon_root._cmd_*` |
| B-19 | `health` is "unhealthy: not recording" during the first 10-30 s (ffmpeg probes). Add a `starting` state. | `daemon_root` |
| B-20 | Installer/Update hard-kill `The Watcher.exe` (`taskkill /F`, `Stop-Process -Force`), do not try `watcherctl stop` first and do not match `watcherctl.exe`. | `installer/` |
| B-21 | Inno `[Files]` copies the staged `.env`/`certs\` over an existing install (Update-Watcher.ps1 preserves them, the Inno path does not). Firewall rule is added on every install without an existence check (and port, see B-16). | `installer/The Watcher.iss` |
| B-22 | Purity test is a deny-list: an unlisted monorepo module would pass; non-literal `import_module` is not seen; dynamic boot uses `start_recording=False`. Replace by an allow-list of the 65-file closure. | `tests/test_import_purity.py` |
| B-23 | `build.ps1` hardcodes a pip list that can drift from `requirements.txt`; stale "dist" comments; `upx=True` in the spec. | `installer/` |
| B-24 | CI: `cache-dependency-path` hashes only `requirements-dev.txt`; no smoke test of the built exe; no `permissions:`/`concurrency:`; Python 3.13 is untested locally (3.14.7 used). | `.github/workflows/` |
| B-25 | Dropped monorepo behaviors: `migrate_legacy_event_clips`, hang-timeout `os._exit` hook, `on_recording_failed` wiring; the single-instance lock is now a machine-wide file lock (monorepo: per-session named mutex), so a running monorepo build does not exclude this daemon. State files land in `SEGMENT_DIR`'s parent (a drive root if `SEGMENT_DIR` is `D:\segments`). | `daemon_root`, `instance` |
