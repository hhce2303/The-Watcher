# ADR-0012 — Hexágono Rust vía PyO3 como destino (extiende ADR-0006)

- **Estado**: Aceptado (destino comprometido; R1 con prerequisito)
- **Fecha**: 2026-06-30
- **Origen**: `/plan-eng-review` — decisión del owner (postura A) sobre el hallazgo F7
- **Extiende**: [ADR-0006](ADR-0006-rust-segment-engine.md) (motor de segmentos Rust)
- **Docs**: [how-to portar a Rust](../../migration/howto-port-to-rust.md) · [matriz de puertos](../../migration/reference-target-architecture.md#matriz-de-tecnología-por-puerto-destino-rust--track-r)

## Contexto

Con la migración a Tauri, el backend Rust del shell podría quedar como mero *glue* mientras Python
concentra la lógica — una asimetría que el owner rechazó. [ADR-0006](ADR-0006-rust-segment-engine.md)
ya estableció Rust (PyO3 + maturin) como componente de core para el motor de segmentos, con
`SegmentCompilerPort` y fallback FFmpeg. La pregunta es hasta dónde llega Rust.

Motivaciones (bundle/memoria, remoto/móvil) apuntan a que, a largo plazo, eliminar Python y colapsar
todo en un binario Tauri+Rust es lo más alineado.

## Decisión

**El destino es un hexágono Rust:** Rust dueño del core y de los driven adapters, invocados como
**comandos Tauri nativos**; Python es andamiaje transitorio que se retira al alcanzar paridad.

- **Mecanismo:** **PyO3 in-process**, port por port detrás de los `core/ports/*` existentes (mismo
  patrón que [`adapters/native/rust_segment_compiler.py`](../../../app/adapters/native/rust_segment_compiler.py)).
  Rust **no** es un shell: los puertos son la costura por la que entra.
- **Orden:** `RecorderPort`+`ClipPort` (crítico, always-on) → `EditorExportPort` →
  `PlayerPort`/`MonitorPort` → `Storage`/`EventStore`/`UserConfig` → `RequestPort` → `CloudSharePort`
  (último o queda plugin, por ser I/O-bound).
- **Colapso final (R4):** cuando los adapters críticos son Rust, se reescriben los servicios de
  aplicación a Rust; el Facade pasa a comandos Tauri nativos y `adapters/ipc` + el sidecar Python
  **desaparecen** → binario único, sin serialización IPC.
- **Track R corre después del cutover F3**, no en paralelo a la reescritura de UI (F2), para no
  diluir el equipo.

## Consecuencias

- ✅ Un solo lenguaje dueño del hexágono en el estado final; binario mínimo, mejor perf, y base para
  target móvil (lógica portable).
- ✅ Cada puerto migrado aporta valor por sí solo (perf/footprint) y se puede pausar sin dejar el
  sistema a medias; el fallback Python mantiene el arranque.
- ➖ **Riesgo F7 (confianza 9/10):** el scaffold [`native/watcher_segments`](../../../native/watcher_segments)
  está en `ENGINE_READY=false`, con `mpeg2ts-reader`/`muxide` **comentadas**, sin tests, y la dev box
  **no tiene `cargo`/`rustc`**. No es una semilla probada.
- ➖ **Prerequisito para arrancar R1** (no negociable): (a) toolchain Rust en el build
  (`setup_env.ps1`/`build.ps1`), (b) spike que pruebe mux/demux MPEG-TS→MP4 frame-exact con
  **paridad** vs FFmpeg, y (c) un owner con experiencia Rust.
- ➖ Compromiso de fondo multi-trimestre sobre un equipo hoy Python/Qt; se acota con la suite Python
  como oráculo de paridad y el flag `ENGINE_READY` por puerto.

## Evidencia externa (investigación 2026-07)

Refina la matriz de puertos (detalle + fuentes en
[tech-debt-and-best-practices](../../migration/tech-debt-and-best-practices.md)):
- **`windows-capture`** ofrece bindings **Rust Y Python (PyO3) en un solo codebase**, sobre WGC + DXGI
  Desktop Duplication → semilla ideal para `RecorderPort` (adoptable desde Python hoy).
- **`shiguredo_mp4`** (Rust zero-dep, Sans-I/O, **HEVC nativo** `hev1`/`hvc1`) es candidato para el
  mux de `ClipPort`, alternativa al `muxide` comentado en `watcher_segments`.
- ⚠️ **`ffmpeg-next` en modo mantenimiento** (TD-4) — preferir crates puros si se puede.
- `maturin` auto-detecta pyo3 → sin config extra para exponer el crate como wheel.
