# ADR-0017 — ADR-0007 gate resolved: capture CPU confirmed within SLA, Track R3 not triggered

- **Estado**: Aceptado
- **Fecha**: 2026-07-11
- **Requisitos**: Track R2 M0 telemetry (`track-r2-baseline.md`), M5 gate (ADR-0007 decision point)

## Contexto

[ADR-0007](ADR-0007-dxgi-capture-deferred.md) deferred the Rust capture port (`windows-capture` +
Media Foundation, Track R3) pending profiling evidence that capture CPU is the actual bottleneck.
[ADR-0014](ADR-0014-zerocopy-qsv-capture-pipeline.md) shipped the zero-copy D3D11→QSV pipeline
(now the `CAPTURE_PIPELINE=auto` default) based on a single-monitor, 20-second synthetic benchmark
showing ~0.21-0.26 cores/monitor. Track R2's plan (M5) made this ADR-0007 gate explicit: "con
telemetría M0/M4, evaluar CPU de captura vs SLA ≤5%/monitor. Solo un FAIL documentado escala el
port de captura ... como Track R3."

The SLA (`ffmpeg-pipeline-optimization-research.md` §, restated in ADR-0014) is **≤5% of the
machine's total CPU per recorder** — not 5% of one core. On this dev machine (16 logical cores),
that means each recorder must use ≤0.80 cores (≤80% in `psutil.cpu_percent()`'s per-core-normalized
units) to pass.

## Evidence

Track R2 M0's full-scale bench (`docs/migration/track-r2-baseline.md`): 3 real concurrent
monitors, 20-minute steady-state, under crash/churn stress — not a synthetic single-monitor
snapshot.

| Pipeline | CPU/monitor (mean, % of 1 core) | % of this 16-core machine |
|---|---:|---:|
| `legacy` (CPU download every frame) | 112-148% | **7.0-9.3%** |
| `auto` (zero-copy, the shipped default) | 17-19% | **1.06-1.19%** |

`legacy` exceeds the 5% SLA — expected and unsurprising, since it is not the shipped default
(exists only as an explicit rollback: `CAPTURE_PIPELINE=legacy`). **`auto`, the pipeline every
real deployment actually runs, passes with 4-5x headroom** (1.06-1.19% vs the 5% ceiling), now
confirmed at real production scale rather than only in ADR-0014's isolated single-monitor
benchmark — multi-monitor concurrency and 20 minutes of real crash/churn stress introduced no
CPU regression versus the original single-monitor measurement (which was actually slightly higher,
~21-26% of one core vs this run's ~17-19%).

## Decisión

**No escalar el port de captura Rust (Track R3).** The ADR-0007 gate condition ("solo un FAIL
documentado escala...") is not met — this is a documented PASS. `windows-capture` + Media
Foundation remains deferred exactly as ADR-0007 already stated; this ADR closes the specific
M5 gate the Track R2 plan required, with real telemetry instead of a hypothetical.

Track R2's M2-M4 (which would have produced additional M4 telemetry for this same gate) were
independently deferred per [ADR-0016](ADR-0016-recorder-supervision-ctypes-not-rust.md) — this
verdict rests on M0's data alone, which is sufficient: the gate question is about *capture*
CPU (zero-copy pipeline, ADR-0014), which M2-M4 (recorder *supervision* — process lifecycle, not
the capture filtergraph) would not have changed regardless.

## Consecuencias

- ✅ Track R3 (Rust capture port) stays deferred with empirical, production-scale justification —
  no speculative Rust investment for a problem that measurably doesn't exist today.
- ✅ Closes the last open M5/Track R2 gate — Track R2's revised scope (M0, M1, ctypes orphan-fix,
  M5) is now fully delivered.
- ➖ `legacy` pipeline CPU (7-9.3% of this machine) is informational only — it is not the shipped
  default and no action is needed, but it quantifies exactly why ADR-0014's zero-copy pipeline
  was worth building.
- 🔁 If a FUTURE fleet machine's real-world telemetry (not this dev box) shows `auto` CPU
  approaching or exceeding 5%/monitor (e.g. many more monitors, a much weaker iGPU, or a codec
  change), this ADR is reopened with fresh telemetry — same reopening pattern ADR-0007 already
  established.
