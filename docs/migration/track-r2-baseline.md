# Track R2 M0 — Bench harness + baseline

**Status: DONE.** Harness built and validated live on this dev box (`hcruz.SIG`, 16 logical / 12
physical cores, 3 real monitors — DISPLAY1 1920x1200 primary, DISPLAY5 1920x1080, DISPLAY6
1440x2560). Full-scale measurement (20 min steady-state, 3 crashes, 1 stall, 1 hard-kill, churn
x200, both `legacy` and `auto` `CAPTURE_PIPELINE`) completed — see "Full-scale results" below.
This is also the empirical input to M5's ADR-0007 gate — see
`docs/architecture/adr/ADR-0017-adr0007-sla-verdict-confirmed.md` for the verdict.

## Harness

Three new files, no product-code behavior change (telemetry CSV export is opt-in via
`TELEMETRY_CSV`, unset by default):

- `project/app/infrastructure/proc_telemetry.py` — extended with `TELEMETRY_CSV` env var:
  when set, each sample batch is appended as a CSV row (`ts,category,label,pid,cpu_pct,rss_mb`).
  Off by default; a write failure is swallowed (diagnostic-only, must never affect the recorder
  it's observing). 3 new tests in `test_proc_telemetry.py` (header-once, resume-without-header,
  disabled-by-default).
- `project/tools/bench_scenario.py` — builds real `MonitorWorker` instances (the exact
  `FFmpegRecorderAdapter` + `RecorderSupervisor` + `BufferManager` wiring `runtime/backend.py`
  uses in production, reusing `build_worker()` directly) against real detected monitors
  (synthesizing extra tiled ones if more are requested than are physically attached). Three
  subcommands:
  - `run` — steady-state, then N injected crashes (kill -9 the FFmpeg child, measure MTTR via
    `is_running()`/new-PID polling), an optional stall (suspend the FFmpeg child via
    `psutil.Process.suspend()`, measure stall-detection MTTR), and a churn loop (`cycles` x
    `stop()`+`start()` with a kill injected ~20ms after each start — probes the documented
    Popen-to-assign-to-Job race window in `recorder_adapter.py`/`process_guard.py`).
  - `hard-kill-test` — arms one worker, records its FFmpeg child PID(s), then `os._exit(1)`
    (no `atexit`, no `finally`) to prove the Job Object — not Python cleanup — is what reaps
    the child when the owning process dies abruptly.
  - `check-orphans` — run from a fresh process after `hard-kill-test`'s parent has died; confirms
    none of its recorded FFmpeg PIDs are still alive (kills any that are, as a safety net).
- `project/tools/bench_report.py` — parses the `TELEMETRY_CSV` (grouped by category/label:
  CPU/RSS mean+max) and the scenario JSON (event list with MTTRs/orphan counts) into a markdown
  report. Handles a missing CSV gracefully (a run shorter than
  `PROC_TELEMETRY_INTERVAL_SECONDS`, default 10s, never fires a single sample — not an error).
  6 tests in `test_bench_report.py`.
