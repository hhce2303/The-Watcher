# TODOS

## Operator policy engine — deferred follow-ups
Captured during `/plan-eng-review` of `feat/operator-policy-engine` (2026-06-23).
All three were consciously deferred to keep this PR right-sized; each has a clear
trigger to pick it up.

### 1. Hang / liveness detection for the operator process
- **What:** Detect and recover a *hung-but-alive* operator process (frozen main
  loop — the operator process is now the headless Python daemon post-F1/F3, not
  the old Qt event loop) — add a heartbeat (the app writes a timestamp; a
  checker relaunches if stale) or a watchdog execution-time-limit.
- **Why:** The current restart watchdog is a Windows Scheduled Task with
  *restart-on-failure*. It only fires when the process *exits* with a non-zero
  result (kill / crash). A process that is alive but wedged never exits, so the
  scheduler never restarts it and recording silently stops.
- **Pros:** Closes the last always-on gap.
- **Cons:** Reintroduces the polling/heartbeat machinery the native-scheduler
  approach deliberately avoided; risk of false-positive relaunches during heavy
  disk I/O or FFmpeg stalls.
- **Context:** The common hang (FFmpeg stall) is already handled in-process by
  `RecorderSupervisor` (`app/core/recording_service/supervisor.py`) plus
  `recording_health`. This TODO is only for a *full-app* freeze, which is rarer.
- **Depends on:** the scheduled-task watchdog (`app/infrastructure/scheduled_task.py`).

### 2. Report degraded watchdog state to IT (remote)
- **What:** When the scheduled-task registration fails (corporate group policy /
  permissions) and the app falls back to the HKCU Run key, push that degraded
  state to IT over the existing request WebSocket / inbox — not just a log line.
- **Why:** On a locked-down box the operator has no settings tab and may never
  see a log file. IT should know which stations lack restart-after-kill
  protection (fleet health).
- **Pros:** IT visibility into degraded stations.
- **Cons:** Couples a log/status concern to the WS/inbox plumbing for a rare case.
- **Context:** `enforce_role` returns `"runkey"` in this case (see
  `app/core/role.py`). Post-F3, `main.py` only logs this
  (`logger.info("Role: {} | watchdog: {}", ...)`) — the old Python tray tooltip
  (`app/adapters/ui/tray_icon.py`) that used to surface it was removed with
  QML/PySide6; the new Rust tray (`src-tauri/src/tray.rs`) does not yet surface
  watchdog status either, so this is currently invisible outside the log file.
  The WS server/client live in `app/adapters/ws/`.
- **Depends on:** the request system (IT server / Supervisor client).

## Ship follow-ups — feat/f1-backend-headless → main (2026-07-10)
Captured during `/ship` of the F1–F3 migration branch (backend headless, full
React+Tauri UI, Rust segment engine, MJPEG preview server) plus this session's
recording-health/hourly-clip fix. Deferred to keep the ship moving; each has a
clear trigger to pick it up.

### 4. CI/release pipeline for the Tauri installer + Rust native module
- **What:** No `.github/workflows/` exists yet. This branch introduces two new
  distributable artifacts — the Tauri desktop shell (`src-tauri/`) and the
  native Rust segment engine (`project/native/watcher_segments`, built via
  `maturin`) — with no automated build/release pipeline for either.
- **Why:** Already flagged in `CLAUDE.md` (repo root) as a known remaining item
  ("Tauri prod installer packaging queda como fase posterior a F3"). Not a
  surprise, but worth a durable tracker now that the branch is landing.
- **Pros:** Reproducible signed installers (MSI/NSIS via `tauri-action`),
  catches native-build breakage in CI instead of on a dev machine.
- **Context:** `tauri-action` is the standard GitHub Actions integration;
  `maturin` is already wired into `setup_env.ps1` / `installer/build.ps1`
  per the Rust F0 spike.
- **Depends on:** —

