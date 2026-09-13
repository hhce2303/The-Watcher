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
  [ADR-0011](../architecture/adr/ADR-0011-local-ipc-security.md).
- **Audit:** `startRecording`/`stopRecording`/`unlockIT`/`setRole` se loguean al event store con
  origen y timestamp.
- El WS de `adapters/ws/` (IT↔Supervisor, inter-máquina) es **otro** canal, no este.
- **Polling → push:** hoy `app_bridge.py` hace polling (grabación @1 s, preview @500 ms); migrar a
  eventos push por el bus donde se pueda.

## Matriz de tecnología por puerto (destino Rust — Track R)

Orden = prioridad de migración a Rust. Binding = **PyO3 in-process** durante la transición →
**comando Tauri nativo** en el endgame. Ver [ADR-0012](../architecture/adr/ADR-0012-rust-hexagon-endgame.md).

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
| **sin secuenciar** | `LiveViewPort` *(nuevo, post-migración)* | sesión/token/auditoría + rama de encode H.264 sobre el pipeline FFmpeg existente, canal WS binario cifrado (`wss://`) | **Por decidir** — no está en el orden R1-R4 de ADR-0012; Go fue evaluado y diferido como ruta de escalación, ver [ADR-0018](../architecture/adr/ADR-0018-go-liveview-relay-escalation-deferred.md) |

### `LiveViewPort` — extensión post-migración (2026-07-12)

Feature nueva, no parte de la migración Tauri original: Supervisor obtiene vista en vivo,
solo-lectura, LAN-only, de la pantalla de un Operador (paridad con el acceso que IT ya
tiene vía TeamViewer). Sigue el mismo patrón Facade/DTO de ADR-0009 (`LiveViewApi` nuevo,
espejo de `RequestsApi`). Diseño completo (premisas, alternativas evaluadas, revisiones
adversariales de arquitectura/seguridad/tests) en la sesión `/office-hours` + `/autoplan`
del 2026-07-12, rama `feat/f1-backend-headless`. Puntos clave para quien retome esto:

- **No está secuenciado en el roadmap Track R** (ADR-0012) — antes de asignarle una
  prioridad de port-a-Rust, confirmar con el owner de Track R si esto compite o no con
  el trabajo ya en curso (Track R2).
- **Prerequisito bloqueante antes de rollout a la flota real** (no antes de implementar):
  política de "quién puede ver a quién" — ver TODOS.md, ítem 9. La arquitectura/DTO puede
  avanzar con un placeholder; el rollout no.
- **Gate técnico dentro del prototipo de 48h**: confirmar si una falla en la rama de
  live-view puede tumbar el proceso de grabación completo (`recorder_adapter.py` corre
  UN proceso FFmpeg por monitor) — determina si el esfuerzo estimado (L) es correcto o
  si hace falta un diseño de proceso separado.

## Fases (orden estricto)

| Fase | Qué | Estado |
|------|-----|--------|
| **F0** | Gate GO/NO-GO **bloqueante**: 6 spikes en máquina real (ver [how-to F0](howto-f0-gate.md)) | ✅ GO (2026-07-02) |
| **F1** | Backend headless: `core/api` (Facade+DTOs+bus), `adapters/ipc`, arranque por rol; QML sigue vivo | ✅ **cerrada** (2026-07-04, `feat/f1-backend-headless`) |
| **F2** | UI React a paridad, vista por vista (editor al final) | ✅ **cerrada** (2026-07-06) |
| **F3** | Cutover: **eliminación total de QML+PySide6**, WS Qt-free, scripts Tauri-first | ✅ **cerrada** (2026-07-06, dev-only — instalador Tauri es fase siguiente) |
| **Track R** | Hexágono Rust port-por-port vía PyO3 (post-cutover) | 1er port live (`ENGINE_READY=true`) |

## Archivos afectados

**Eliminados (F3):** todo `project/app/adapters/ui/` (`app_bridge.py`, `settings_bridge.py`,
`editor_bridge.py`, `tray_icon.py`, `screenshot_provider.py`, `log_handler.py`, `main_window.py`,
`button_trigger.py`, `Main.qml` + 28 `.qml` + 2 `qmldir`), `project/prototype/` completo, y los
tests Qt (`qml_smoke.py`, `qml_runtime_smoke.py`, `test_ws_inbound.py`, `test_ws_outbound.py`,
`test_app_bridge_onedrive.py`, `test_editor_bridge.py`, `test_settings_bridge.py`).

**Reescritos sin Qt (F3):** `project/app/adapters/ws/request_server.py` y `request_client.py`
(de `QWebSocketServer`/`QWebSocket` a `websockets` + asyncio-en-hilo, mismo protocolo de wire —
IT↔Supervisor siguen interoperando); `project/app/infrastructure/logging_setup.py` (sink Qt →
evento de bus `LogMessage`); `project/app/runtime/mode.py` (sin flag → `--daemon` para Operador,
`--sidecar` para el resto; ya no existe modo QML).