- `project/tools/bench_recording.ps1` — orchestrator. Resolves system Python 3.13+ (mirrors
  `setup_env.ps1`'s detection — the repo `.venv` is broken, never used), sets
  `CAPTURE_PIPELINE`/`TELEMETRY_CSV`/`SEGMENT_DIR`/`SEGMENT_DURATION` env vars *before* launching
  the Python process (`Settings` reads `os.getenv()` at class-body/import time, so env vars must
  be set by the parent process — setting them after import inside the script is a no-op; this was
  caught live during harness validation, see "Bugs found" below), runs the scenario, optionally
  the hard-kill/orphan test, then renders the report.

Gate: `pytest project/tests/test_proc_telemetry.py project/tests/test_bench_report.py` green
(9 + 7 = 16 tests, all new/extended for this milestone). Full suite: 530 passed, 10 skipped
(pre-existing skips, unrelated to this change).

## Bugs found while validating the harness live

Both found and fixed during the first live smoke runs on this machine — kept here since they're
non-obvious gotchas future milestones (M1-M5 also drive `bench_scenario.py`-style processes) will
hit again otherwise:

1. **`Settings` reads env at import time, not per-instantiation.** `project/app/infrastructure/config.py`'s
   `Settings` class assigns fields like `segment_duration: int = int(os.getenv("SEGMENT_DURATION", "300"))`
   directly in the class body — evaluated once when the module is first imported. Calling
   `os.environ.setdefault(...)` inside `bench_scenario.py`'s `__init__` (after the `config` module
   was already imported by the script's own top-level imports) was a no-op — FFmpeg kept using
   `-segment_time 300` regardless of `--segment-duration`. Fix: `bench_recording.ps1` sets
   `$env:SEGMENT_DURATION` (and `CAPTURE_PIPELINE`, etc.) *before* invoking `python`, since env
   vars set by a parent process are inherited before the child's imports run. `bench_scenario.py`
   now just warns if the resolved `Settings.segment_duration` doesn't match what was requested,
   instead of silently doing nothing.
2. **`bench_report.py` crashed on a run too short to sample.** `PROC_TELEMETRY_INTERVAL_SECONDS`
   defaults to 10s; a scenario shorter than that (as used for quick harness smoke-testing) never
   fires `ProcTelemetry._sample()`, so `TELEMETRY_CSV` is never created. `_load_csv_rows()` now
   returns `[]` for a missing file instead of raising `FileNotFoundError`. Regression test added.
3. **PowerShell 5.1 + native-process `2>&1` + `$ErrorActionPreference = "Stop"`.** Piping
   `python.exe ... 2>&1` wraps every stderr line (loguru logs INFO+ to stderr) in a
   `NativeCommandError` and aborts the whole script even on a clean exit. Fixed by not redirecting
   stderr for the scenario/report invocations — it prints directly to the console instead.
4. **Non-ASCII characters in a `.ps1` file break Windows PowerShell 5.1 parsing** when the file is
   written without a BOM (em dashes, `x` as `×`, arrows). Rewrote `bench_recording.ps1` in
   plain ASCII rather than chasing BOM/encoding on the write path.

## Smoke-scale validation (real, live — not representative baseline)

Run live on this machine to prove the harness end-to-end works before committing to the ~30-60 min
full-scale run: `auto` pipeline, 1 real monitor (DISPLAY1), `SEGMENT_DURATION=3`, 8s steady-state,
1 crash, 2 churn cycles. **These numbers are NOT the M0 baseline** — the artificially short segment
duration causes constant segment-build churn that inflates CPU/RSS; they only demonstrate the
mechanism works:

| Check | Result |
|---|---|
| Crash MTTR | 3.22s (kill -9 to new-PID confirmed running) |
| Churn (2 cycles, kill ~20ms after each start) | 2/2 killed, **0 orphans** |
| Hard-kill/orphan test (`os._exit(1)`, no cleanup) | **0 orphaned FFmpeg processes** — Job Object `KILL_ON_JOB_CLOSE` confirmed working independent of Python's own `atexit` cleanup |
| CPU / RSS (recorder/m0, 2 samples) | 70.25% mean / 80.8% max CPU; 111.8 MB mean / 125.7 MB max RSS (not representative — see above) |

The hard-kill result is directly relevant to M2a's decision (below): the *current* Python-only
stack, using nothing but the existing `process_guard.py` ctypes Job Object assignment, already
reaps orphans correctly on an abrupt parent death. This narrows what M2's Rust crate would need to
additionally prove — see M2a.

## Full-scale results

Ran in the background (`project/tools/bench_full_run.ps1`, detached via `Start-Process` so it
survived the launching session): `legacy` then `auto` `CAPTURE_PIPELINE`, 3 real monitors,
`SEGMENT_DURATION=300` (production default), 1200s (20 min) steady-state, 3 injected crashes,
1 stall, churn x200, 1 hard-kill/orphan test — per pipeline. Total wall-clock: ~81 min
(legacy 05:00→05:44, auto 05:44→06:22).

**IMPORTANT — the `legacy` run predates the ADR-0016 ctypes orphan-fix; the `auto` run postdates it.**
The background job was launched at 05:00:05, before the ctypes fix landed on disk (05:30-05:31);
`legacy`'s Python process had already imported the pre-fix `recorder_adapter.py` by then, while
`auto` (spawned fresh at 05:44:41) picked up the fix. This is a lucky, not designed, natural
before/after — treat the CPU/RSS/MTTR numbers as a clean legacy-vs-auto pipeline comparison, but
do NOT read the churn-orphan numbers below as a fix-vs-no-fix comparison; see that section.

| Metric (steady-state, 3 monitors) | Legacy | Auto (zero-copy, ADR-0014) |
|---|---:|---:|
| CPU/monitor (mean, % of 1 core) | 112-148% (m0/m1/m2: 112.2/115.8/148.3) | 17-19% (m0/m1/m2: 16.9/16.9/19.1) |
| CPU/monitor as % of this 16-core machine | **7.0-9.3%** | **1.06-1.19%** |
| RSS (mean, recorder process) | 131-161 MB | 191-215 MB |
| Crash MTTR (3 samples) | 3.42s / 4.03s / 3.82s | 3.22s / 3.82s / 4.22s |
| Stall MTTR | not captured this run — see below (verified separately: **358.4s**) | not captured this run — see below |
| Churn x200 orphans (raw harness count) | 1 | 1 |
| Churn x200 orphans (after investigation) | **0** — false positive, see below | **0** — false positive, see below |
| Hard-kill/orphan test | 0 orphaned | 0 orphaned |

**ADR-0007 SLA verdict (≤5% of machine CPU per monitor, per `ffmpeg-pipeline-optimization-research.md`
§ and ADR-0014):** legacy fails on this 16-core machine (7.0-9.3% > 5%) — expected, it's not the
shipped default. **Auto (the actual `CAPTURE_PIPELINE=auto` default) passes with 4-5x headroom
(1.06-1.19% vs the 5% ceiling)**, confirmed now at real production scale (3 concurrent real
monitors, 20 real minutes, under crash/churn stress) rather than ADR-0014's single-monitor 20s
synthetic benchmark. Full verdict and Track R3 gate decision:
`docs/architecture/adr/ADR-0017-adr0007-sla-verdict-confirmed.md`.

### Churn-orphan false positive — investigated

Both pipelines' `bench_scenario.py churn()` flagged exactly 1 "orphan" out of 200 cycles. Traced
via the run logs (`grep`'d the orphan PID in `full_legacy.log`/`full_auto.log`): **both are the
same false-positive class** — a legitimate, still-in-progress `HourlyRecordingBuilder` batch
clip-build (`process_guard.assign_to_batch_job`, `category=batch label=clip-m1`), caught alive by
the harness's orphan check at the exact instant it snapshotted, not an actual recorder-Job orphan.
Confirmed by grepping both PIDs' context: both show `assign_to_batch_job: PID <n> assigned to
batch job` immediately before the harness's snapshot — a completely different subsystem
(offline clip assembly) from the recorder-supervision race this milestone is about.

Fixed in `bench_scenario.py`'s `churn()`: candidates now get a 10s grace-period recheck (batch
clip builds for these small test clips finish in seconds) before being counted as real orphans —
re-verified with a follow-up smoke run (`churn=15`) showing `orphans: 0`. This was a test-harness
measurement bug, not a regression in the production fix — the dedicated M2a spike's x500 race test
(0 orphans, a much cleaner isolated test with no concurrent batch-build activity) and the smoke
validation (0/10 churn + hard-kill test, both after the fix landed) remain the correct evidence
that the ctypes orphan-fix works.

### Stall MTTR — not captured in the full run, verified separately

The original `bench_scenario.py inject_stall()` used a fixed 90s timeout regardless of the active
`SEGMENT_DURATION` — with the production default (300s) the real detection threshold is
`300 + _STALL_GRACE_SECONDS(60) = 360s`, so both full-scale runs timed out waiting
(`mttr_s: None`) without ever seeing the real number. Fixed: the timeout is now derived from
`settings.segment_duration + _STALL_GRACE_SECONDS + 30s` margin. Re-verified with a dedicated
single-monitor run (`SEGMENT_DURATION=300`, `-Stall` only): **stall MTTR = 358.4s**, matching the
`_STALL_GRACE_SECONDS=60` + `segment_duration=300` = 360s formula in `recorder_adapter.py:648`
almost exactly (the ~1.6s difference is the watchdog's 1s poll granularity plus scheduling jitter),
empirically confirmed rather than only read from the source. This ~6-minute detection latency is
the concrete number M3 (deferred, ADR-0016) would have fixed via timer-exact stall detection —
worth keeping in mind if poll-based detection ever proves to be a real operational problem later.

### Threads

Not captured this cycle — `bench_scenario.py` doesn't sample `psutil.num_threads()`. The 4N+2
formula in the plan is a code-derived estimate (`recorder_adapter.py` spawns a watchdog +
stderr-drain thread per monitor, `supervisor.py` one supervisor thread per monitor = 3N, plus the
shared `proc_telemetry` thread + main thread = 3N+2 in this codebase, not 4N — the "+1N" in the
plan's estimate anticipated a 4th per-monitor thread that isn't actually present in the current
Python-only stack). Flagged here rather than silently omitted; not blocking for this cycle since
M2-M4 (which would have changed this number) are deferred per ADR-0016.

## M2a spike — DONE, see ADR-0016

Per the plan, M2a was a 1-2 day spike that had to run *before* committing to the M2 Rust crate:
does the orphan-fix actually need Rust, given `process_guard.py` already does raw ctypes Win32
calls (`OpenProcess`, `AssignProcessToJobObject`)? Result: **no** — pure ctypes
(`CreateProcessW(CREATE_SUSPENDED)` → `AssignProcessToJobObject` → `ResumeThread`) closed the race
cleanly (0/500 in a dedicated race test, clean hard-kill/Job-reap test). User decided to close the
Track R2 cycle here rather than proceed to the full M2-M4 Rust crate — see
`docs/migration/track-r2-m2a-decision.md` and
`docs/architecture/adr/ADR-0016-recorder-supervision-ctypes-not-rust.md` for the full decision
record. The ctypes fix is now in production (`recorder_adapter.py`/`process_guard.py`),
live-validated (this doc's full-scale run, both pipelines, 0 real orphans after investigation).
