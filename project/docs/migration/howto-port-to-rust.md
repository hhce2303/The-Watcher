# How-to — Portar un driven port a Rust vía PyO3 (Track R)

Cómo mover la implementación de un `core/ports/*` de Python a Rust sin que el resto del sistema se
entere, con tests de paridad. Al terminar, un puerto corre en Rust detrás de la misma interfaz, y se
activa solo cuando iguala al oráculo Python.

> Track R es **post-cutover** (después de F3). Reusa el patrón ya establecido por
> [ADR-0006](../editing/adr/ADR-0006-rust-segment-engine.md) (`SegmentCompilerPort` + `.pyd` PyO3 +
> fallback FFmpeg). Ver [ADR-0012](../editing/adr/ADR-0012-rust-hexagon-endgame.md).

## Prerequisitos (bloqueantes para arrancar R1)

- **Toolchain Rust en el build:** `rustup` + MSVC + `maturin` en `setup_env.ps1`/`build.ps1`. Hoy la
  dev box **no tiene** `cargo`/`rustc` — instalarlo es prerequisito.
- Un **owner con experiencia Rust**.
- Para `RecorderPort`/`ClipPort`: un spike que pruebe mux/demux MPEG-TS→MP4 **frame-exact con
  paridad** vs FFmpeg (el scaffold `native/watcher_segments` está en `ENGINE_READY=false`, con
  `mpeg2ts-reader`/`muxide` comentadas).

## Orden (de la matriz de puertos)

`RecorderPort` + `ClipPort` (primero) → `EditorExportPort` → `PlayerPort`/`MonitorPort` →
`Storage/EventStore/UserConfig` → `RequestPort` → `CloudSharePort` (último o queda plugin). Ver
[matriz completa](reference-target-architecture.md#matriz-de-tecnología-por-puerto-destino-rust--track-r).

## Pasos

1. **Confirma el puerto y su Protocol.** Abre `project/app/core/ports/<port>.py`. El puerto es la
   frontera estable: la firma no cambia.

2. **Implementa el crate Rust.** Extiende `project/native/watcher_segments/` (Cargo + maturin) o crea
   un crate hermano. Compila a `.pyd` con PyO3. Sin DLLs externas si puedes (crates puros), para no
   romper la detección de PyInstaller.

3. **Escribe el adapter Python que carga el `.pyd`** e implementa el Protocol del puerto — igual que
   `adapters/native/rust_segment_compiler.py`. Mantén el adapter Python (FFmpeg) como **fallback**
   detrás del mismo puerto.

4. **Añade el flag de activación** (patrón `ENGINE_READY`): el selector usa Rust si el `.pyd` está y
   el flag está ON; si no, cae al fallback. La app arranca aunque falte el `.pyd`.

5. **Tests de paridad.** Usa la suite Python existente como **oráculo**: el output del adapter Rust
   debe ser idéntico (checksums/duración/frames) al del Python para las mismas entradas. **No actives
   el flag hasta que pase.**

## Verificación

- `cargo test` verde en el crate; `pytest` verde con el adapter Rust activado.
- Paridad byte/frame contra el oráculo Python en casos reales.
- El bundle sigue arrancando con y sin el `.pyd` (fallback intacto).

## Troubleshooting

- **PyO3 no encuentra libpython:** issue conocido con python-build-standalone; fija el intérprete o
  usa maturin como en el patrón ADR-0006.
- **DLLs transitivas del `.pyd` no empaquetan:** prefiere crates puros; si no, añade los binarios al
  `.spec` de PyInstaller explícitamente.
- **El puerto es I/O-bound (Cloud/Request):** cuestiona si vale portarlo — puede quedarse en Python o
  como plugin Tauri; Rust rinde donde hay CPU/latencia (grabación/segmentos), no en I/O de red.

## El colapso final (R4)

Cuando los adapters críticos son Rust, se reescriben los servicios de aplicación a Rust y el Facade
pasa a **comandos Tauri nativos**: `adapters/ipc` y el sidecar Python **desaparecen** → binario
único, sin serialización IPC. Es el estado final del hexágono Rust.

## Relacionado
- [ADR-0012](../editing/adr/ADR-0012-rust-hexagon-endgame.md) · [ADR-0006](../editing/adr/ADR-0006-rust-segment-engine.md) · [Referencia — Matriz de puertos](reference-target-architecture.md)
