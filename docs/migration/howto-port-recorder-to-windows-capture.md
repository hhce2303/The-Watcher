# How-to / Design — Migrar `RecorderPort` a `windows-capture` (Rust, Track R1)

> Investigación: 2 subagentes generales en paralelo (sin paso de revalidación ni cruce con
> codex), 2026-09-17. Fuentes primarias: repo GitHub `NiiightmareXD/windows-capture` (README,
> `src/settings.rs`, `src/frame.rs`, `src/monitor.rs`, ejemplos, Issues) + PyPI/`windows-capture-python`,
> más el código de este repo (`recorder_port.py`, `rust_segment_compiler.py`,
> `watcher_segments/Cargo.toml`, `buffer_manager.py`). No se usó `/browse` para la parte externa —
> el navegador headless falló con un bug de `mkdir EEXIST` en `.gstack/`; se recurrió a `gh api`/WebFetch
> como fallback. Señalarlo si se repite: puede indicar un problema de instalación de gstack a revisar.

## 0. Qué ADR autoriza esto (y qué NO cambia)

Este documento **no reabre** [ADR-0007](../architecture/adr/ADR-0007-dxgi-capture-deferred.md)/[ADR-0017](../architecture/adr/ADR-0017-adr0007-sla-verdict-confirmed.md).
Esos ADRs cerraron la pregunta de *"¿la captura es el cuello de botella de CPU?"* con un **PASS**
confirmado en telemetría de producción (pipeline `ddagrab` zero-copy, ADR-0014, a 1.06-1.19% de
16 núcleos vs SLA ≤5%). **No hay justificación de performance para portar la captura a Rust hoy.**

Lo que sí autoriza este trabajo es [ADR-0012](../architecture/adr/ADR-0012-rust-hexagon-endgame.md):
el destino final del hexágono es Rust dueño de todos los driven adapters, y **`RecorderPort` es el
primer puerto de la matriz** (junto a `ClipPort`, ya en producción vía `watcher_segments`,
`ENGINE_READY=true`). `windows-capture` es la semilla nombrada explícitamente en ADR-0012 porque
publica bindings Rust **y** Python (PyO3) desde el mismo repo, adoptable sin esperar el colapso
final. Es decir: este es trabajo de **arquitectura de destino (Track R1)**, no una respuesta a un
problema de CPU medido.

**Prerequisito bloqueante, no negociable, aún NO satisfecho en esta máquina** (ADR-0012 §Consecuencias,
`howto-port-to-rust.md` §Prerequisitos):
- ❌ `rustc`/`cargo` **no están instalados** en este dev box (verificado: `rustc --version` →
  `command not found`). Sin toolchain no hay build.
- ❌ No hay spike de paridad mux/demux frame-exact validado para captura (el de `watcher_segments`
  cubre remux/concat, no captura en vivo).
- ❌ No hay owner con experiencia Rust asignado formalmente a este puerto.

**No empieces a escribir el crate sin resolver esto primero.** El resto del documento es el diseño
para cuando esos tres puntos estén cerrados.

## 1. Qué es `windows-capture`

Crate Rust (MIT, `NiiightmareXD/windows-capture`, v2.0.1 al momento de esta investigación, activo:
506★, push hace 10 días) con bindings Python 1:1 (`windows-capture` en PyPI, vía PyO3). Desde 2.0
soporta **dos backends**:

- **WGC** (`Windows.Graphics.Capture`): captura por *item* (ventana o monitor), con composición de
  cursor y borde gestionada por el OS. API basada en trait (`GraphicsCaptureApiHandler`) +
  callback `on_frame_arrived`.
- **DDA** (`DxgiDuplicationApi`): el mismo nivel que ya usa `ddagrab` en FFmpeg — output duplication
  DXGI, pero por *polling* (`acquire_next_frame(timeout_ms)`), no callback.

**Punto clave para este proyecto: el frame puede quedarse en GPU.** `Frame::as_raw_texture()` /
`.device()` expone el `ID3D11Texture2D` directamente — la misma idea zero-copy que ADR-0014 ya
logra vía `hwmap`/`vpp_qsv` en FFmpeg, pero como API Rust nativa en vez de filtergraph.

**Gap importante, no resuelto por el crate:** el path **DDA** (el equivalente exacto a `ddagrab`)
**no tiene composición de cursor** — hay un issue abierto pidiéndolo. Es decir, adoptar DDA aquí
*reintroduce* el mismo problema que ADR-0013 resolvió (cursor separado del blit). El path **WGC**
sí compone cursor limpio vía OS, así que si se adopta este crate **el backend correcto es WGC, no
DDA**, invirtiendo la intuición de "usa la misma capa que ddagrab".

