# Glosario

> Términos de dominio usados en toda la documentación de arquitectura (`goals.md`,
> `roadmap.md`, `traceability-matrix.md`, `nfr.md`, [ADRs](adr/)) y en el código.
> Una definición por término — si un término tiene dos sentidos en el repo, aquí se
> resuelve cuál es el canónico. Enlaza con [[nfr.md]] y [[CONTRIBUTING.md]] (raíz del
> repo) para las convenciones que dependen de estos términos.
>
> Estado: vivo · Fecha: 2026-09-13

---

## Roles y topología de proceso

| Término | Definición |
|---|---|
| **Operador (Operator)** | Rol de la estación que graba de forma continua. Corre como **daemon always-on** desacoplado de la UI (sobrevive a un cierre de ventana), supervisado por un *watchdog* de SO. Ver [ADR-0010](adr/ADR-0010-role-conditional-topology.md). |
| **IT** | Rol con acceso al tab de edición y a la configuración de la estación. Corre como **sidecar** que muere con la app (no always-on). Desbloqueado por `IT_PIN` (ver [`nfr.md`](nfr.md) NFR-Seg-2). |
| **Supervisor** | Rol de solo-observación remota (vista en vivo de un Operador vía `LiveViewPort`). También **sidecar**, no always-on. |
| **Sidecar** | Proceso Python (empaquetado one-file PyInstaller) que la UI Tauri lanza y controla; termina por comando **stdin/stdout**, nunca por `process.kill()` — el kill solo alcanza el bootloader de PyInstaller, no el intérprete Python real (TD-3, `tech-debt-and-best-practices.md`). |
| **Daemon always-on** | Topología del rol Operador: el proceso de grabación sigue vivo aunque la ventana/UI se cierre; un *watchdog* de SO (Windows Scheduled Task o clave `HKCU Run` como *fallback*) lo relanza si termina. |
| **Watchdog** | Mecanismo de reinicio automático del daemon del Operador. Hoy solo detecta **salida del proceso** (crash/kill), no un *hang* con el proceso vivo pero congelado — ver `TODOS.md` #1. |

## Arquitectura hexagonal (core / ports / adapters)

| Término | Definición |
|---|---|
| **Core (`app/core/`)** | Dominio y casos de uso. **No importa** Qt, FFmpeg, Rust, ni nada de infraestructura o UI. Verificable por inspección + tests sin dependencias gráficas (NFR-Core-1). |
| **Port** | Interfaz abstracta (ABC) definida en `core/ports/` que el dominio invoca sin conocer la implementación concreta. Ej.: `RecorderPort`, `ClipPort`, `SegmentCompilerPort`, `EditorExportPort`, `DetectorPort`, `EventStorePort`, `LiveViewPort`. |
| **Adapter** | Implementación concreta de un *port* bajo `app/adapters/` (FFmpeg, SQLite, filesystem, Rust nativo, ML, WS/IPC). Puede tener más de un adapter por *port* (ej. motor Rust vs. *fallback* FFmpeg). |
| **Composition root** | `app/main.py` — el único lugar que instancia adapters concretos y los cablea a los ports que el core consume. Ninguna otra parte del código construye dependencias concretas. |
| **`core/api` (ApiLayer)** | El **único puerto de entrada** al dominio: Facade + DTOs Pydantic + *event bus* thread-safe. Toda UI (named-pipe IPC hoy; QML históricamente) es un adaptador intercambiable sobre este puerto — ver [ADR-0009](adr/ADR-0009-input-port-facade.md). Especializado en `recording_api.py`, `settings_api.py`, `editor_api.py`, `clips_api.py`, `requests_api.py`, `delivery_api.py` (no existe un único `facade.py`; ver `AGENTS.md`). |
| **DTO** | Objeto Pydantic que cruza el límite `core/api` ↔ IPC. Cambios de forma requieren sincronizar `dto.py`, `src/types/dto.ts` y `npm run gen:dto:check`. |
| **Event bus** | Mecanismo thread-safe de `core/api` para publicar eventos de dominio (progreso de grabación, estado de salud, etc.) hacia los adaptadores de UI suscritos. |
| **Engine (motor nativo)** | Implementación Rust opcional de una operación de *hot path* (hoy: compilación de segmentos), expuesta vía PyO3/`maturin` como `.pyd`. Bandera `ENGINE_READY` indica si está disponible; si no, el adapter cae a FFmpeg sin romper la app (degradación elegante). |