### 5. Test coverage gaps in the React UI and Tauri Rust shell
- **What:** AI-assessed coverage audit at ship time: ~55% weighted by risk.
  Closed in this ship: `ipc.rs` (10 unit tests on the extracted
  frame-classification/encoding/frame-limit logic) and `LogDrawer`/`LogTicker`
  (render tests added during Fix-First triage, plus a shared
  `LOG_LEVEL_STYLE` map replacing the duplicated per-component branching).
  Remaining gaps:
  - 38 of the 39 new React component/feature/shell files (editor/trim/export
    flow, `ITEditorView`, `SupervisorView`, `AnalyticsTab`, most of
    `src/shell/*`) have no component test.
  - 9 of 14 new frontend hooks are untested: `useClipTranscode`,
    `useEditorExport`, `useInboxRequests`, `useLiveAnalytics`, `useMediaRoots`,
    `useRequests`, `useSettingsForm`, `useStorages`, `useTauriEvent`/`useIpc`.
  - `src-tauri/src/{commands,policy,tray,lib}.rs` have no `#[test]`s (only
    `media_protocol.rs` and `ipc.rs` do).
- **Why:** Untested paths are where regressions hide silently, especially in
  the frame-exact editor/export flow (already flagged as tricky in TD-7).
- **Pros:** Closes the highest-remaining-risk gap; the backend Python suite
  is already at ~90% module-to-test mapping, so this brings the frontend/Rust
  shell up to the same bar.
- **Cons:** Non-trivial effort — component tests for the editor/export flow
  need a render harness; the Rust command layer needs a `tauri::test`
  approach that doesn't hit the `MockRuntime` linking issue found this
  session (see item 6).
- **Depends on:** item 6 if the Rust command layer is tackled with
  `tauri::test::mock_app()`.

### 6. `tauri::test::mock_app()` crashes the test binary on this machine
- **What:** Adding `tauri = { features = ["test"] }` as a dev-dependency and
  calling `tauri::test::mock_app()` from a `#[tokio::test]` compiles cleanly
  but the resulting test executable crashes at startup with
  `STATUS_ENTRYPOINT_NOT_FOUND` (0xc0000139) — reproducible, affects the
  *entire* test binary (including previously-passing `media_protocol.rs`
  tests), both in `--release` and debug profile.
- **Why:** Investigated during this ship's `ipc.rs` coverage work; root cause
  not identified (looks like a DLL/feature-unification interaction between
  the `test` feature and the real `tray-icon`/`image-png` GUI features
  compiled into the same binary — possibly a stale/mismatched native
  WebView2 dependency). Worked around by extracting the pure protocol logic
  (frame classification, request encoding) into free functions and testing
  those directly with plain `#[test]`, avoiding `AppHandle` entirely.
