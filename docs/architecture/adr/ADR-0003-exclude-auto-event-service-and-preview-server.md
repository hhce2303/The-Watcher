# ADR-0003 — `auto_event_service` y `preview_server` MJPEG quedan fuera del daemon

- **Estado**: Aceptado
- **Fecha**: 2026-10-03
- **Requisitos**: ADR-0001; spec de extracción §3 (decisión pendiente "entran solo si el flujo Operador los usa").

## Contexto

El spec dejó dos piezas "pendientes de confirmar": `auto_event_service` y `preview_server`. Criterio por defecto:
entran solo si grabación o streaming LAN las usan en el flujo Operador. Evidencia (monorepo @ `ed5fd98`, rutas
bajo `project/`):

**`auto_event_service`**
- Se construye solo en `app/runtime/backend.py`, *después* del retorno anticipado `if not settings.events_enabled`;
  `config.py` define `events_enabled = _env_flag("EVENTS_ENABLED", False)` y el comentario del backend dice que
  el pipeline de eventos es opt-in "while continuous recording is stabilised".
- Sus únicos consumidores son `main.py` (start/stop) y `runtime/backend.py`. `live_view_lan` y la supervisión no lo
  referencian (grep sin coincidencias).
- Arrastra `core/analytics/models`, `DetectorPort`, `LiveInferenceService`, `IouTracker`, `ml/`, `SqliteEventStore`
  y `EventService`: analítica/ML, justo lo que el gate de pureza prohíbe.

**`preview_server` (MJPEG)**
- `MjpegPreviewServerAdapter` solo lo construye `main.py::_build_preview_server` (rol Operador) y su único
  consumidor es `RecordingApi.get_preview_server_info`, expuesto por el router IPC a la UI Tauri.
- La vista LAN no lo usa: `LiveViewLanAdapter` lee directamente los `segments/m{i}/preview.jpg` que escribe el
  recorder (`server.py:278-281, 342-343`) y trae su propio respaldo MJPEG (ADR-0022). No hay referencia a
  `preview_server` en `live_view_lan`.
- Consumidor único del daemon = operadores/supervisión LAN: no hay UI Tauri ni IPC (spec §1).

## Decisión

Ambos quedan **fuera**, junto con `core/ports/preview_server_port.py`, `tests/test_preview_server.py`,
`tests/test_auto_event_service.py` y los ajustes `PREVIEW_HTTP_*`, `EVENTS_ENABLED`, `ONNX_*`, `INFERENCE_*`,
`MOTION_THRESHOLD`, `TRACKER_*`, `EVENT_COOLDOWN_*` de `config.py`/`.env.example`. Se conservan `EVENT_PRE/POST_SECONDS`
porque `ClipBuilder` (grabación) los usa.

También quedó fuera `native/watcher_h264_encoder`, que el spec listaba como "entra": es el spike de encode
H.264 en Rust para `EditorExportPort` (su README: "SPIKE — not production") y el código del daemon no lo importa
(`h264_feed.py` solo menciona codecs ffmpeg por nombre).

## Consecuencias

- Positivas: cierre de imports mínimo; sin dependencias de ML (`numpy`, `onnxruntime`, `Pillow` fuera de `requirements.txt`).
- Negativas: el daemon no genera clips por eventos automáticos ni manuales; no hay preview HTTP local en
  `127.0.0.1:8787`. Si el flujo Operador vuelve a necesitar alguno, se reabre con un ADR nuevo (no se reinyecta
  por la puerta de atrás); `ClipBuilder` queda como pieza de grabación aún no conectada a un disparador.
- `ADR-0019` (coalescencia de builds de auto-eventos) se heredó por el spec, pero describe código que no está aquí.

## Opciones no elegidas

- Incluirlos "apagados" por flag: mantendría `analytics`/`ml` en el cierre de imports y ampliaría la superficie.