## Grabación y pipeline de video

| Término | Definición |
|---|---|
| **Segmento (`seg_*.ts`)** | Fragmento de grabación continua en MPEG-TS, escrito bajo `segments/m{index}/` (uno por monitor). Unidad atómica que el motor de compilación concatena/recorta. |
| **Reel** | Línea de tiempo de edición de **una sola pista** que agrupa uno o varios clips, reordenables y recortables, para exportar como un único MP4. Descartado el multipista/NLE — ver [ADR-0001](adr/ADR-0001-evidence-reel-single-track.md). |
| **Trim (recorte)** | Marcas IN/OUT editables sobre un clip dentro del reel. El export usa *stream-copy* cuando el corte cae cerca de un *keyframe*, y re-encode solo del GOP de borde cuando se exige corte exacto por frame — ver [ADR-0002](adr/ADR-0002-smart-trim-copy-vs-encode.md). |
| **Stream-copy** | Copia de stream sin recodificar (bit-idéntica al origen). Preferida por defecto para no romper la cadena de custodia de la evidencia. |
| **GOP (Group of Pictures)** | Bloque de frames entre dos *keyframes*. Solo el GOP de borde se recodifica en un corte exacto por frame; el resto del clip queda intacto. |
| **Keyframe** | Frame codificado sin depender de otros (I-frame). Los cortes "baratos" (sin recodificar) solo pueden caer en un keyframe. |
| **ddagrab** | Fuente de captura DXGI Desktop Duplication usada por FFmpeg para eliminar el titileo del cursor visto con `gdigrab`. Los índices de monitor vienen de DXGI, **no** del orden de `screeninfo` — ver [ADR-0013](adr/ADR-0013-ddagrab-capture-cursor-flicker.md). |
| **Zero-copy (pipeline QSV/CUDA)** | Ruta de captura donde el frame D3D11 se entrega directo al encoder por hardware (QSV/NVENC) sin pasar por RAM del sistema — ver [ADR-0014](adr/ADR-0014-zerocopy-qsv-capture-pipeline.md). |
| **`segment_floor`** | Invariante de `buffer_manager.py`: nunca se concatenan segmentos de configuraciones de monitor incompatibles (dimensiones distintas). Ver NFR-Rel-3 en [`nfr.md`](nfr.md). |
| **Job Object (batch)** | Job de Windows compartido al que se asignan todos los procesos FFmpeg *offline*/background (builders horarios, converter, analyzer) para acotar CPU/memoria/prioridad frente al grabador — ver [ADR-0015](adr/ADR-0015-batch-ffmpeg-governance.md). El grabador **nunca** entra a este Job con *hard cap* (un *hard cap* lo congelaría). |
| **Semáforo de concurrencia batch** | `MAX_BATCH_FFMPEG` — límite global de procesos FFmpeg batch corriendo a la vez en todo el proceso Python, independiente del monitor de origen. |
| **Coalescencia de eventos automáticos** | Ventana mínima (`EVENT_AUTO_BUILD_MIN_INTERVAL_SECONDS`) que evita que una detección continua dispare un re-encode de clip cada pocos segundos — ver [ADR-0019](adr/ADR-0019-auto-event-clip-build-coalescing.md). |

## IA / Analíticos (costuras)