**Riesgos documentados en Issues** (no en README, hay que asumirlos): tinte rosado/distorsión de
color en algunos monitores y en captura de ventana, errores Media Foundation `0xC00D6D60`, access
violations `0xc0000005` en algunos casos de captura de ventana/fullscreen, cierre no limpio en
sistemas con iGPU, `title_bar_height` siempre en 0. Nada documentado sobre secure desktop/UAC,
contenido protegido/DRM, ni comportamiento en suspensión/tapa cerrada — falta validar en la flota
real antes de confiar en esto para producción, igual que se hizo con `ddagrab` en ADR-0013.

## 2. Arquitectura propuesta: captura en Rust, encode se queda en FFmpeg

`windows-capture` entrega frames crudos (BGRA8, GPU o CPU). `RecorderPort`
([`recorder_port.py`](../../project/app/core/ports/recorder_port.py)) necesita **archivos ya
codificados y segmentados** (`.ts` rotando) más un `preview.jpg` en vivo — exactamente lo que
`FFmpegRecorderAdapter` produce hoy con `ddagrab → hwmap/vpp_qsv → h264_qsv/hevc_qsv`
([ADR-0013](../architecture/adr/ADR-0013-ddagrab-capture-cursor-flicker.md),
[ADR-0014](../architecture/adr/ADR-0014-zerocopy-qsv-capture-pipeline.md)).

Tres opciones para cerrar esa brecha:

| Opción | Descripción | Veredicto |
|---|---|---|
| (a) Encode en Rust | Media Foundation bindings o crate encoder + muxer propio en Rust | Descartada por ahora: duplica todo el trabajo de encoder HW que FFmpeg ya resolvió (QSV/CUDA, `out_range` fix de ADR-0014), y requiere un muxer de segmentos nuevo |
| **(b) Pipe a `ffmpeg.exe` vía stdin** | Rust captura (WGC) → convierte a `rawvideo bgra` → pipe a un `ffmpeg.exe` ya corriendo con `-f rawvideo -pix_fmt bgra -i -` → mismo pipeline zero-copy QSV/CUDA de ADR-0014 sin cambios | **Recomendada** |
| (c) Buffer compartido | Rust escribe a memoria mapeada, FFmpeg lee de ahí | Más complejo que (b) sin beneficio claro |

**Por qué (b):** este repo ya trata el subproceso FFmpeg como capa de producción aceptable
(`howto-port-to-rust.md`: *"Rust rinde donde hay CPU/latencia... no en I/O"*). Con (b), Rust
**solo reemplaza el source filter** (`ddagrab` → WGC), resolviendo el gap de cursor de DDA sin
tocar nada de la lógica de segmentación/preview/rotación ya validada. El encode zero-copy GPU de
ADR-0014 queda intacto. Full-encode-en-Rust queda como paso futuro, solo si (b) demuestra que el
pipe a stdin es en sí mismo el nuevo cuello de botella (deberá medirse, no asumirse — mismo
estándar de evidencia que ADR-0007/ADR-0017).

## 3. Dónde vive el crate

**Crate hermano nuevo**: `project/native/watcher_capture/`, **no** dentro de
[`watcher_segments/`](../../project/native/watcher_segments/Cargo.toml). `watcher_segments` está
acotado a demux/mux sin pérdida (`mpeg2ts-reader`, `shiguredo_mp4`) — mezclar ahí un crate de
captura en vivo con manejo de proceso rompe la separación de responsabilidades y complica el
gating `ENGINE_READY` **independiente por puerto** que pide `howto-port-to-rust.md` paso 4.

Mismo esqueleto Cargo que el crate existente:

```toml
[lib]
crate-type = ["cdylib", "rlib"]

[dependencies]
pyo3 = { version = "0.22", features = ["extension-module"] }
windows-capture = "=2.0.1"   # pinned, igual que mpeg2ts-reader/shiguredo_mp4
```

`maturin` autodetecta PyO3 sin config adicional (mismo patrón que ya usa `watcher_segments`).

## 4. Threading / lifecycle

`windows-capture` corre su propio hilo de captura del OS con callback por frame. El adapter Python
debe mapear `start()`/`stop()`/`is_running()` de `RecorderPort` así:

- `start(output_dir)`: lanza el hilo de captura (+ el feeder que escribe a stdin de `ffmpeg.exe`)
  en background desde Rust, y **retorna inmediatamente** a Python.