- **Pros of investigating:** Unblocks proper `tauri::test`-based command/IPC
  integration testing (needed for item 5's Rust command-layer gap).
- **Cons:** Environment-specific Windows/Tauri toolchain issue, could be a
  rabbit hole; the workaround (pure-function extraction) is a reasonable
  permanent pattern regardless.
- **Context:** repro is `cargo test --release` in `src-tauri/` with
  `tauri = { version = "2", features = [...original features..., "test"] }`
  added under `[dev-dependencies]`.
- **Depends on:** —

### 7. Manual QA for the recording-health visibility fix (this session)
- **What:** Two manual verification steps from this session's plan were not
  run live (accepted with automated-test coverage as a substitute):
  1. Kill a monitor's ffmpeg mid-build with the app running — confirm the
     orphaned `.tmp.mp4` disappears on the next segment cycle instead of
     persisting until app restart.
  2. Force a worker into `RECOVERING` (kill the live recorder's ffmpeg, not
     a build) — confirm a "warning"-level entry appears in the frontend
     LogDrawer, and a recovery entry on stabilization.
- **Why:** `test_hourly_recording_builder_purge.py` and
  `test_recording_health_service.py` + `appStore.test.ts` cover the logic in
  isolation but not the true end-to-end live-app flow.
- **Context:** see `project/app/adapters/ffmpeg/hourly_recording_builder.py`
  (`_purge_stale_temps`) and `project/app/core/recording_health/service.py`
  (`set_callbacks`).
- **Depends on:** running the real app with a live recorder.

### 8. Negative-case test for a truncated preview JPEG
- **What:** `_read_valid_jpeg()` (`mjpeg_server_adapter.py`) requires both the
  SOI (`\xff\xd8`) and EOI (`\xff\xd9`) markers — discovered while fixing the
  test fixtures in `test_preview_server.py` (they were missing the EOI byte,
  which caused a real test hang this session, see the ship diagnosis).
  No test covers the actual real-world case this validation guards against:
  a `preview.jpg` truncated mid-write by FFmpeg (present on disk, missing the
  EOI marker) — confirm the snapshot endpoint 404s/retries and the MJPEG
  stream skips that frame instead of serving a corrupt one.
- **Why:** Lowest-priority item from this ship's pre-landing review
  (confidence 4/10 — appendix-tier, not blocking); flagged for completeness
  rather than fixed inline to keep the ship moving.
- **Context:** `project/tests/test_preview_server.py`,
  `project/app/adapters/preview_server/mjpeg_server_adapter.py:99-120`.
- **Depends on:** —

## LiveViewPort — deferred policy prerequisite (2026-07-12)
Captured during `/office-hours` + `/autoplan` review of "Live LAN Screen Viewing for
Supervisors" (branch `feat/f1-backend-headless`). Deferred to keep architecture/
implementation work moving; has a clear trigger and a hard gate before rollout.

### 9. "Who can view whom" authorization policy for `LiveViewPort`
- **What:** Define which Supervisor may request to view which Operator, under what
  condition (e.g., any Supervisor↔any Operator, or scoped by site/team) — even a
  deliberately simple placeholder rule. Confirmed during Eng review that this codebase
  has zero identity-to-identity authorization plumbing today: `RequestsApi.send_clip_request`
  accepts any `operator` string with no cross-check, and `UserConfig.role` is a flat
  string (operator/supervisor/it), not a permission graph.
- **Why:** The session-token schema for `LiveViewPort` (`operator_id`, `supervisor_id`,
  `monitor_index`, ...) cannot be authorization-checked without this rule existing
  somewhere. Deferring it lets the port/Facade/DTO/session-token architecture and
  implementation proceed now (Approach B, see design doc), but it is a **hard
  prerequisite before `LiveViewPort` is enabled on the real fleet** — an explicit,
  logged placeholder rule (even "any Supervisor may view any Operator") must land
  before rollout, not after.
- **Pros:** Unblocks implementation of the port/Facade/DTO/session-token layer now
  without waiting on an org policy conversation.
- **Cons:** Ships an authorization no-op if this is never resolved before rollout —
  any Supervisor can watch any Operator with no rule to point to. This is the single
  named risk both the CEO review and Eng review flagged independently during
  `/autoplan`.
- **Context:** Design doc + full review history:
  `~/.gstack/projects/hhce2303-The-Watcher/hcruz--feat-f1-backend-headless-design-20260712-132557.md`.
  Architecture pointer: `docs/migration/reference-target-architecture.md`
  (`LiveViewPort` section). Go-as-escalation-path decision:
  [ADR-0018](docs/architecture/adr/ADR-0018-go-liveview-relay-escalation-deferred.md).
- **Depends on:** whoever owns Operator/IT/Supervisor role definitions landing at least
  a placeholder rule before rollout to the real fleet.

## Repo audit remediation — pending decisions (2026-07-12)
Captured during Milestone 1 of the post-audit remediation plan
(branch `feat/f1-backend-headless`). Deferred to keep M1 unblocked; each has a
clear trigger to pick it up.

### 10. Decide the real fix for the default `IT_PIN`
- **What:** `IT_PIN` still defaults to `"1234"` (`app/infrastructure/config.py`,
  `it_pin` field). M1 only added a loud startup warning
  (`main.py::_warn_if_default_it_pin`) when the PIN is unchanged — it does
  **not** change behavior. Someone needs to decide the actual fix:
  (a) remove the default entirely (requires adding a `None`/empty check in
  `SettingsApi.unlock_it()` — today there is none, so an unset PIN would
  silently and permanently fail every unlock attempt), or
  (b) keep a default but force a first-run "set your IT PIN" step, or
  (c) accept the warning-only fix as sufficient for now.
- **Why:** Removing the default outright without a `None`-check first is a
  regression, not a fix — it trades a weak-but-working PIN for a silent
  permanent lockout. This needs a deliberate choice, not a reflexive "just
  delete the default."
- **Pros:** Closes the actual security gap (weak, well-known default PIN)
  instead of just logging about it.
- **Cons:** Any option beyond the warning touches the IT unlock UX and
  deserves a quick sign-off before implementation.
- **Context:** `app/infrastructure/config.py:170` (field), `app/core/api/settings_api.py`
  (`unlock_it()`, sole consumer). Only consumer confirmed via repo-wide grep.
- **Depends on:** whoever owns the IT-unlock UX flow.

## Resource governance — open risks (architecture-bootstrap gap-fill, 2026-09-13)
Captured while filling the `nfr.md`/`glossary.md`/`CONTRIBUTING.md`/`docs/backlog/` gaps
in the architecture-bootstrap baseline, per user report that the project ships with
"serious bugs, mostly resource abuse." Nothing below is a new finding — each line is
already evidenced elsewhere in the repo; this entry exists so the category is
tracked as one open risk instead of scattered across ADRs and prior TODOS items.
Full detail and IDs: [`docs/architecture/nfr.md`](docs/architecture/nfr.md)
§§1–2 (NFR-Perf-4/5, NFR-Rel-1/6, NFR-Obs-2).

### 11. Resource-abuse risk surface has partial governance, not full coverage
- **What:** Five concrete gaps, all already documented individually:
  1. The batch FFmpeg Job's memory ceiling (`BATCH_JOB_MEMORY_LIMIT_MB`) was verified
     by configuration only — never forced against a real OOM ([ADR-0015](docs/architecture/adr/ADR-0015-batch-ffmpeg-governance.md)).
  2. The recorder process itself is **intentionally unbounded** (no CPU/memory cap —
     a hard cap would freeze it under budget exhaustion), which is the single
     largest surface for uncontrolled resource use if the capture pipeline
     misbehaves ([ADR-0015](docs/architecture/adr/ADR-0015-batch-ffmpeg-governance.md) §Contexto).
  3. `ProcTelemetry` swallows `psutil`/PID errors silently by design (best-effort) —
     it can stop reporting a real resource problem with no alert (same ADR).
  4. Only the recorder's own supervisor detects a hang; a full-app freeze is
     invisible to the OS watchdog, which only reacts to process *exit* (item #1
     above, still open).
  5. A degraded watchdog fallback (`HKCU Run` instead of the Scheduled Task) is
     logged but not surfaced to IT (item #2 above, still open).
- **Why:** None of these are individually new, but nobody had connected them as one
  "resource governance" risk category before. Reported by the user as the project's
  most serious class of bug at this point.
- **Pros of closing:** A pilot deployment (already recommended in ADR-0015 to close
  the ADR-0007 gate) would exercise #1 and #2 together — a good, cheap way to get
  real evidence instead of guessing.
- **Cons:** No fix proposed here on purpose — this entry is a registration of the
  risk, not a remediation plan. Each sub-item already has its own trigger (see
  `nfr.md`); solving one here without touching the others would be premature scope.
- **Context:** `project/app/infrastructure/proc_telemetry.py`, `process_guard.py`
  (batch Job + semaphore), `app/core/recording_service/supervisor.py` (recorder-only
  hang detection).
- **Depends on:** the pilot-deployment telemetry window already called for in
  [ADR-0015](docs/architecture/adr/ADR-0015-batch-ffmpeg-governance.md) /
  [ADR-0017](docs/architecture/adr/ADR-0017-adr0007-sla-verdict-confirmed.md); no
  new owner assigned yet.

## Silent-failure audit remediation — roadmap (2026-09-13)
Captured from a full-repo `/investigate` audit of `app/core`, `app/adapters`,
`app/infrastructure`/`app/runtime`, and `native/watcher_segments` (no Tauri/React
UI exists yet — still headless-sidecar phase). Nothing here has been fixed;
this is the tracker + a proposed fix order. Full findings kept in session
history; each item below carries file:line so it can be picked up standalone.

**Proposed fix order (roadmap):**
1. **Wave 1 — data-loss / topology-integrity (items 12-15):** these can silently
   turn an Operator into a non-recording machine, or make IT falsely believe a
   clip request was saved. Fix first — highest blast radius, lowest effort per fix
   (each is a narrow except-block).
2. **Wave 2 — last-resort alerting (items 16-18):** the "we already gave up,
   now tell someone" paths. If these are broken, every other safeguard in the
   app is silently defeated at the finish line.
3. **Wave 3 — watchdog/process governance (items 19-21):** Job Object failures,
   health-service arming, and `RecordingService` thread-safety. Higher effort
   (touches concurrency), do after Wave 1/2 land and are verified.
4. **Wave 4 — UX-visible but non-critical (items 22-26):** stale live-preview
   tiles, MJPEG catch-all logging, delivery path mismatches, ACL hardening,
   batch analyzer retries. Fix opportunistically.

### 12. Corrupt `user_config.json` silently demotes Operator to unconfigured
- **What:** `JsonUserConfigAdapter.load()` (`app/adapters/filesystem/user_config_adapter.py:26-42`)
  catches any load exception and returns `UserConfig()` (role `""` = unconfigured),
  logged only at `warning`. `role.py`/`main.py` then silently build no recording
  stack and remove the Scheduled Task watchdog.
- **Why:** A truncated write (crash/power-loss mid-`save()`, disk full, AV lock)
  turns into "operator stopped recording" with zero fatal signal.
- **Fix direction:** distinguish "file absent" (fine, first run) from "file present
  but unparseable" (must fail loud — refuse silent fallback to unconfigured,
  surface a startup error / keep last-known-good role instead).
- **Depends on:** none — self-contained in the adapter.

### 13. `save()` failures on `user_config.json` are invisible to the caller
- **What:** `JsonUserConfigAdapter.save()` (`app/adapters/filesystem/user_config_adapter.py:53-70`)
  swallows write errors with only a `warning`; no exception reaches `SettingsApi`
  or the role-change flow.
- **Why:** Combined with #12, a role change can appear to succeed in the UI but
  revert silently on next relaunch.
- **Fix direction:** propagate a typed result/exception so `SettingsApi.set_role`
  can report failure to the caller instead of assuming success.
- **Depends on:** #12 (same file, do together).

### 14. IT server ACKs a clip request even when persisting it failed
- **What:** `request_server.py:146` sends `{"type": "ack", ...}` unconditionally;
  `JsonRequestAdapter.save()` (`app/adapters/filesystem/request_adapter.py:32-41`)
  swallows `OSError` and returns `None` either way.
- **Why:** Supervisor believes a clip request was received and will be fulfilled;
  it silently never was.
- **Fix direction:** `save()` should return success/failure (or raise); `_on_message`
  must send an error response instead of `ack` when persistence fails.
- **Depends on:** none.

### 15. Broken native Rust extension is indistinguishable from "not installed"
- **What:** `_load_native()` (`app/adapters/native/rust_segment_compiler.py:22-29`)
  folds `ImportError` (expected, FFmpeg-only build) and a corrupt/ABI-mismatched
  `.pyd` (packaging defect) into the same `None` + info-level fallback log.
- **Why:** A packaging regression that ships a bad `.pyd` degrades every machine
  to the slower FFmpeg path with no alert distinguishing it from the intentional
  no-Rust-build case.
- **Fix direction:** log the actual exception type/message at `warning` when it's
  anything other than a clean `ImportError`, so a DLL/ABI failure is visibly
  different from "module not present."
- **Depends on:** none.

### 16. Last-resort failure callbacks (`on_clip_failed`/`on_recording_failed`) swallow their own exceptions at `debug`
- **What:** `event_service.py:199-207` and `recording_service/supervisor.py:136-143`
  wrap the final give-up notification in `except Exception: logger.debug(...)`
  — the one place in the codebase that *should* escalate loudest logs quietest.
- **Why:** If the wired callback itself throws (bug in DTO construction, bus in a
  bad state), the operator never learns recording stopped for good or a clip
  permanently failed — and there's no log trail above debug to even diagnose it.
- **Fix direction:** match the pattern used everywhere else in the codebase —
  `logger.exception(...)` (ERROR + traceback), not `debug`.
- **Depends on:** none — two one-line severity/API fixes.

### 17. `DiskSpaceMonitor` never escalates when it can't read disk usage
- **What:** `disk_monitor.py:83-93` catches any `psutil.disk_usage` failure,
  logs a `warning`, and returns — no escalation ladder like the health/detection
  services have, and `on_low_disk` never fires from this path.
- **Why:** A disconnected network share or ejected removable drive makes the
  one guard against filling the recording disk go permanently silent.
- **Fix direction:** treat N consecutive read failures as itself a critical
  condition (escalate the same way `RecordingHealthService`/`MonitorDetectionService`
  already do), not as "nothing to report."
- **Depends on:** none — same file already has the escalation pattern to copy
  from other services.

### 18. `RecordingApi._persist_selection` drops monitor-selection persistence failures
- **What:** `app/core/api/recording_api.py:199-207` — `toggle_monitor()` always
  reports success to the UI regardless of whether the on-disk save worked.
- **Why:** Operator's monitor-selection choice silently reverts on next restart
  with no explanation ("the app forgot my setting").
- **Fix direction:** publish a bus event (or return a failure DTO) when
  `_persist_selection` fails, so the UI can show a real warning.
- **Depends on:** #13 if the underlying adapter's save-failure signaling changes.

### 19. `_start_recording_async` never arms `health_service` if startup fails
- **What:** `app/main.py:798-822` — on any exception from `_start_recording_services`/
  `_recover_startup_clips`, the function logs and returns without calling
  `backend.health_service.start()`. The Scheduled Task watchdog trigger
  (`os._exit(1)` on hang) lives inside that health service, so it's never armed.
- **Why:** A daemon that fails to start recording keeps running (looks alive to
  any process monitor) with zero self-healing path — no crash, so the Scheduled
  Task restart never fires either.
- **Fix direction:** on this failure path, force an immediate `os._exit(1)` (or
  equivalent) so the existing watchdog restart mechanism actually engages,
  instead of leaving a live-but-broken process.
- **Depends on:** none.

### 20. Job Object assignment failures are logged at `debug` — FFmpeg children can become unkillable
- **What:** `process_guard.py:215-245` — `CreateJobObjectW`/`AssignProcessToJobObject`
  failures are caught and logged at `debug` only.
- **Why:** On a locked-down image (EDR/AV blocking Job Objects), every FFmpeg
  recorder/batch child silently loses its "die with the app" guarantee — directly
  relevant to TD-3 (`process.kill()` doesn't reliably kill the PyInstaller
  one-file sidecar).
- **Fix direction:** raise this to `warning`/`error` and consider surfacing it
  through the same IT-visibility channel as item #2 above (degraded watchdog
  state) — this is the same category of "fleet health IT should know about."
