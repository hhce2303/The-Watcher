# Referencia — Arquitectura objetivo de la migración a Tauri 2.0

Descripción técnica de la arquitectura destino: componentes, matriz de tecnología por puerto,
contrato IPC, archivos afectados y fases. Fáctico; el *por qué* está en la
[explicación](explanation-tauri-migration.md).

## Diagrama de la arquitectura objetivo

```
                 ┌──────────────────────── OPERADOR ────────────────────────┐
                 │  Scheduled-task watchdog ──lanza/reinicia──►  Python DAEMON │
                 │                                               (always-on)   │
                 │   tray • single-instance • autostart • grabación • IPC local│
                 └───────────────────────────────▲──────────────────────────┘
                                                  │  canal IPC local (mismo contrato)
   ┌─── Tauri (Rust) ────────────────┐           │
   │  WebView2 + React (UI)          │◄───────────┘  (cliente opcional/mínimo p/ Operador)
   │  Plugins: tray, autostart,      │
   │  single-instance, updater       │           ┌──────────── IT / SUPERVISOR ─────────────┐
   │  Custom protocol: preview/thumbs │──spawn───►│  Python SIDECAR (externalBin)             │
   │  Comandos Rust nativos (futuro) │  externalBin│  vive y muere con la app • IPC local      │
   └─────────────────────────────────┘           └───────────────────────────────────────────┘
                                                  │
                                                  ▼
   ┌──────────────────── core/api Facade (INPUT PORT — sin Qt/WS/JSON) ─────────────┐
   │ RecordingApi • SettingsApi • EditorApi   +   Event Bus (thread-safe)           │
   └───────────────────────────────┬────────────────────────────────────────────────┘
                                    ▼
   ┌──────────────────────── CORE PYTHON (sin Qt — INTACTO) ───────────────────────┐
   │ RecordingService • BufferManager • RecorderSupervisor • EventService           │
   │ ClipBuilder • EditTimeline • TimelineSequencer • CloudShareService • Player     │
   │ ports/ (RecorderPort, ClipPort, CloudSharePort, EditorExportPort, ...)          │
   └───────────────┬───────────────────────────┬───────────────────────┬───────────┘
                   ▼                           ▼                       ▼
            adapters/ffmpeg              adapters/filesystem        adapters/cloud, ws, native
```

- Capas que **NO cambian**: `core/`, `adapters/{ffmpeg,filesystem,cloud,storage,monitor,native}`.
- Capa que se **reemplaza y luego se elimina**: `adapters/ui/`.
- Capa con **limpieza menor**: `adapters/ws/` (quitar `QObject parent`).

## Puerto de entrada (`core/api`) — la frontera UI ↔ core

Paquete nuevo `project/app/core/api/`, **sin Qt, sin WS, sin JSON**:

| Componente | Contenido |
|-----------|-----------|
| Facade | `recording_api.py`, `settings_api.py`, `editor_api.py` — la unión de lo que hacen los 3 bridges, como métodos que aceptan comandos (DTOs) y devuelven DTOs. Por dentro llaman a los servicios existentes. |
| DTOs | `dto.py` (Pydantic) — comandos + eventos. Fuente única del contrato; de aquí se generan los tipos TS (Pydantic → JSON Schema → TS). |
| Event bus | `events.py` — registro de observadores thread-safe (`subscribe`/`publish`). Reemplaza las Qt Signals. Normaliza los callbacks del core (`on_segment_finalized`, `on_clip_built`, `on_monitors_changed`) a eventos tipados. |

**Regla de oro:** `core/api` no conoce Qt, ni WS, ni JSON. Cada adaptador de entrada conoce su
transporte pero no la lógica. El único lugar con serialización es `adapters/ipc/`.

## Contrato IPC — mapeo bridges QML → comandos/eventos

Fuente: los 6 bridges Qt actuales en `project/app/adapters/ui/`. Cada slot → un comando; cada Signal
→ un evento del bus.

| Bridge actual (Qt) | LOC | Comandos (request→response) | Eventos (push backend→UI) |
|--------------------|-----|------------------------------|----------------------------|
| `app_bridge.py` | 1006 | `triggerEvent`, `startRecording`, `stopRecording`, `toggleMonitor`, `loadClip`, `listDirectory`, `listStorages`, `listOperators`, `sendClipRequest`, `getInboxRequests`, `getMyRequests`, `ensureFolderLink` (~30 slots) | `isRecordingChanged`, `recordSecChanged`, `monitorsChanged`, `clipsChanged`, `recordingFailed`, `logMessage`, `requestShowWindow` |
| `settings_bridge.py` | 449 | `setClipsDir`, `setDriverIndex`, `setRole`, `unlockIT`, `setAutostart`, `openItWsPort` + getters | `clipsDirChanged`, `encoderChanged`, callbacks: restart / relaunch / autorecord |
| `editor_bridge.py` | 296 | `addClip`, `addClipTrimmed`, `addFilesFromUrls`, `exportTimeline` | `timelineChanged`, `exportStarted`, `exportProgress(float)`, `exportFinished(str)`, `exportFailed(str)` |
| `screenshot_provider.py` | 47 | (imagen) | reemplazado por **custom protocol** Tauri o endpoint HTTP local de frames/thumbs |
| `tray_icon.py` | 81 | — | reemplazado por **plugin tray** de Tauri / tray del daemon |
| `log_handler.py` | 19 | — | stream de logs por el canal |