- Estado compartido (`running: bool`, handle del proceso ffmpeg, contador de frames) en
  `Arc<Mutex<...>>`, igual que expone `rust_segment_compiler.py` — `is_running()` es un lock+read.
- Cualquier llamada bloqueante desde Python (`stop()` esperando el join del hilo) debe soltar el
  GIL (`py.allow_threads(...)`), igual que hace `compile_clip` en `watcher_segments/src/lib.rs` —
  si no, se congela el servidor IPC mientras se detiene la grabación.

## 5. Rotación de segmentos y paridad

El nuevo pipeline sigue respetando `segment_floor`
([`buffer_manager.py:79`](../../project/app/core/recording_service/buffer_manager.py#L79)): un
cambio de monitor/resolución debe seguir invalidando segmentos de dimensión incompatible, sin
tocar ese hook. Bajo la opción (b), la rotación y el `preview.jpg` siguen siendo responsabilidad de
FFmpeg — no hay lógica nueva que portar ahí.

**Tests de paridad** (mismo patrón que `howto-port-to-rust.md` pasos 3-5): el adapter
`ddagrab`/FFmpeg actual es el **oráculo**. Antes de activar cualquier flag, comparar
checksum/duración/frame-count entre segmentos alimentados por WGC vs por `ddagrab`, para las mismas
entradas.

## 6. Activación (patrón `ENGINE_READY`)

Reutilizable directamente del patrón ya en producción en `rust_segment_compiler.py`: un flag
`CAPTURE_ENGINE_READY` en el `#[pymodule]` del nuevo crate, y un factory
(`make_recorder(prefer_rust=True)`) que elige el adapter Rust/WGC solo si el `.pyd` está presente
**y** el flag está en `true`; si no, cae al `FFmpegRecorderAdapter` (`ddagrab`/zero-copy) actual.
**No mover el flag a `true` hasta que la suite de paridad + smoke del editor pasen en verde** — la
misma disciplina que se siguió para `ENGINE_READY` del motor de segmentos.

## 7. Empaquetado

`watcher_segments` solo usa crates puro-Rust (comentario en su `Cargo.toml`: *"no external DLLs →
clean PyInstaller bundle"*). `windows-capture` envuelve APIs Win32 (WGC/DXGI vía `windows-rs`) sin
dependencias de terceros nuevas — usa `d3d11.dll`/`dxgi.dll` del sistema, que **ya son una
dependencia implícita hoy** vía `ddagrab`. Riesgo de detección de PyInstaller bajo, pero es un
`.pyd` nuevo: aplica la misma disciplina de `externalBin` con sufijo `-<target-triple>` (TD-6) y
`.spec` explícito si algo no se autodetecta.

## 8. Orden concreto de arranque (cuando los prerequisitos del §0 estén cerrados)

1. Instalar toolchain Rust (`rustup` + MSVC + `maturin`) en `setup_env.ps1`/`build.ps1`.
2. Asignar owner con experiencia Rust a este puerto.
3. Spike aislado: capturar 60s con `windows-capture` (backend **WGC**, no DDA) en Python puro
   (sin este repo), medir CPU/GPU y confirmar que no hay flicker de cursor ni los issues de color
   reportados en la sección 1, en la máquina de referencia real (Intel Iris Xe).
4. Si el spike pasa: crear `project/native/watcher_capture/`, adapter Python, tests de paridad
   contra el oráculo FFmpeg, flag `CAPTURE_ENGINE_READY=false` por defecto.
5. Activar el flag solo tras paridad verde + smoke en máquina real, siguiendo
   [`howto-port-to-rust.md`](howto-port-to-rust.md).

## Referencias
- [ADR-0012](../architecture/adr/ADR-0012-rust-hexagon-endgame.md) — destino Rust hexágono, semilla `windows-capture`
- [ADR-0007](../architecture/adr/ADR-0007-dxgi-capture-deferred.md) / [ADR-0017](../architecture/adr/ADR-0017-adr0007-sla-verdict-confirmed.md) — por qué esto NO es una respuesta a CPU
- [ADR-0013](../architecture/adr/ADR-0013-ddagrab-capture-cursor-flicker.md) / [ADR-0014](../architecture/adr/ADR-0014-zerocopy-qsv-capture-pipeline.md) — pipeline actual que este diseño preserva
- [ADR-0006](../architecture/adr/ADR-0006-rust-segment-engine.md) — patrón PyO3/maturin ya en producción
- [howto-port-to-rust.md](howto-port-to-rust.md) — proceso genérico de port
- [reference-target-architecture.md](reference-target-architecture.md#matriz-de-tecnología-por-puerto-destino-rust--track-r) — matriz de puertos