- **Depends on:** item #2 (report degraded watchdog state to IT) if a shared
  reporting channel is built.

### 21. `RecordingService._workers`/`_contexts` mutated without a lock across threads
- **What:** `app/core/recording_service/service.py` `add_worker`/`remove_worker`
  (hot-plug thread) vs. `health_report()`/`total_stored_duration_seconds()`
  (health-watchdog thread, IPC/UI poll thread) — no lock, unlike
  `segment_index.py` which is correctly locked.
- **Why:** ADR-0009 requires thread-safety at the facade/event-bus boundary;
  this is a genuine gap — a hot monitor unplug/replug racing a health check or
  UI poll can throw `RuntimeError: dictionary changed size during iteration`
  (uncaught on the IPC path) or silently return a stale/partial worker view.
- **Fix direction:** add the same lock pattern already used in `segment_index.py`
  around `_workers`/`_contexts` mutation and iteration.
- **Depends on:** none — self-contained, but higher effort/risk (concurrency
  change), do after Wave 1/2 are verified.

### 22. `LivePreviewService` has no crash/restart watchdog (unlike the real recorder)
- **What:** `live_preview_service.py:168-198` — reader thread just exits on EOF/
  exception with a `debug` log; no `on_crash` callback, no auto-relaunch, unlike
  `FFmpegRecorderAdapter`'s `_watchdog_loop`.