### Transporte y seguridad
- **NO** un TCP WebSocket abierto. **Named pipe de Windows** (scoped al usuario/sesión) o, si TCP en
  loopback, **token burned-in en build-time**. Ver
  [ADR-0011](../editing/adr/ADR-0011-local-ipc-security.md).
- **Audit:** `startRecording`/`stopRecording`/`unlockIT`/`setRole` se loguean al event store con
  origen y timestamp.
- El WS de `adapters/ws/` (IT↔Supervisor, inter-máquina) es **otro** canal, no este.
- **Polling → push:** hoy `app_bridge.py` hace polling (grabación @1 s, preview @500 ms); migrar a
  eventos push por el bus donde se pueda.

## Matriz de tecnología por puerto (destino Rust — Track R)

Orden = prioridad de migración a Rust. Binding = **PyO3 in-process** durante la transición →
**comando Tauri nativo** en el endgame. Ver [ADR-0012](../editing/adr/ADR-0012-rust-hexagon-endgame.md).

| # | Puerto (`core/ports/`) | Adapter Python hoy | Tecnología Rust objetivo |
|---|------------------------|--------------------|--------------------------|
| 1 | `RecorderPort` | `FFmpegRecorderAdapter` (gdigrab+FFmpeg) | `windows-capture`/XCap + encoder |
| 1 | `ClipPort` | `FFmpegTrimAdapter`, `CombinedClipBuilder` | mux/demux Rust (`mpeg2ts-reader`+`muxide`) |
| 2 | `EditorExportPort` | `FFmpegEditorExportAdapter` | mismo motor de segmentos Rust |
| 3 | `PlayerPort`/`ClipInspectorPort` | `FFprobeClipInspectorAdapter` | `symphonia` o wrapper ffprobe |
| 3 | `MonitorPort` | `ScreeninfoMonitorAdapter` | crate `windows` / XCap monitors |
| 4 | `StoragePort`/`EventStorePort`/`UserConfigPort` | filesystem/sqlite/json | `tokio::fs` / `rusqlite` / `serde_json` |
| 5 | `RequestPort` + `adapters/ws` | `JsonRequestAdapter` + WS | `tokio-tungstenite` |
| último | `CloudSharePort` | `LocalShareAdapter`/`OneDriveGraphAdapter` | `reqwest`+MS Graph o queda plugin/HTTP |

## Fases (orden estricto)

| Fase | Qué | Estimación |
|------|-----|-----------|
| **F0** | Gate GO/NO-GO **bloqueante**: 6 spikes en máquina real (ver [how-to F0](howto-f0-gate.md)) | ~1-2 sem / CC ~2-4 d |
| **F1** | Backend headless: `core/api` (Facade+DTOs+bus), `adapters/ipc`, arranque por rol; QML sigue vivo | ~1-2 sem |
| **F2** | UI React a paridad, vista por vista (editor al final); F2a-d + buffer | ~8-13 sem |
| **F3** | Cutover: rollout por cohorte, empaquetado Tauri, **eliminación total de QML+PySide6** | ~2-3 sem |
| **Track R** | Hexágono Rust port-por-port vía PyO3 (post-cutover) | incremental |

## Archivos afectados

**Se reemplazan y luego se ELIMINAN** (F3): todo `project/app/adapters/ui/` — `app_bridge.py`,
`settings_bridge.py`, `editor_bridge.py`, `tray_icon.py`, `screenshot_provider.py`,
`log_handler.py`, `main_window.py`, y los 29 `.qml` bajo `adapters/ui/qml/`.

**Se modifican:** `project/app/main.py` (arranque daemon/sidecar; quitar bootstrap Qt),
`project/app/adapters/ws/request_server.py` y `request_client.py` (quitar `parent` Qt),
[`project/run.ps1`](../../run.ps1) (lanzar Tauri dev + backend por rol; retirar env vars Qt en F3),
[`project/installer/build.ps1`](../../installer/build.ps1) + `The Watcher.spec` (sidecar + bundler
Tauri), `project/requirements.txt` (purgar `PySide6*`/`shiboken6` en F3).

**Se crean:** `project/app/core/api/` (Facade+DTOs+bus), `project/app/adapters/ipc/` (canal local),
`src-tauri/` (proyecto Tauri), frontend React (`src/`, tema desde `Tokens.qml`, componentes desde los
`W*`).

**Se reusa intacto:** `project/app/core/**`,
`adapters/{ffmpeg,filesystem,cloud,storage,monitor,native}/**`, el scheduled-task watchdog, y como
semilla de Track R: `project/native/watcher_segments/` (hoy scaffold, `ENGINE_READY=false`).

## Verificación (por fase)
- Ejecuta pruebas visuales y build con [`run.ps1`](../../run.ps1) / [`installer/build.ps1`](../../installer/build.ps1) (reutilizados y evolucionados — no scripts paralelos).
- F0: ver criterios numéricos en el [how-to F0](howto-f0-gate.md).
- F1: `pytest` sigue verde; el canal IPC responde el contrato; QML aún levanta contra los mismos servicios.
- F3 (aceptación): matar la ventana → grabación de Operador **continúa**; cerrar app IT/Supervisor → **sin** proceso huérfano; export de reel frame-exact idéntico al QML; bundle medido vs 259 MB.

## Relacionado
- [Explicación — Por qué migrar](explanation-tauri-migration.md)
- [How-to F0](howto-f0-gate.md) · [How-to migrar vista](howto-migrate-view.md) · [How-to portar a Rust](howto-port-to-rust.md)
