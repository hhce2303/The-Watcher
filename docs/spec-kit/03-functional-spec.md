# 03 — Especificación funcional

## Grabación continua

- Se detectan monitores al inicio y cada 5 segundos; hot-plug agrega o retira workers.
- Cada worker escribe segmentos MPEG-TS y un `preview.jpg`. `BufferManager` conserva `RETENTION_HOURS` de material y poda lo anterior.
- `RecorderSupervisor` reinicia un FFmpeg que cae con backoff exponencial de 2, 4, 8 y hasta 30 segundos, con máximo configurable de 10 reinicios. Health y disk monitor publican degradación/recuperación.
- La grabación de Operator no puede detenerse desde la UI; IT la controla conforme a su política.

## Eventos y clips

- `trigger_event` captura la selección de monitores y el instante en un contexto inmutable.
- Se espera `EVENT_POST_SECONDS`, se toma `EVENT_PRE_SECONDS` del buffer y se ensambla el clip. El cooldown evita duplicados manuales.
- Eventos automáticos comparten el flujo de construcción y reintentos del evento manual. Se coalescen: `EVENT_AUTO_BUILD_MIN_INTERVAL_SECONDS` limita la frecuencia de encodes pesados sin perder todos los eventos analíticos.
- Los eventos se almacenan en SQLite y se escriben como sidecar `<clip>.events.json` versionado.

## Clips y reproducción

| Resultado | Ubicación predeterminada | Característica |
|---|---|---|
| Segmentos | `segments/m{index}/seg_*.ts` | Buffer volátil y podado. |
| Preview | `segments/m{index}/preview.jpg` | JPEG reciente; nunca en IPC JSON. |
| Raw | `clips_raw/` | MP4 por monitor y ventana. |
| Combinado | `clips/` | Grid multi-monitor con marca temporal. |
| Evento | `clips_events/` | Highlight manual/automático y sidecar. |

`watcher://preview/m{index}` sirve el preview; `watcher://clip/{base64url(path)}` sirve el archivo validado contra raíces permitidas. Si WebView2 no puede decodificar HEVC, usar `transcode_clip`; no asumir fallback de software.

## Edición y entrega

- El editor construye un reel de una pista a partir de clips, permite añadir, ordenar, remover y cambiar in/out por clip.
- La exportación corre server-side. El exportador verifica incompatibilidades de codec/resolución y mezcla copy/re-encode en los bordes según sea necesario.
- Delivery crea/obtiene una carpeta OneDrive, exporta allí y devuelve enlace de compartición. La implementación local usa la carpeta sincronizada; Graph está preparado, no es el camino activo por defecto.
- IT puede guardar un reel de modo privado; es distinto de compartir con link.

## Solicitudes y analítica

- Supervisor consulta storage/operators y manda solicitudes JSON al cliente WebSocket; IT corre el servidor, persiste solicitudes y publica eventos de inbox/estado.
- La analítica ofrece conteo por clase, dwell por track y eventos por zona. Puede usar ONNX si existe `ONNX_MODEL_PATH`; sin modelo se usa detector mock. Live inference toma previews con motion gate y tracker IoU; batch analiza clips cerrados.
- El tab Analytics hace polling cada 10 segundos, una decisión aceptada para no acoplarlo aún al event bus.

