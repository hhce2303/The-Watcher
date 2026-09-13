# Optimización del pipeline FFmpeg — investigación `/deep-research` (2026-07-05)

**Pregunta:** cómo reducir el consumo sostenido de CPU/RAM de los procesos FFmpeg de The Watcher
(un pipeline always-on por monitor, 3-4 monitores típicos, flota mixta Intel QSV + algunas NVIDIA),
qué alternativas modernas existen (2025-2026), qué papel juega Rust, y cómo gobernar los
subprocesos para que no se descontrolen.

**Método y estado de verificación.** Harness `/deep-research`: 5 ángulos de búsqueda → 23 fuentes →
114 claims extraídos → top-25 seleccionados. Los paneles de verificación adversarial (75 votos)
fallaron dos veces por límites de sesión de la API, así que la verificación se hizo de forma
directa: **(a) empírica** — benchmark real en una máquina con Intel Iris Xe + FFmpeg 8.1 full-build
(la base QSV de la flota), y **(b) documental** — re-fetch dirigido de las fuentes primarias de los
claims load-bearing. Cada afirmación lleva etiqueta:

- `[LOCAL]` — verificado ejecutándolo en esta máquina (máxima confianza).
- `[DOC]` — verificado contra la fuente primaria (docs oficiales FFmpeg/Microsoft/NVIDIA/GStreamer o el repo).
- `[BÚSQUEDA]` — proviene de la fase de búsqueda, no re-verificado individualmente (confianza media).

---

## 1. Resumen ejecutivo

1. **El quick win dominante es el pipeline zero-copy D3D11→QSV, y ya está validado en esta máquina:
   reduce el CPU del grabador en ~66-70%** (0.68 → 0.21-0.23 núcleos por monitor) cambiando solo el
   filtergraph de FFmpeg — cero código nuevo de negocio, con feature flag y rollback trivial. `[LOCAL]`
2. El "descontrol de recursos" tiene arreglo directo: el `process_guard.py` actual solo mata
   huérfanos; Windows Job Objects soportan **límite de CPU (hard cap o peso), prioridad y límite de
   memoria** — y ya usamos ctypes, así que extenderlo es barato. Dos procesos (batch analyzer,
   mp4 converter) hoy ni siquiera entran al Job. `[DOC]`/`[LOCAL en código]`
3. De las alternativas modernas, **ninguna justifica reemplazar FFmpeg a corto plazo**: GStreamer es
   técnicamente equivalente pero cuesta ~100 MB de runtime + una stack nueva; libobs es un mal
   encaje como librería; el camino Rust (`windows-capture` + Media Foundation + `shiguredo_mp4`)
   es el destino correcto para Track R **post-cutover**, no un atajo de hoy.
4. **Dos correcciones a supuestos previos:** `vpl-rs` (bindings Rust de Intel VPL, de Shiguredo) es
   **solo Linux** — el encode HW desde Rust en Windows pasa por Media Foundation `[DOC]`; y NVENC en
   GPUs consumer tiene un límite de **8 sesiones de encode por sistema** — 4 grabadores + builders
   concurrentes pueden rozarlo, otra razón para el presupuesto de concurrencia `[DOC]`.

**Recomendación:** ejecutar los PoC de la §8 en este orden — (1) zero-copy con flag, (2) gobernanza
Job Objects + presupuesto de concurrencia + telemetría psutil, (3) clip de evento en una pasada.
La telemetría del PoC-2 es además el dato que exige el gate de ADR-0007 para decidir (o descartar)
el port Rust de captura.

---

## 2. Benchmark empírico `[LOCAL]`

**Entorno:** Intel Iris Xe (driver 32.0.101.7084), 16 núcleos lógicos, Windows 11, FFmpeg
8.1-full_build (gyan.dev, compilado con libvpl → QSV respaldado por D3D11). Captura real del
monitor 0 vía ddagrab, 20 s por variante, salida de grabación a MPEG-TS (NUL) + rama preview JPEG
2 fps, calidad 28 como producción. Escritorio mayormente estático (con contenido en movimiento los
absolutos suben, pero el orden relativo se mantiene). Script: `bench.ps1` (scratchpad de la sesión).