- **Why:** A dead per-monitor preview process leaves that tile frozen in the UI
  with no error state — misleading, though it doesn't affect actual recorded
  footage.
- **Fix direction:** add the same watchdog/relaunch pattern `recorder_adapter.py`
  already has.
- **Depends on:** none.

### 23. MJPEG stream handler's catch-all logs nothing
- **What:** `mjpeg_server_adapter.py:275-276` — `except Exception: pass` with a
  comment but zero logging, the only such case in the codebase.
- **Why:** A genuine bug (not just a client disconnect) is fully invisible.
- **Fix direction:** add `logger.debug(...)` at minimum, matching the rest of
  the codebase's catch-all convention.
- **Depends on:** none — one-line fix.

### 24. `DeliveryApi._active_operator` masks request-store errors as "no active operator"
- **What:** `app/core/api/delivery_api.py:138-148` — swallows any exception from
  `load_all()`, silently delivering clips to a folder path missing the operator
  segment.
- **Why:** Clips land in the wrong/shared delivery folder with no indication why.
- **Fix direction:** log at `warning` with `exc_info=True` at minimum; consider
  surfacing a delivery-path warning in the UI when this fallback triggers.
- **Depends on:** none.

### 25. Device identity key ACL hardening is silent best-effort
- **What:** `app/adapters/browser_local/identity.py:101-133` — `icacls` failure
  to restrict the Ed25519 private key file's ACL only logs a `warning`, no
  periodic re-check.
