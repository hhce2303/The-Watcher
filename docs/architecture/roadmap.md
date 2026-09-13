# Tab de Edición → IA — Roadmap y buenas prácticas

> Documento de **linealidad**: la secuencia de fases que lleva desde las herramientas de edición de
> hoy hasta un sistema de detección de eventos (YOLO) + analíticos con UI React/Tauri, sin reescrituras.
>
> Estado: vivo · Fecha: 2026-07-04 · Referencias: [`goals.md`](goals.md) · [ADRs](adr/) · Frigate NVR (arquitectura de referencia) · [Migración Tauri](../migration/README.md).

---

## Mapa de fases

```
Fase 0  EDICIÓN + COSTURAS                                         [HECHO]
   │    timeline multi-clip, trim, zoom, fullscreen, export inteligente
   │    + motor Rust de segmentos + ports/esquemas de IA (vacíos)
   ▼
Fase 1  PERSISTENCIA DE EVENTOS                                    [HECHO]
   │    EventStorePort + adapter SQLite + esquema sidecar *.events.json
   │    pintar eventos MANUALES existentes como marcadores en el timeline
   ▼
Fase 2  PIPELINE DE INFERENCIA (mock)                              [HECHO]
   │    DetectorPort + adapter MOCK + AutoEventService
   │    prueba punta-a-punta del flujo detect→evento→clip SIN modelo real
   ▼
Fase 3  YOLO REAL (batch, out-of-process)                          [HECHO*]
   │    análisis de clips grabados; modelo ONNX servido por crate Rust `ort`
   │    (DirectML/CUDA) — evita AGPL de Ultralytics; ver ADR-0005
   ▼
Fase 4  TIEMPO REAL + ANALÍTICOS                                   [HECHO]
   │    dos etapas (gate de movimiento → detección), IouTracker,
   │    Zonas, AnalyticsQueryPort + SqliteAnalyticsAdapter
   ▼
Fase 5  TAB ANALÍTICOS (TAURI/REACT)                               [SIGUIENTE]
        AnalyticsTab.tsx · CountsChart · DwellTable · ZonePanel
        IPC endpoints sobre AnalyticsQueryPort (F4) + canal F1
        Tauri commands tipados (tauri-specta) + live events

        ↳ F2a HECHO (2026-07-04): Tauri 2 shell + React bootstrapped
          src-tauri/ (Rust IPC client, named-pipe, commands)
          src/ (Vite+React 18+TS, tab shell, tokens CSS, useIpc, useTauriEvent)
          Gate F5 desbloqueado
```

_\* F3 infra lista; pendiente modelo ONNX permisivo (ADR-0005)_

---

## Detalle por fase

### Fase 0 — Edición + costuras *(actual)*
**Entregables**: R-1…R-6 (ver [`goals.md`](goals.md)) + ports/esquemas de IA declarados pero vacíos
(`DetectorPort`, `EventStorePort`, `core/analytics/models.py`) + capa `events` en el timeline lista
para poblarse.
**Criterio de salida**: el reel se arma, recorta, reproduce, hace zoom/fullscreen y exporta sin
pérdida; el motor Rust compila segmentos con fallback FFmpeg; los ports de IA compilan y tienen
adapter *mock*/stub testeable.

### Fase 1 — Persistencia de eventos
**Entregables**: `EventStorePort` + adapter **SQLite** (`adapters/storage/`), esquema sidecar
`<clip>.events.json` versionado, y render de los **eventos manuales** (`Event.source == "manual"`,
ver [`event_service.py`](../../project/app/core/event_service.py)) como pines clicables en el timeline que
hacen *seek*.
**Criterio de salida**: un evento manual disparado se persiste y aparece como marcador navegable.
**Por qué antes que la IA**: valida el almacén y la UI de marcadores con datos reales y baratos
(disparos manuales) antes de meter inferencia.

### Fase 2 — Pipeline de inferencia (mock)
**Entregables**: `DetectorPort` con un **adapter mock** (devuelve detecciones sintéticas) +
`AutoEventService` que se suscribe al detector y llama al **mismo** `snapshot_event()`/`build()` con
cooldown que el flujo manual.
**Criterio de salida**: una "detección" mock genera un `AnalyticEvent`, un clip y un marcador, sin
ningún modelo real. Demuestra que el pipeline está completo y desacoplado.

### Fase 3 — YOLO real (batch, out-of-process)
**Entregables**: adapter de inferencia real en un **worker/sidecar** que analiza clips ya cerrados.
Ruta recomendada: modelo exportado a **ONNX** servido por el crate Rust **`ort`** (ONNX Runtime) con
backend **DirectML** (o CUDA) — reusa la cadena PyO3/maturin del motor de segmentos. Tracking básico.
**Criterio de salida**: detección real sobre footage grabado escribe en `EventStore` y aparece en el
timeline; licencia del modelo resuelta en [ADR-0005](adr/ADR-0005-yolo-licensing.md).