| Variante | Filtergraph (resumen) | CPU (núcleos) | Peak RAM |
|---|---|---:|---:|
| **Actual** → `hevc_qsv` | ddagrab → `hwdownload,format=bgra` → split → scale CPU → encode | 0.68 | 483 MB |
| **Zero-copy** → `hevc_qsv` | ddagrab → split → `hwmap=derive_device=qsv,vpp_qsv=w=1920:h=1080:format=nv12` → encode; preview: `fps=2,hwdownload` | **0.23 (−66%)** | 480 MB |
| Zero-copy + `-low_power 1` | ídem + VDEnc | 0.23 | 478 MB |
| Zero-copy + `async_depth=1` | ídem (vpp y encoder) | **0.21** | **441 MB (−8%)** |
| Actual → `libx265 ultrafast` (SW) | lo que paga una máquina sin encoder HW | 2.21 | 533 MB |

Hallazgos colaterales verificados en la ejecución:

- `hwmap=derive_device=qsv` funciona **dentro del filtergraph** sin `-init_hw_device` explícito
  (ddagrab crea su device D3D11 y QSV se deriva de él). `[LOCAL]`
- `fps=2` acepta frames D3D11 (opera sobre referencias/PTS), así que la rama preview solo hace
  `hwdownload` a 2 fps en vez de 30 — el JPEG de preview se generó correcto en las 4 variantes
  (~190 KB), es decir **la analítica en vivo no pierde su fuente de frames**. `[LOCAL]`
- `-low_power` (VDEnc) no cambió el CPU (ya es ~0); su efecto es de consumo eléctrico/calidad BRC.
  En Iris Xe el default `auto` ya elige bien. `[LOCAL]`
- La RAM (~0.44-0.5 GB working set por proceso) está dominada por los pools de superficies
  D3D11/QSV, no por el scale CPU: el zero-copy **no** la reduce; `async_depth=1` la baja ~8%.
  Con 4 monitores el residente sostenido es ~1.8-2 GB — esa es la palanca de RAM realista
  (más el presupuesto de concurrencia de la §4, que evita picos apilados). `[LOCAL]`
- Contexto de SLA (≤5% CPU/monitor): los núcleos importan. 0.23 núcleos = 1.4% en una máquina de
  16 hilos, pero 5.7% en una de 4. El pipeline actual (0.68 núcleos) solo cumple el SLA en máquinas
  de ≥14 hilos; el zero-copy lo cumple desde ~5 hilos.

---

## 3. A — Optimización del pipeline FFmpeg actual

### 3.1 Zero-copy D3D11→QSV (quick win #1) `[LOCAL]`+`[DOC]`

Base documental: ddagrab emite **exclusivamente frames D3D11** (GPU); `hwdownload` solo es
necesario cuando hay procesamiento por software — el ejemplo canónico de la doc oficial pipea
ddagrab directo a NVENC sin descarga `[DOC: docs FFmpeg 8.0 ddagrab]`. En builds con libvpl (como
gyan.dev full) el child device de QSV es d3d11va por defecto, el prerequisito del interop
`[DOC: ffmpeg-devel enero 2024]`. El patrón split 1:N sobre frames QSV está documentado en la wiki
oficial de QuickSync `[DOC]`.