- **Why:** On profiles where `icacls` fails (policy/redirected profile), the
  private signing key can keep a broader inherited ACL indefinitely.
- **Fix direction:** re-attempt the ACL restriction on each subsequent app start
  (cheap, idempotent) rather than only at key-creation time, so a transient
  failure self-heals instead of persisting forever.
- **Depends on:** none.

### 26. `BatchClipAnalyzer` drops failed clips with no retry or dead-letter
- **What:** `app/core/analytics/batch_clip_analyzer.py:77-86` — per-clip analysis
  exceptions are `warning`-logged and the clip is dropped, no requeue.
- **Why:** A transient failure (locked file right after a crash/restart cycle)
  permanently skips that clip's auto-analysis with nothing downstream aware.
- **Fix direction:** requeue with a small retry budget, or persist a "failed
  analysis" marker so a later pass can retry — matches the recorder's own
  retry/backoff philosophy elsewhere in the codebase.
- **Depends on:** none.

## Completed

### Track R2 — recorder supervision: ctypes orphan-fix, M1 clip-engine quick win, M5 hardening
- **What:** Full-scope investigation of the Rust recorder-supervision migration plan
  (`/plan-eng-review`'d 2026-07-11, branch `feat/f1-backend-headless`). Delivered: M0 (bench
  harness + full-scale legacy/auto baseline, 3 real monitors), the ctypes orphan-fix (spawn
  suspended → assign to Job → resume, closing the historical Popen-then-assign race in
  `recorder_adapter.py`/`process_guard.py`), M1 (`allow_threads` GIL fix in the Rust
  `compile_clip`, `CLIP_ENGINE` routing with automatic FFmpeg fallback), and M5 (`ClipBuilder`'s
  0.5s sleep-poll replaced with a `threading.Condition`, plus the ADR-0007 SLA gate resolved).
