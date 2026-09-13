# ADR-0015 — Gobernanza de FFmpeg batch: Job Object compartido + semáforo + telemetría

- **Estado**: Aceptado
- **Fecha**: 2026-07-05
- **Relación**: implementa el PoC-2 de
  [ffmpeg-pipeline-optimization-research.md](../../migration/ffmpeg-pipeline-optimization-research.md#8-plan-de-poc)
  (§4). La telemetría que introduce es el instrumento del gate de profiling de
  [ADR-0007](ADR-0007-dxgi-capture-deferred.md) §7 — ver "Estado del gate ADR-0007" abajo.

## Contexto

`process_guard.py` solo mataba huérfanos (`assign_to_job`, kill-on-close sin límites) — todo
proceso FFmpeg, grabador o batch, corría sin techo de CPU/RAM ni prioridad relativa. Dos
consecuencias observadas en la investigación:

- `mp4_converter_adapter.py:63` y `batch_clip_analyzer.py:113` ni siquiera entraban a un Job
  (huérfanos posibles si Python muere a mitad de una conversión/análisis); el analyzer además
  lanzaba su proceso sin `CREATE_NO_WINDOW`.
- Cada monitor tiene su propio executor de builder → con 3-4 monitores, un evento simultáneo podía
  disparar hasta N builds horarios + el grid combinado + el converter + el analyzer al mismo
  tiempo, sin ningún límite de concurrencia ni prioridad frente al grabador.

## Decisión

**`process_guard.py` v2** — dos primitivas nuevas, coexistiendo con `assign_to_job` (sin cambios,
sigue siendo el camino del grabador):

1. **Job Object batch compartido** (`assign_to_batch_job` + `configure_batch_governance`): TODO
   proceso FFmpeg offline/background (builders horario y combinado, mp4 converter, batch analyzer)
   se asigna al **mismo** Job, creado una vez de forma perezosa, con:
   - `KILL_ON_JOB_CLOSE` (mismo comportamiento que el Job del grabador).
   - `PriorityClass = BELOW_NORMAL_PRIORITY_CLASS`.
   - `JobMemoryLimit` configurable (`BATCH_JOB_MEMORY_LIMIT_MB`, default 1536 MB, 0 = sin límite).
   - CPU rate control (`JOBOBJECT_CPU_RATE_CONTROL_INFORMATION`, info-class 15): `WEIGHT_BASED`
     por defecto (`BATCH_JOB_WEIGHT`, 1-9, default 2 — cede CPU al grabador sin congelarse) o
     `HARD_CAP` opcional (`BATCH_CPU_HARD_CAP_PERCENT`, default 0=off, **nunca** para el grabador:
     un hard cap congela hilos al agotar el presupuesto del intervalo).
   - Si `SetInformationJobObject` para CPU rate control falla (documentado: RDS con DFSS activo),
     degrada a solo prioridad+memoria en vez de perder el Job completo.
2. **Semáforo de concurrencia global** (`batch_slot()` + `configure_batch_concurrency`,
   `MAX_BATCH_FFMPEG`, default 1): un `threading.BoundedSemaphore` platform-independiente que
   serializa cuántos procesos FFmpeg batch corren a la vez **en todo el proceso Python**, sin
   importar de qué monitor/adaptador vienen. Envuelve el spawn+wait de cada builder — nunca al
   grabador, que debe poder arrancar siempre de inmediato.

**Cerrado el hueco de huérfanos**: `mp4_converter_adapter.py` y `batch_clip_analyzer.py` ahora
llaman `assign_to_batch_job` + `batch_slot()`; el analyzer también gana `CREATE_NO_WINDOW`.

**Telemetría psutil** (`app/infrastructure/proc_telemetry.py`, nuevo): un hilo de fondo
(`PROC_TELEMETRY_INTERVAL_SECONDS`, default 10 s) muestrea cada PID trackeado (`cpu_percent`,
`memory_info().rss`) y lo loguea estructurado (`category=recorder|batch label=... pid=... cpu_pct=...
rss_mb=...`). `track_process`/`untrack_process` se llaman en los 5 puntos de spawn (grabador +
4 sitios batch). Deliberadamente **best-effort**: cualquier error de psutil, o un `pid` inválido,
se traga silenciosamente — la instrumentación nunca debe poder romper la grabación.

**Corrección encontrada durante el hallazgo de tests**: `assign_to_batch_job`/`assign_to_job`
pasaban `proc.pid` sin convertir a un `ctypes.WinDLL` sin `argtypes` declarados. Un test que
sustituye `subprocess.Popen` por un `MagicMock()` (sin `.pid` real) hacía que ctypes intentara
sondear el Mock buscando ganchos de marshaling (`_as_parameter_`), y `MagicMock` responde
recursivamente creando mocks hijos — **stack overflow fatal, no capturable por `except Exception`**.
Fix: `pid = int(pid)` antes de la llamada ctypes (un `MagicMock` se coacciona a `1`, un `TypeError`
real se vuelve capturable). Aplica también a `ProcTelemetry.track()`, que ahora atrapa
`TypeError`/`ValueError` además de `psutil.Error`.

## Validación

En esta máquina (real, no mockeada): 4 "batch jobs" de FFmpeg (`libx264 -preset veryslow`,
640×480, 4 s) lanzados concurrentemente con `MAX_BATCH_FFMPEG=2`:

- **Concurrencia real medida: pico de 2 procesos vivos simultáneos, nunca 4** — el semáforo
  gobierna procesos FFmpeg reales, no solo hilos Python.
- **Prioridad verificada vía `psutil.Process.nice()`**: los 4 procesos reportan
  `BELOW_NORMAL_PRIORITY_CLASS` — confirma que el Job Object aplica la prioridad, no solo que la
  llamada no lanzó excepción.
- Job creado con log `weight=2, mem_limit_mb=1536, cpu_hard_cap_pct=off` — configuración aplicada.
- Telemetría emitiendo `[telemetry] category=batch label=... cpu_pct=... rss_mb=...` cada segundo
  mientras los procesos corrían.
- Suite pytest completa verde (530 passed, 10 skipped) + 22 tests nuevos: semáforo de concurrencia
  (con hilos reales), clamps de configuración, `assign_to_batch_job` sobre un proceso real de
  Python y sobre un `MagicMock` (regresión del stack overflow), y el ciclo de vida de
  `ProcTelemetry` sobre procesos reales (track/untrack/sample/evict/start-stop).

## Estado del gate ADR-0007 (importante — no cerrado hoy)

Esta ADR entrega la **infraestructura de medición** que el §7 de la investigación exige para
decidir el port Rust de captura ("profiling que demuestre que la captura es el cuello de botella").
No cierra el gate por sí sola: el criterio de decisión del doc requiere **desplegar 2-3 puestos
piloto (1 QSV, 1 con RTX) durante 2 semanas** y mirar el p95 de CPU por grabador en la flota real —
algo que una sesión local no puede simular.

Dato preliminar de esta máquina (ADR-0014, zero-copy QSV): **~0.26 núcleos/monitor**. Convertido a
% de máquina según hilos lógicos:

| Hilos lógicos | CPU/monitor (zero-copy) | ¿Cumple SLA ≤5%? |
|---|---|---|
| 16 (esta máquina) | 1.6% | Sí, con margen amplio |
| 8 | 3.3% | Sí |
| 6 | 4.3% | Sí, al límite |
| 4 | 6.5% | **No** — cruza el 5% |

Lectura honesta: en máquinas de operador típicas (≥6-8 hilos), zero-copy solo probablemente ya
resuelve el SLA sin tocar Rust. El caso que justificaría escalar Rust-4 es la cola de la flota con
pocos núcleos o sin QSV/NVENC (solo-CPU) — exactamente lo que el plan de perfilado del §7 pide medir
con telemetría real, no con una extrapolación de una sola máquina. **Recomendación**: desplegar
zero-copy (ADR-0014) + esta telemetría a los puestos piloto ahora que ambas existen, y revisar
ADR-0007 con datos de flota en 2 semanas — no antes.

## Hallazgo colateral — corregido

Al enrolar `batch_clip_analyzer.py` en el Job batch se detectó que **`BatchClipAnalyzer.start()`
nunca se llamaba en producción** (`main.py` construía el analyzer en `build_recording_backend()` y lo
alimentaba vía `queue_clip()`, pero jamás arrancaba su hilo consumidor). En la práctica, la detección
automática por lotes sobre clips cerrados estaba inerte: los clips se encolaban y nadie los procesaba.

Corregido en `main.py`: `batch_analyzer.start()` junto a `auto_event_service.start()`, y
`batch_analyzer.stop()` dentro de `_stop_backend()`. Caveat documentado in-line: `batch_analyzer` y
`live_service` (vía `auto_event_service`) comparten la misma instancia cruda de `DetectorPort` y
cada uno llama su propio `start()`/`stop()` sobre ella — inofensivo con `MockDetectorAdapter`
(idempotente) pero `OnnxDetectorAdapter.start()` recarga la sesión ONNX en cada llamada, así que un
modelo real pagaría una doble carga al arrancar. No es un problema hoy (`ONNX_MODEL_PATH` vacío por
defecto) pero hay que revisar la propiedad del ciclo de vida del detector antes de desplegar un
modelo real a la flota.

## Consecuencias

- ✅ Cumple el gate de PoC-2: concurrencia acotada, prioridad batch visible, sin tocar `core/`.
- ✅ Cierra el hueco de huérfanos de `mp4_converter_adapter`/`batch_clip_analyzer`.
- ✅ Rollback trivial: `MAX_BATCH_FFMPEG` y `BATCH_JOB_*` son env vars; `batch_slot()`/
  `assign_to_batch_job` son no-op-seguros si algo falla (degradan, no rompen la grabación).
- ➖ El techo de memoria (`JobMemoryLimit`) se verificó por configuración aplicada (log +
  `SetInformationJobObject` sin error), no forzando un OOM real — validar el enforcement bajo
  presión de memoria queda para el despliegue piloto.
- ➖ No cierra ADR-0007: entrega el instrumento, no el veredicto de flota.