Cambio concreto (todo en [recorder_adapter.py:202-322](../../project/app/adapters/ffmpeg/recorder_adapter.py#L202-L322)):

```text
# HOY (rama ddagrab con preview):
ddagrab=output_idx=N:framerate=30:draw_mouse=0,hwdownload,format=bgra,split=2[rec][prev];
[rec]scale=1920:1080,format=yuv420p[recout];
[prev]fps=2,scale=1280:-2,format=yuv420p[prevout]

# ZERO-COPY (validado):
ddagrab=output_idx=N:framerate=30:draw_mouse=0,split=2[rec][prev];
[rec]hwmap=derive_device=qsv,vpp_qsv=w=1920:h=1080:format=nv12:async_depth=1[recout];
[prev]fps=2,hwdownload,format=bgra,scale=1280:-2,format=yuv420p[prevout]
```

más `-async_depth 1` en el encoder QSV. La conversión BGRA→NV12 y el scale pasan a la GPU
(`vpp_qsv`), el split ocurre en el dominio D3D11 y solo se descargan 2 fps para el preview.

**Condiciones y trampas:**

- Solo aplica cuando el encoder activo es `*_qsv` (el filtergraph queda acoplado al encoder —
  hoy `encoder_selector` y `_build_ffmpeg_command` son independientes; hay que pasarle el encoder
  resuelto al builder del grafo).
- **NVENC:** la doc oficial muestra ddagrab → `h264_nvenc`/`hevc_nvenc` consumiendo frames D3D11
  directamente `[DOC]`; si no hace falta escalar (captura ya 1080p) ni siquiera se necesita filtro.
  Con scale, el camino es hwmap a CUDA + `scale_cuda`. **No validado localmente** (no hay NVIDIA en
  esta máquina) → el PoC debe probarlo en una RTX real antes de habilitarlo para ese driver.
- **AMF y gdigrab quedan en el pipeline legacy** (gdigrab entrega frames CPU; no hay zero-copy posible).
- iGPU vs dGPU en la misma máquina: `derive_device` exige que capture y encoder estén en la **misma
  GPU**. ddagrab captura en el adaptador del monitor; si un monitor cuelga de la dGPU NVIDIA y el
  encode va a QSV (iGPU), el hwmap falla → el probe de arranque debe probar el grafo zero-copy
  **por monitor** y caer al legacy si falla (extender el probe existente de
  [recorder_adapter.py:358](../../project/app/adapters/ffmpeg/recorder_adapter.py#L358)).
- Rollback: flag de config (p. ej. `CAPTURE_PIPELINE=auto|zerocopy|legacy`) + fallback automático
  del probe. Riesgo residual ≈ 0: es el mismo binario FFmpeg, mismo formato de segmentos `.ts`,
  mismos SPS/PPS uniformes (el compilador Rust y el concat lossless no se enteran).

### 3.2 Clip de evento en una sola pasada (quick win #3)

Hoy cada clip de evento son **dos procesos secuenciales**: trim/concat
([trim_adapter.py:315](../../project/app/adapters/ffmpeg/trim_adapter.py#L315)) y luego un re-encode
completo solo para quemar el timestamp
([timestamp_adapter.py:126](../../project/app/adapters/ffmpeg/timestamp_adapter.py#L126)). Matiz importante
tras validar contra el código:

- **Multi-monitor (composite):** hoy son 2 encodes (xstack + burn). Plegar el `drawtext` en el
  filter_complex del composite — exactamente como ya hace
  [combined_clip_builder.py](../../project/app/adapters/ffmpeg/combined_clip_builder.py) — **elimina un
  encode completo** (~50% del costo del clip).
- **Single-monitor:** hoy es copy (barato) + 1 encode (burn) — una sola pasada
  decode+drawtext+encode cuesta lo mismo en encodes; la ganancia es solo un proceso y un archivo
  intermedio menos. Prioridad baja.

### 3.3 Tuning 24/7 (menor, acompaña al PoC)

- **GOP explícito** (p. ej. `-g 150` = 5 s a 30 fps): hoy no se fija; gobierna la granularidad del
  trim keyframe-aligned del editor y del corte de segmentos. Costo cero, mejora la predictibilidad.
- `-low_power` dejar en `auto` (default): no mostró diferencia de CPU `[LOCAL]` y tiene
  limitaciones de BRC según versión de mfx (la propia ayuda del encoder lo marca experimental).
- `-threads`/`filter_threads`: irrelevantes en el camino zero-copy (no hay filtros SW en la rama
  caliente); **sí** acotarlos en el fallback `libx265`/`libx264` y en los re-encodes batch
  (composite, grid, convert) para limitar RAM y picos: p. ej. `-threads 4` en trabajos batch.
- Presets NVENC para 24/7: `p4 -tune ll` (ya lo hace `encoder_selector`) es el equilibrio correcto
  según la app note de NVIDIA `[DOC]`.

### 3.4 Consolidar N procesos en uno — **NO recomendado**

Un solo FFmpeg con N grafos ddagrab + N muxers segment es posible, pero:
un crash mata la grabación de **todos** los monitores a la vez (hoy el blast radius es un monitor);
el supervisor per-monitor con backoff ([supervisor.py](../../project/app/core/recording_service/supervisor.py))
y el hot-add/remove de monitores (workers dinámicos cada 5 s) están diseñados alrededor del
proceso-por-monitor; y el ahorro real es pequeño (el overhead por proceso es fijo, ~decenas de MB —
el costo está en los píxeles, que no cambia). El aislamiento vale más que el ahorro. Con zero-copy,
el costo marginal por proceso ya es ~0.2 núcleos.

---

## 4. B — Gobernanza de subprocesos en Windows

### 4.1 Primitivas disponibles (todas alcanzables desde el ctypes que ya usamos)

| Primitiva | Semántica exacta | Para The Watcher |
|---|---|---|
| Job Object `CPU_RATE_CONTROL_HARD_CAP` | "After the job reaches its CPU cycle limit for the current scheduling interval, **no threads associated with the job will run** until the next interval". `CpuRate` = porcentaje × 100 (20% → 2000); 0 es inválido. `[DOC verbatim MS Learn]` | **Solo trabajos batch.** Congelaría periódicamente un grabador de 30 fps → prohibido en la ruta caliente. |
| Job Object `WEIGHT_BASED` | Peso 1-9 (default 5), participación **relativa** bajo contención; no congela hilos. `[DOC]` | Ideal para el Job batch: cede CPU cuando el grabador/usuario la necesita, sin techo artificial. |
| Job Object límites de memoria | `ProcessMemoryLimit`/`JobMemoryLimit` en `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` (la struct que ya declara `process_guard.py`; solo falta poblar campos + flags). `[DOC]` | Techo de RAM para batch (p. ej. 1.5 GB por Job) → un xstack 4K desbocado ya no se come la máquina. |
| `PriorityClass` en el Job | `JOB_OBJECT_LIMIT_PRIORITY_CLASS` + `BELOW_NORMAL`/`IDLE`. | Batch a `BELOW_NORMAL`; grabadores quedan en `NORMAL`. |
| EcoQoS / `PROCESS_POWER_THROTTLING` | `SetProcessInformation` por PID; el scheduler usa cores eficientes a menor frecuencia. Microsoft advierte **no** usarlo en trabajo performance-critical. `[DOC]` | Opcional para batch en laptops; nunca para grabadores. |
| Jobs anidados (Win 8+) | Un proceso puede pertenecer a jobs anidados. `[DOC]` | Permite mantener el job kill-on-close por proceso **y además** un Job batch compartido con límites. |

Notas: pywin32 no expone `JobObjectCpuRateControlInformation` (solo 4 info-classes) `[DOC]` — da
igual, `process_guard.py` ya es ctypes puro. Caveat documentado: CPU rate control no funciona bajo
Remote Desktop Services con DFSS activo `[DOC]` — irrelevante para puestos físicos de operador,
anotarlo por si aparece un caso RDP.

### 4.2 Diseño recomendado

1. **`process_guard.py` v2** — dos modos:
   - `assign_to_job(proc)` (grabadores): como hoy, kill-on-close, sin límites. La grabación nunca
     se throttlea.
   - `assign_to_batch_job(proc)` (builders horarios, grid, trim/burn, export, convert, batch-decode):
     **un Job compartido** con kill-on-close + `WEIGHT_BASED` weight 2-3 + `PriorityClass
     BELOW_NORMAL` + `JobMemoryLimit` configurable. Opcional endurecer a `HARD_CAP` (p. ej. 40%)
     vía config para máquinas muy justas — el batch tolera congelarse.
2. **Cerrar el hueco de huérfanos:** enrolar
   [mp4_converter_adapter.py:63](../../project/app/adapters/ffmpeg/mp4_converter_adapter.py#L63) y
   [batch_clip_analyzer.py:113](../../project/app/core/analytics/batch_clip_analyzer.py#L113) (hoy fuera de
   todo Job; el analyzer además sin `CREATE_NO_WINDOW`).
3. **Presupuesto global de concurrencia:** hoy cada monitor tiene su propio executor de builder →
   hasta N builds horarios simultáneos + grid + batch + evento. Sustituir por un semáforo/cola
   global (`MAX_BATCH_FFMPEG=1` por defecto, env-tunable) que serialice los trabajos batch entre
   monitores. Beneficio doble: aplana picos de CPU/RAM **y** acota las sesiones de encode HW
   simultáneas — crítico en NVENC consumer (límite de **8 sesiones por sistema** `[DOC: NVIDIA
   Video Codec SDK 13.0]`; 4 grabadores + builders concurrentes pueden rozarlo; QSV no tiene un
   tope duro equivalente).
4. **Telemetría psutil por PID** (hoy: cero): hilo de muestreo cada ~10 s sobre los PIDs vivos —
   `cpu_percent`, `memory_info().rss`, conteo por categoría (recorder/batch) — a log estructurado
   y/o al `AnalyticsStore`. Es también el instrumento del gate ADR-0007 (§7). Patrón estándar en
   NVRs 24/7: Frigate corre un proceso FFmpeg por cámara con supervisión, presets de hwaccel y
   telemetría por proceso `[BÚSQUEDA]`.

---

## 5. C — Alternativas modernas al subproceso FFmpeg (Windows, 2025-2026)

Contrato a satisfacer (del código real): segmentos `.ts` `seg_%Y%m%d_%H%M%S` de 300 s por monitor,
`preview.jpg` ~2 fps, callbacks segmento-listo/crash, params uniformes para concat lossless, HEVC
(`hvc1`) y H.264, 24/7 con watchdog, ≤5% CPU/monitor.

| Opción | Estado | Contra el contrato | Veredicto |
|---|---|---|---|
| **FFmpeg zero-copy** (§3.1) | Validado `[LOCAL]` | Cumple todo — es el mismo pipeline con otro grafo | **Ganador corto plazo** |
| **Rust: `windows-capture` + Media Foundation + `shiguredo_mp4`** | WGC + DXGI, bindings Rust **y** Python en el repo, v2.0.0, encoder HW integrado; pero su `VideoEncoder` documenta **solo MP4** (HEVC/TS/rotación de segmentos sin documentar), ~485★, mantenedor único `[DOC]` | La captura encaja; el encode/mux hay que construirlo: MF `IMFSinkWriter` via windows-rs + mux fMP4 propio con `shiguredo_mp4` (ya probado en `watcher_segments`) + callbacks. Semanas de trabajo + spike de paridad | **Destino Track R (Rust-4), post-cutover** — exactamente lo que ya dice ADR-0007. La referencia de implementación existe: `wcap` (WGC+MF, MP4 fragmentado crash-safe) `[BÚSQUEDA]` |
| **GStreamer** (`d3d11screencapturesrc` → `qsvh265enc`/`mfh265enc` → `splitmuxsink`) | `d3d11screencapturesrc` soporta DXGI **y** WGC, emite `D3D11Memory` zero-copy, selección por `monitor-index`, `show-cursor` `[DOC]`; splitmuxsink hace segmentos con callbacks | Técnicamente cumple todo, en un solo proceso o por monitor | **Descartado por costo de despliegue**: runtime ~100+ MB + plugins + PyGObject empaquetado con PyInstaller + una stack nueva que nadie del equipo opera. Iguala, no supera, al FFmpeg optimizado |
| **libobs / OBS headless** | Librería pensada como app de streaming; API C compleja, packaging pesado | Sobredimensionado; segmentación/callbacks no nativos | Descartado |
| **WGC + MF vía helper C#/C++** | Posible | Introduce un tercer toolchain | Descartado (Rust ya es el destino comprometido) |

**Corrección relevante para Track R:** `vpl-rs` (bindings Intel VPL de Shiguredo — la misma casa de
`shiguredo_mp4`) soporta encode/decode H.264/H.265/VP9/AV1 con libvpl estático, v2026.3.0, pero es
**Linux x86_64 únicamente** `[DOC]`. En Windows, el encode HW desde Rust pasa por **Media
Foundation** (windows-rs), que además abstrae QSV/NVENC/AMF de forma uniforme — mejor encaje para
la flota mixta que bindings por vendor. Sobre segmentos: para el port Rust conviene evaluar
**fMP4/CMAF** (crash-safe como TS, sin la sobrecarga ~5-10% del contenedor TS, y `shiguredo_mp4` ya
lo cubre) — cambiaría la extensión del contrato de segmentos, decisión para el ADR del spike.

---

## 6. D — Matriz de decisión

| Criterio | Zero-copy FFmpeg | + Gobernanza Jobs | GStreamer | Rust (WGC+MF) | libobs |
|---|---|---|---|---|---|
| Costo en código | ~1 día (filtergraph + flag + probe) | ~2 días (ctypes + semáforo + psutil) | Semanas (stack nueva + packaging) | Semanas (spike + paridad) | Semanas |
| Reducción CPU grabación | **−66-70% medido** `[LOCAL]` | 0 (aplana picos) | ≈ igual que zero-copy | ≈ igual (mismas APIs debajo) | ≈ igual |
| Reducción RAM | −8% por proceso; picos −mucho con presupuesto | Techo duro configurable | ≈ | Potencialmente mejor (control de pools) | ≈ |
| Escala con N monitores | Lineal, ~0.2 núcleos/monitor | Serializa batch entre monitores | Lineal | Lineal | — |
| Flota QSV/NVENC mixta | QSV validado; NVENC por validar; AMF/CPU → legacy | Neutral (+ respeta límite 8 sesiones NVENC) | Cubre ambos | MF cubre ambos | Cubre ambos |
| Alineación destino Rust | Neutral (compra tiempo) | Neutral | **Negativa** (stack puente) | **Total** (es Track R) | Negativa |
| Rollback | Flag + fallback automático | Flag por límite | Difícil | Flag `ENGINE_READY` (patrón probado) | Difícil |

**Decisión recomendada:** zero-copy + gobernanza **ahora** (suma ~3-4 días, todo tras feature
flags); Rust queda como Track R/Rust-4 con el gate de ADR-0007 alimentado por la telemetría nueva.
GStreamer y libobs descartados.

---

## 7. Plan de perfilado (gate ADR-0007)

ADR-0007 exige "profiling que demuestre que la captura es el cuello de botella" antes de portar la
captura a Rust. Con la telemetría de §4.2-4:

1. Desplegar zero-copy + telemetría a 2-3 puestos piloto (1 QSV puro, 1 con RTX).
2. Recoger 2 semanas: CPU/RAM por proceso (p50/p95), núcleos de la máquina, driver activo,
   frecuencia de picos batch, restarts del supervisor.
3. Criterio de decisión: si tras zero-copy el p95 de CPU por grabador sigue > 5% de la máquina en
   una fracción relevante de la flota (máquinas de pocos núcleos o solo-CPU), **escalar Rust-4**
   (captura windows-capture + encode MF). Si no — que es lo esperable con QSV como base — Rust-4
   permanece diferido y el port Rust sigue su orden natural post-cutover.

## 8. Plan de PoC

| # | Qué | Costuras | Días | Gate de éxito |
|---|---|---|---|---|
| 1 | **Zero-copy QSV** tras flag `CAPTURE_PIPELINE=auto\|zerocopy\|legacy`; probe por monitor con fallback; variante NVENC directa | `recorder_adapter._build_ffmpeg_command`/`_ddagrab_source` + acople con `encoder_selector` + probe (`:358`) + `config.py` | 1-1.5 | En máquina de operador QSV: CPU/monitor ≤ ⅓ del actual, segmentos válidos (concat lossless OK con `watcher_segments`), preview.jpg vivo, watchdog/supervisor intactos. En RTX: grafo NVENC validado o fallback limpio |
| 2 | **Gobernanza**: `process_guard` v2 (batch Job: weight+priority+mem), enrolar converter/analyzer, semáforo `MAX_BATCH_FFMPEG`, telemetría psutil | `process_guard.py`, `mp4_converter_adapter.py`, `batch_clip_analyzer.py`, builders, nuevo `infrastructure/proc_telemetry.py` | 1.5-2 | Con 4 builds encolados: nunca >1 encode batch simultáneo, prioridad batch BELOW_NORMAL visible, techo de RAM efectivo, métricas en log/analytics |
| 3 | **Evento en una pasada** (composite): drawtext dentro del xstack, retirar la pasada `burn` en ese camino | `trim_adapter._build_composite`, `clip_builder.py`, `timestamp_adapter` | 0.5-1 | Clip multi-monitor con timestamp correcto en 1 encode; suite pytest verde |

Los tres son independientes, reversibles por flag y no tocan `core/` (solo adapters + infra), así
que no interfieren con F2 (UI React) ni con el contrato del backend headless de F1.

## 9. Fuentes

**Verificación local:** FFmpeg 8.1-full_build (gyan.dev) sobre Intel Iris Xe, Windows 11 — script
`bench.ps1`, 5 variantes (§2).

1. FFmpeg 8.0 docs — ddagrab: https://ayosec.github.io/ffmpeg-filters-docs/8.0/Sources/Video/ddagrab.html
2. FFmpeg 8.0 docs — hwmap/derive_device: https://ayosec.github.io/ffmpeg-filters-docs/8.0/Filters/Video/hwmap.html
3. FFmpeg wiki — Hardware/QuickSync (hwmap derive, split 1:N, MFE): https://fftrac-bg.ffmpeg.org/wiki/Hardware/QuickSync
4. ffmpeg-devel — QSV child device d3d11va por defecto (libvpl): https://ffmpeg.org/pipermail/ffmpeg-devel/2024-January/319323.html
5. Microsoft Learn — JOBOBJECT_CPU_RATE_CONTROL_INFORMATION: https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information
6. Microsoft Learn — Job Objects: https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
7. Microsoft Learn — SetProcessInformation / PROCESS_POWER_THROTTLING: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation
8. Microsoft — Introducing EcoQoS: https://devblogs.microsoft.com/performance-diagnostics/introducing-ecoqos/
9. Microsoft — Windows container resource controls (Jobs como primitiva): https://learn.microsoft.com/en-us/virtualization/windowscontainers/manage-containers/resource-controls
10. pywin32 — win32job (info-classes soportadas): https://timgolden.me.uk/pywin32-docs/win32job.html
11. NVIDIA Video Codec SDK 13.0 — NVENC Application Note (8 sesiones/sistema consumer): https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-application-note/index.html
12. windows-capture (Rust+Python, WGC/DXGI): https://github.com/NiiightmareXD/windows-capture
13. vpl-rs (Shiguredo — Linux only): https://github.com/shiguredo/vpl-rs
14. GStreamer — d3d11screencapturesrc: https://gstreamer.freedesktop.org/documentation/d3d11/d3d11screencapturesrc.html
15. GStreamer — splitmuxsink: https://gstreamer.freedesktop.org/documentation/multifile/splitmuxsink.html
16. wcap (WGC+MF, MP4 fragmentado crash-safe — referencia para Track R): https://github.com/mmozeiko/wcap
17. GStreamer en Windows — deployment: https://gstreamer.freedesktop.org/documentation/deploying/windows.html