### Fase 4 — Tiempo real + analíticos ✓
**Entregables**: `MotionFilter` (gate CPU numpy), `LiveInferenceService` (wrapper Frigate-style sobre
`DetectorPort`), `IouTracker` (SORT-lite, tracking estable sin scipy), `Zone` (polígono normalizado +
ray-cast), `AnalyticsQueryPort` + `SqliteAnalyticsAdapter` (conteos, dwell, zonas consultables).
**Criterio de salida**: ✓ Detección en vivo sin bloquear la grabación — 489 pruebas verdes, 0 regresiones.

### Fase 5 — Tab Analíticos (Tauri/React) ✓ CERRADA
**Entregables**:

| Componente | Descripción |
|-----------|-------------|
| `AnalyticsTab.tsx` | ✓ Tab principal: filtros (rango 1h/6h/24h/7d, monitor) + tres paneles |
| `CountsChart` | ✓ Gráfica de barras — Canvas API (sin D3/AGPL) |
| `DwellTable` | ✓ Tabla de dwell times por `track_id`: clase, primer/último avistamiento, total |
| `ZonePanel` | ✓ Eventos por zona con frecuencia relativa + barra proporcional |
| `useLiveAnalytics` | ✓ Hook React: polling 10 s + refresh en cambio de filtros |
| IPC endpoints | ✓ `analytics_counts`, `analytics_dwell`, `analytics_zone_events` en `IpcRouter` |
| Tauri commands | ✓ Typed Rust commands (`AnalyticsFilter` / `ZoneFilter`) sin tauri-specta |
| E2E básico | ✓ `test_f5_analytics_ipc.py` — 15 tests: stub + SQLite roundtrip + filtros |

**Criterio de salida**: ✓ Tab Analíticos operativo en shell Tauri sin Qt/QML; filtros, gráficas,
dwell y zonas funcionales; E2E básico verde — 514 pruebas verdes, 0 regresiones.
**Desviación aceptada**: `useLiveAnalytics` usa polling (10 s) en lugar de suscripción a eventos de
bus; la suscripción requeriría cablear el bus a los callbacks de `build_recording_backend`, lo cual
es scope de backend y no de UI — queda como mejora post-F5.

---

## Buenas prácticas (la barandilla hacia IA)

1. **El core nunca toca infraestructura.** `core/editor` y `core/analytics` no importan
   Qt/FFmpeg/Rust/torch. Toda inferencia vive en `adapters/ml/` detrás de `DetectorPort`.
2. **La grabación nunca se bloquea por ML** (principio Frigate). La inferencia corre
   *out-of-process* o en hilo aparte, alimentada por muestreo de frames y colas acotadas.
3. **Eventos = clip + metadatos.** Un `AnalyticEvent` es un intervalo temporal con datos
   estructurados; se materializa como clip (reusando el pipeline de eventos) y como entrada en
   `EventStore` + sidecar.
4. **Esquemas versionados.** `Detection`/`AnalyticEvent` son pydantic con `schema_version`; los
   cambios incompatibles suben versión y se documentan.
5. **Un ADR por decisión irreversible o discutida.** (timeline, trim, fullscreen, motor Rust,
   licencia de modelo, captura DXGI…). Ver [adr/](adr/).
6. **Determinismo del disparo.** El `EventContext` inmutable que ya congela la selección al disparar
   un evento se reutiliza tal cual para disparos automáticos — mismo código, misma garantía.
7. **Reutiliza fuentes de frames existentes**: los frames MJPEG de
   [`live_preview_service.py`](../../project/app/adapters/ffmpeg/live_preview_service.py) (tiempo real) o el
   decode de clips cerrados (batch) — no inventar una nueva tubería de captura para empezar.
8. **Ruta de inferencia permisiva.** Preferir modelo ONNX propio + `ort` (Apache/MIT) frente a
   Ultralytics (AGPL) para mantener el producto cerrado. Ver [ADR-0005](adr/ADR-0005-yolo-licensing.md).

---

## Track Rust (transversal)

| Hito | Qué | Fase |
|------|-----|------|
| Rust-1 | Motor de segmentos (`watcher_segments` .pyd) detrás de `SegmentCompilerPort` | 0 |
| Rust-2 | (opcional) Hash de integridad de evidencia (`sha2`/`blake3`) en el export | 0/1 |
| Rust-3 | Inferencia ONNX vía `ort` + DirectML como sidecar | 3 |
| Rust-4 | (diferido) Captura DXGI Desktop Duplication vs gdigrab — solo si la captura es el cuello de botella | post-4 · [ADR-0007](adr/ADR-0007-dxgi-capture-deferred.md) |
| Rust-5 | (post-F5) Port de `SqliteAnalyticsAdapter` a Rust puro (hexágono Track R) — solo cuando `ENGINE_READY` esté consolidado | Track R |