| Término | Definición |
|---|---|
| **Detection** | Modelo Pydantic (con `schema_version`) que representa una detección puntual de un frame (clase, bbox, confianza). |
| **AnalyticEvent** | Intervalo temporal con datos estructurados derivado de una o más `Detection`; se materializa como clip (reusando el pipeline de eventos manuales) + entrada en `EventStore` + sidecar `*.events.json`. |
| **DetectorPort** | Puerto que abstrae el motor de inferencia (mock hoy; ONNX + `ort`/DirectML en Fase 3 — ver [ADR-0005](adr/ADR-0005-yolo-licensing.md) sobre la licencia del modelo). |
| **AutoEventService** | Servicio que se suscribe al `DetectorPort` y dispara el mismo flujo de captura de evento (`snapshot_event()`/`build()`) que un disparo manual, con cooldown/coalescencia. |
| **IouTracker** | Tracker ligero estilo SORT (sin `scipy`) que asocia detecciones entre frames por *Intersection-over-Union*. |
| **Zone (zona)** | Polígono normalizado sobre el frame; usado con *ray-casting* para atribuir eventos/dwell a un área del encuadre. |

## Seguridad y canal IPC

| Término | Definición |
|---|---|
| **Named pipe autenticado** | Canal IPC local de Windows, *scoped* al usuario, usado por React↔Python en vez de un puerto TCP loopback abierto — ver [ADR-0011](adr/ADR-0011-local-ipc-security.md). |
| **`watcher://`** | Protocolo custom de Tauri para servir video/preview (nunca JSON IPC) preservando soporte de `Range` HTTP y el *allowlist* de rutas del lado Rust. |
| **Audit log** | Registro persistente (SQLite, `AuditPort`) de todo intento de desbloqueo de IT / cambio de rol, con origen y timestamp — ver [ADR-0011](adr/ADR-0011-local-ipc-security.md). |
| **`IT_PIN`** | PIN que desbloquea el rol IT. Trae un *default* inseguro (`"1234"`) marcado como TODO de seguridad abierto (`TODOS.md` #10) — ver NFR-Seg-2. |

| **Browser-local** | Canal externo navegador↔daemon del iframe Daily, independiente del named pipe Tauri. Usa HTTPS/WSS exclusivamente en `127.0.0.1`/`::1`, assertions Ed25519 emitidas por Daily y capabilities opacas para media. Ver [ADR-0020](adr/ADR-0020-browser-local-daily-channel.md). |
| **Assertion Watcher** | JWT EdDSA de 60 s y un solo uso emitido por la Edge Function de Daily para un usuario, dispositivo y sitio enrolados. Se entrega al hijo local mediante `postMessage`, se canjea por una sesión de memoria y nunca aparece en URL o logs. |

## Convenciones de trazabilidad

| Término | Definición |
|---|---|
| **ADR** | *Architecture Decision Record*. Una decisión estructural por archivo, numerada `ADR-NNNN`, con ciclo de vida `Aceptado` / `Diferido` / `superseded by ADR-NNNN`. Nunca se borra. Ver [`adr/README.md`](adr/README.md). |
| **NFR** | Requisito no funcional con ID estable (`NFR-<área>-N`). Ver [`nfr.md`](nfr.md) — complementa los `R-NF*` locales al tab de edición en [`goals.md`](goals.md). |
| **R-N / R-NFN** | IDs de requisitos funcionales/no funcionales *scoped* al tab de edición, definidos en [`goals.md`](goals.md) y verificados en [`traceability-matrix.md`](traceability-matrix.md). |
| **TD-N** | Entrada del registro de deuda técnica en [`tech-debt-and-best-practices.md`](../migration/tech-debt-and-best-practices.md) (migración Tauri). |
| **EPIC-NNN / US-NNN / FB-NNN** | IDs del backlog de feedback de usuarios (fuera del ciclo de ADRs) — ver [`docs/backlog/`](../backlog/README.md). |