**Modificados:** `project/app/main.py` (cirugía completa — sin bootstrap PySide6, sin bloque QML,
wiring de requests/fallos/callbacks compartido antes de la rama daemon/sidecar),
[`project/run.ps1`](../../project/run.ps1) y [`project/run_dev.ps1`](../../project/run_dev.ps1) (Tauri por defecto,
backend por rol, sin env vars Qt), [`project/installer/build.ps1`](../../project/installer/build.ps1) +
`The Watcher.spec` (bundle headless-only, sin PySide6), `project/requirements.txt` (purgado
`PySide6*`/`shiboken6`, añadido `websockets`).

**Se crean (F2):** `project/app/core/api/` (Facade+DTOs+bus), `project/app/adapters/ipc/` (canal
local), `src-tauri/` (protocolo custom `watcher://`, tray, single-instance, política de cierre),
frontend React completo (`src/features/*`, `src/shell/*`, `src/components/W*`).

**Se reusa intacto:** `project/app/core/**`,
`adapters/{ffmpeg,filesystem,cloud,storage,monitor,native}/**`, el scheduled-task watchdog, y como
semilla de Track R: `project/native/watcher_segments/` (hoy scaffold, `ENGINE_READY=false`).

## Verificación (por fase)
- Ejecuta pruebas visuales y build con [`run.ps1`](../../project/run.ps1) / [`installer/build.ps1`](../../project/installer/build.ps1) (reutilizados y evolucionados — no scripts paralelos).
- F0: ver criterios numéricos en el [how-to F0](howto-f0-gate.md).
- **F1 (✅ cerrada 2026-07-04, rama `feat/f1-backend-headless`):**
  - ✅ `pytest` verde — 428 passed, 10 skipped (los skips son la paridad Rust).
  - ✅ El canal IPC responde el contrato — round-trip sobre named pipe real + eventos streamed + rechazo de comando desconocido (`tests/test_ipc_*`), y smoke en vivo de `--sidecar` (bindea `\\.\pipe\TheWatcher.<user>`, shutdown por stdin, exit 0).
  - ✅ Auditoría (ADR-0011): `start/stop/unlock/setRole` en la ruta QML (event store como `AuditPort`) y en la ruta IPC (`origin="ipc"`).
  - ✅ Seguridad (ADR-0011): SDDL scoped al usuario, sin puerto TCP.
  - ➖ **Sign-off en máquina real (riesgo aceptado por el owner, 2026-07-04):** (1) arranque interactivo de la UI QML por rol y (2) build congelado `installer/build.ps1` con pywin32 — no ejecutados en CI; se validan en el despliegue.
  - Entregado: `core/api/` (EventBus thread-safe, DTOs Pydantic, facades Recording/Settings/Editor/Clips/Requests/Delivery, bootstrap), `adapters/ipc/` (named pipe + SDDL + router + audit), `adapters/filesystem/file_browser_adapter.py`, `runtime/` (mode + headless daemon/sidecar + build_recording_backend). Los 3 bridges QML delegan a las facades (coexistencia dual-path); `main.py` cablea un `ApiLayer` compartido y despacha `--daemon`/`--sidecar`.
- **F2/F3 (✅ cerradas 2026-07-06):**
  - ✅ Auditoría de paridad IPC: los 43 comandos que invoca el frontend existen en `router.py`, y los 43 comandos del router se consumen — sin huérfanos en ninguna dirección. Los 24 eventos de `dto.py` están declarados en `BackendEventMap` del frontend.
  - ✅ `pytest` verde — 481 passed, 10 skipped; cero referencias a `PySide6`/`adapters.ui` en `project/app` y `project/tests`.
  - ✅ `cargo check` limpio + 5 tests unitarios Rust (protocolo custom, allowlist de rutas).
  - ✅ `npm run build` (tsc + vite) y `npx vitest run` (41 tests) verdes.
  - ✅ Bug real encontrado y corregido: `ClipRequestServer.stop()` colgaba 5s por una carrera entre `loop.stop()` y `run_coroutine_threadsafe` (ver `adapters/ws/request_server.py`).
  - ➖ **Descoped (documentado, no bloqueante):** gestión de puerto WS de IT desde Settings (`open_it_ws_port` + hosts — el DTO existe, sin resto de comandos), telemetría real de `HealthBadge` (CPU/DISK/FPS siguen simulados, igual que QML). Empaquetado del instalador Tauri (bundlear el backend como `externalBin`) es fase posterior — alcance de esta migración fue "solo dev + purga".
  - Aceptación (pendiente de validar en hardware real, no ejecutable en este entorno): matar la ventana → grabación de Operador **continúa** (daemon decoupled); cerrar app IT/Supervisor → **sin** proceso huérfano (sidecar vía stdin); export de reel server-side idéntico al QML (TD-7: sin scrub frame-exact desde `<video>`); preview en vivo por protocolo custom (TD-5: nunca por invoke JSON); fallback HEVC→H.264 on-demand (TD-1).

## Relacionado
- [Explicación — Por qué migrar](explanation-tauri-migration.md)
- [How-to F0](howto-f0-gate.md) · [How-to migrar vista](howto-migrate-view.md) · [How-to portar a Rust](howto-port-to-rust.md)
