# ADR-0019 — Auto-eventos: build de clip por EventService + coalescencia de ventana

- **Estado**: Aceptado
- **Fecha**: 2026-07-12
- **Relación**: corrige un defecto en la costura descrita por [ADR-0004](ADR-0004-ai-detection-seams.md)
  (`DetectorPort` → `AutoEventService` → callback de build). No cambia la costura, solo cómo
  `app/runtime/backend.py` la conecta con `EventService`.

## Contexto

Se reportó sospecha de un "fallo silencioso" disparando construcciones de clip de forma excesiva,
con logs como:

```
16:04:07 | [auto-event] person (conf=0.90) zone=None → event 20260712210407411464
16:04:25 | BUILD-EVENT | Building clip: event=...T21:02:25 | 3 monitor(s) | window [21:00:25 → 21:04:25]
16:04:25 | FFmpeg clip: -y → 2026-07-12_21-02-25_event.mp4
16:04:43 | [auto-event] person (conf=0.90) zone=None → event 20260712210443276959
16:05:03 | BUILD-EVENT | Building clip: event=...T21:03:03 | 3 monitor(s) | window [21:01:03 → 21:05:03]
16:05:03 | FFmpeg clip: -y → 2026-07-12_21-03-03_event.mp4
```

Investigación (`app/runtime/backend.py`, `_on_auto_event`) encontró **dos defectos** en el camino de
eventos automáticos, distinto del camino manual (`EventService.trigger_manual_event` /
`_execute_clip_build`, con el que nunca compartió código):

1. **Camino de build ad-hoc, sin manejo de errores.** `_on_auto_event` armaba su propio
   `threading.Timer` con un closure `_build_auto_clip` que llamaba a `clip_builder.build(ctx)`
   directo, sin `try/except`, sin reintentos y sin loggear éxito. Si `build()` lanzaba una
   excepción, moría dentro del hilo del `Timer` — Python solo la reporta por
   `threading.excepthook` (stderr), nunca llega al sink de loguru. Por eso en los logs se veía
   `Building clip:` / `FFmpeg clip:` (logueados dentro de `ClipBuilder.build()` mismo, ajenos a
   quién lo invoque) pero nunca la confirmación `Clip created: {}` que sí emite
   `EventService._execute_clip_build` en el camino manual.
2. **Sobreesfuerzo real: cooldown de evento << ventana del clip.** `AutoEventService.cooldown_seconds`
   (`EVENT_COOLDOWN_SECONDS`, default 30s) solo gobierna cada cuánto una detección se convierte en
   `AnalyticEvent` — correcto para analítica/zonas, donde se quiere granularidad. Pero cada evento
   agendaba también un build de clip completo con ventana `event_pre_seconds + event_post_seconds`
   (120+120 = 240s). Con detección continua (persona en cuadro varios minutos), cada ~30s se disparaba
   un build multi-monitor (grid combinado + HEVC) de una ventana de 4 minutos que se solapaba ~90%
   con el anterior — hasta 8 clips redundantes cubriendo casi el mismo metraje, cada uno compitiendo
   por el mismo encoder.

## Decisión

- **Unificar el camino de build.** `EventService._schedule_clip_build`/`_execute_clip_build` pasan
  a ser públicos (`EventService.schedule_clip_build(ctx, on_built=None)`), aceptando un callback de
  persistencia por-llamada que sobreescribe el del constructor. `_on_auto_event` ahora llama a
  `backend.event_service.schedule_clip_build(ctx, on_built=_persist_auto_clip)` en vez de su propio
  `threading.Timer` — recupera reintentos (3 intentos, `CLIP_RETRY_DELAY_SECONDS`), logging de éxito/
  error, y que el timer quede rastreado en `_pending_timers` (se cancela en `stop()`).
- **Coalescer builds automáticos por ventana.** Nueva config `EVENT_AUTO_BUILD_MIN_INTERVAL_SECONDS`
  (default: `EVENT_PRE_SECONDS + EVENT_POST_SECONDS`, i.e. la ventana completa del clip). En
  `_on_auto_event`, un lock + timestamp del último build agendado deciden si el evento actual dispara
  un nuevo build: si `event.start - last_build_at < min_interval`, se persiste el `AnalyticEvent`
  igual (analítica/timeline intactas) pero **no** se agenda un build nuevo — el pendiente ya cubre esa
  actividad. Con el default, los builds quedan contiguos (sin solape, sin huecos) en vez de apilarse
  cada 30s.

## Consecuencias

- ✅ Una excepción en `ClipBuilder.build()` durante un evento automático ahora se loguea (con
  reintento) igual que en el camino manual — deja de ser un fallo silencioso.
- ✅ Detección continua ya no dispara ~8 re-encodes redundantes por visita; a lo sumo uno cada
  `EVENT_AUTO_BUILD_MIN_INTERVAL_SECONDS`.
- ➖ Con el default (ventana completa), la cola de un visita larga puede quedar hasta
  `min_interval` segundos sin resumen en el clip destacado si la detección se corta justo después de
  agendar un build — el buffer continuo/hourly recording sigue teniendo el metraje crudo completo;
  solo el clip "highlight" puede no extenderse hasta el último frame de actividad. Aceptable: el
  propósito del clip de evento es un resumen, no la fuente de verdad.
- 🔁 Tests: `project/tests/test_event_service.py::TestScheduleClipBuildOnBuiltOverride` (override
  sobrevive reintento) y `project/tests/test_f2_e2e.py::TestAutoEventBuildCoalescing` (ráfaga de
  eventos → un solo build; evento fuera del intervalo → build nuevo).
