# Track R2 M2a spike — ctypes vs Rust decision

**Status: spike complete, empirical results in. Decision on the bifurcation below is pending
user input — this is a scope/timeline tradeoff (event-driven latency gains vs 5+ more weeks of
Rust crate work), not an engineering correctness question, so it isn't decided unilaterally here.**

## Question

M2's original justification for a Rust crate was: "`std::Command` doesn't expose the new
process's thread handle, so we can't spawn suspended, assign to a Job, then resume — Rust's
`windows` crate can." The M2a re-review (Eng Review / Outside Voice) flagged that this is a
limitation of the Rust/Python **standard library**, not of Windows — `process_guard.py` already
makes raw ctypes Win32 calls (`OpenProcess`, `AssignProcessToJobObject`) in this exact codebase.
Before committing weeks 3-4 to the full crate, spike whether pure ctypes (bypassing `subprocess`/
`std::Command` entirely, calling `CreateProcessW` directly) closes the orphan race just as well.

## Spike: `project/tools/spike_m2a_ctypes_guard.py` (discardable, not shipped)

Mechanism: `CreateProcessW(CREATE_SUSPENDED)` → `AssignProcessToJobObject` (while still suspended)
→ `ResumeThread`. Because `CreateProcessW` returns both the process AND thread handles in its
`PROCESS_INFORMATION` out-param (unlike `subprocess.Popen`, which only gives you the process
handle), there is no window where the child can run — spawn descendants, exit, or otherwise
escape — before it is a Job member. This is the *exact* mechanism M2 planned to implement in Rust,
done here in ~250 lines of pure ctypes, three of whose five struct definitions
(`_BasicLimitInfo`, `_IoCounters`, `_ExtendedLimitInfo`) are copied verbatim from the
already-shipped `process_guard.py` — the only genuinely new structs are the two standard,
well-documented `STARTUPINFOW`/`PROCESS_INFORMATION`.

## Empirical results (this machine, `hcruz.SIG`, 2026-07-11)

| Test | Result |
|---|---|
| x500 rapid spawn+kill race (kill 0-10ms after `CreateProcessW`, before or shortly after `ResumeThread`) | **0/500 orphans, 0 spawn failures** |
| Hard-kill/Job-reap test (`os._exit(1)` on the owning process, zero cleanup, zero `atexit`) | **PASS — child reaped by `KILL_ON_JOB_CLOSE`, no Python cleanup involved** |

Both match the smoke-scale result already recorded in `track-r2-baseline.md` (0 orphans from the
`bench_scenario.py` hard-kill test using the *existing* Popen-then-assign pattern) — i.e. even
today's un-fixed gap didn't reproduce on this machine's timing, and the *structurally closed*
ctypes version is unconditionally race-free by construction (not just empirically lucky), since
the child cannot execute any code until after Job assignment.

## Decision criteria (per the plan)

> Si el spike cierra la carrera de forma limpia Y el código ctypes queda legible/acotado → la
> justificación de Rust para M2 se reduce a las ganancias de latencia event-driven (crash <50ms
> vía `WaitForSingleObject`, segment-ready <50ms vía RDCW) frente al equivalente en `pywin32`, NO
> al fix de huérfano en sí (que ctypes ya resuelve).

Both conditions are met: the race closed cleanly (0/500), and the ctypes code stays bounded —
no new fragile struct sprawl beyond what's already shipped and reviewed in `process_guard.py`.
**This means M2's crate is no longer justified by the orphan fix itself — only by whether the
event-driven latency wins (crash detection <50ms vs today's ~poll-based ~1s; segment-ready <50ms
vs ~1s glob) are worth 5+ more weeks of Rust crate work (M2-M4).**

## Bifurcation (per the plan — user decision needed)

- **Close the cycle now:** ship the ctypes orphan-fix (replace `recorder_adapter.py`'s
  `Popen()`-then-`assign_to_job()` with the suspended-spawn pattern above, promoted from spike to
  production code) + M0 + M1 (~3 weeks total instead of 8). Defer M2-M4 entirely; M5's
  `threading.Condition` fix for `ClipBuilder` is independent and could still land on its own.
  Document the decision in an ADR.
- **Proceed to M2 as planned:** the event-driven latency wins (sub-50ms crash/segment detection)
  are judged worth the remaining 5+ weeks (M2's `watcher_recorder_guard` crate, M3's directory
  watcher + parity harness, M4's wire-in + 24h soak). No changes to the plan.

Today's crash-detection latency (poll-based, `_STALL_GRACE_SECONDS=60` for stalls) is already
measured empirically: see `track-r2-baseline.md` (~1s poll cadence for crash detection; full-scale
run pending for the production-realistic number). The question is whether shaving that to <50ms
matters for a monitoring/recording tool (not a real-time system) enough to justify the remaining
schedule.
