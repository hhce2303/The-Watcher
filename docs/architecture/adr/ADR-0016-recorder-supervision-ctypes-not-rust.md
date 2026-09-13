# ADR-0016 — Recorder supervision: ctypes orphan-fix instead of a Rust crate (Track R2 M2-M4 deferred)

- **Estado**: Aceptado
- **Fecha**: 2026-07-11
- **Requisitos**: Track R2 plan (`~/.claude/plans/necesito-que-me-ayudes-wobbly-treehouse.md`), M2a spike

## Contexto

Track R2's plan proposed a Rust crate (`watcher_recorder_guard`, M2-M4, ~5 weeks) to fix a
documented race: `recorder_adapter.py` calls `subprocess.Popen(cmd)` (the FFmpeg child starts
running immediately), then `assign_to_job(proc)` afterward (`process_guard.py`) — a window where
the owning Python process could die before the child is ever a Job member, leaking it as a
permanent orphan (`monitor_worker.py:82-85` / `supervisor.py:159-170`). The plan's original
justification for Rust: `std::Command` never exposes the new process's thread handle, so nothing
can spawn suspended, assign to a Job, then resume.

The M2a spike (`/plan-eng-review` cross-model tension, see `track-r2-m2a-decision.md`) questioned
this: `process_guard.py` already makes raw ctypes Win32 calls (`OpenProcess`,
`AssignProcessToJobObject`) in this exact codebase — the "thread handle" limitation is a
`std::Command`/`subprocess.Popen` standard-library gap, not a Windows one. `CreateProcessW`,
called directly via ctypes (bypassing `subprocess` entirely), returns both the process AND thread
handles, closing the same gap Rust would have closed.

## Spike results (`project/tools/spike_m2a_ctypes_guard.py`, 2026-07-11, this machine)

- x500 rapid spawn+kill race (kill 0-10ms after `CreateProcessW`, before/after `ResumeThread`):
  **0 orphans, 0 spawn failures.**
- Hard-kill/Job-reap test (`os._exit(1)` on the owning process, zero cleanup): **PASS** — the
  child was reaped by `KILL_ON_JOB_CLOSE` alone.
- The ctypes code stayed bounded: 3 of 5 struct definitions are copied verbatim from the
  already-shipped `process_guard.py`; the only new ones (`STARTUPINFOW`, `PROCESS_INFORMATION`)
  are standard, well-documented Win32 structures.

Per the plan's own decision rule (`track-r2-m2a-decision.md`), both conditions for "Rust is no
longer needed for the orphan fix" were met.

## Decisión

**Cerrar el ciclo con el fix ctypes + M0 + M1.** El fix estructural (spawn-suspendido →
assign-to-Job → ResumeThread, reemplazando el patrón `Popen()`-luego-`assign_to_job()` actual)
se promueve del spike a `recorder_adapter.py`/`process_guard.py` como código de producción.
**Se difiere M2-M4 completos** (el crate `watcher_recorder_guard`, el directory-watcher de
`watch.rs`, y el wire-in `RECORDER_GUARD=auto` con soak de 24h) — el único ROI restante de esas
milestones sería la latencia event-driven (crash detection <50ms vía `WaitForSingleObject` /
segment-ready <50ms vía `ReadDirectoryChangesW`, frente a hoy ~1s poll-based), que el usuario
decidió no justifica 5+ semanas adicionales de crate Rust + toolchain + packaging para una
herramienta de monitoreo/grabación (no un sistema de tiempo real).

M5's `ClipBuilder` → `threading.Condition` fix (elimina el sleep-poll de 0.5s en
`_await_post_window`) es independiente de M2-M4 y se mantiene en el alcance de este ciclo.

## Consecuencias

- ✅ Cierra la fragilidad real (huérfano FFmpeg) sin comprometer 5+ semanas ni un segundo
  toolchain/crate Rust en este ciclo — reduce el alcance de 8 semanas a ~3.
- ✅ Reutiliza structs ya revisados y en producción (`process_guard.py`); el código nuevo es
  pequeño y acotado.
- ➖ No se gana la latencia event-driven sub-50ms (crash/segment detection quedan poll-based:
  ~1s hoy). Aceptable para una herramienta de monitoreo, no de tiempo real.
- ➖ `TODOS.md` #9 (borrar el watchdog Python legacy) pierde su trigger original
  (`RECORDER_GUARD=auto` estable en producción) — no aplica ya que `RECORDER_GUARD` nunca se
  introduce en este ciclo; el watchdog Python actual sigue siendo la única implementación,
  simplemente con el gap de huérfanos cerrado.
- 🔁 Si en el futuro la latencia poll-based (~1s) demuestra ser un problema real medido en
  producción (no solo teórico), este ADR se reabre con un nuevo spike de paridad —igual que
  ADR-0007 para la captura DXGI.

## Alcance revisado de Track R2 (post-ADR) — estado final del ciclo

| Milestone | Estado |
|---|---|
| M0 — baseline + bench harness | **Hecho** (`track-r2-baseline.md`, full-scale legacy+auto, 3 monitores reales) |
| M1 — quick win ClipPort (`allow_threads` + `CLIP_ENGINE`) | **Hecho** (parity harness verde en los 3 estados + sin `.pyd`) |
| M2a — spike ctypes vs Rust | **Hecho** (este ADR) |
| M2 — crate `watcher_recorder_guard` | **Diferido** (este ADR) |
| M3 — `watch.rs` + parity | **Diferido** (este ADR) |
| M4 — wire-in + soak 24h | **Diferido** (este ADR) |
| ctypes orphan-fix (nuevo, reemplaza M2's objetivo) | **Hecho** — promovido del spike a `recorder_adapter.py`/`process_guard.py`, validado en vivo (0 huérfanos reales tras investigar 2 falsos positivos del harness) |
| M5 — `ClipBuilder` Condition-variable | **Hecho** (`test_clip_builder_condition_regression.py`, 3 casos obligatorios) |
| M5 — gate ADR-0007 | **Hecho** — [ADR-0017](ADR-0017-adr0007-sla-verdict-confirmed.md): PASS, Track R3 no se activa |

**Ciclo Track R2 cerrado.** Alcance final: M0 + M1 + ctypes orphan-fix + M5, tal como decidió el
usuario en el gate de M2a. M2-M4 quedan diferidos indefinidamente (no en este ciclo ni el
siguiente) salvo que la latencia poll-based demuestre ser un problema real medido en producción.