- **Why:** M2a's ctypes-vs-Rust spike (`project/tools/spike_m2a_ctypes_guard.py`) proved pure
  ctypes closes the FFmpeg-orphan race just as well as the planned Rust crate (0/500 in a rapid
  spawn+kill race test, a clean hard-kill/Job-reap test) — reusing structs already shipped in
  `process_guard.py`. User decided to close the cycle there rather than spend 5+ more weeks on
  the `watcher_recorder_guard` Rust crate (M2), its directory-watcher + parity harness (M3), and
  the wire-in + 24h soak (M4) — all **deferred indefinitely**, so `RECORDER_GUARD` is never
  introduced and there is no second supervision implementation to later remove (this is why the
  original item #9 here, "remove the legacy Python watchdog after `RECORDER_GUARD=auto` proves
  stable," no longer applies — that flag never ships).
- **Context:** Decision record: [ADR-0016](docs/architecture/adr/ADR-0016-recorder-supervision-ctypes-not-rust.md)
  (ctypes not Rust) and [ADR-0017](docs/architecture/adr/ADR-0017-adr0007-sla-verdict-confirmed.md)
  (ADR-0007 SLA gate: PASS, Track R3 not triggered — zero-copy capture CPU is 1.06-1.19% of this
  16-core machine per monitor, well under the 5% SLA). Full telemetry and methodology:
  `docs/migration/track-r2-baseline.md` and `track-r2-m2a-decision.md`. New tests:
  `test_process_guard.py::TestResumeSuspendedProcess`, `test_parity_clip_port.py`,
  `test_clip_builder_condition_regression.py`, plus extensions to `test_proc_telemetry.py` and
  `test_bench_report.py`.
- **If revisited:** only if poll-based crash/stall detection (~1s crash, ~360s stall at production
  segment durations) proves to be a real operational problem (not theoretical) — reopens with a
  fresh spike/ADR, same reopening pattern as ADR-0007 (DXGI capture).
- **Completed:** 2026-07-11 (branch `feat/f1-backend-headless`)

### Audit log for IT unlocks and role changes
- **What:** Persist an audit trail (who / when / which machine) for IT-PIN
  unlocks (`Ctrl+Alt+Shift+R`) and role changes (`setRole`).
- **Why:** The IT PIN is the *sole* gate — anyone holding it can unlock on any
  machine. For a security/monitoring tool, traceability of privilege use matters.
- **Context:** Implemented as `AuditPort` (`app/core/ports/audit_port.py`,
  ADR-0011) — `SettingsApi.set_role` / `SettingsApi.unlock_it`
  (`app/core/api/settings_api.py`) call `_audit_cmd()` for every attempt
  (success and failure), persisted via `sqlite_event_store.py`. Covered by
  `project/tests/test_audit_store.py`.
- **Completed:** v0.1.0 (2026-07-10)
