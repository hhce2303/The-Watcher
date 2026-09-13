# 02 — Arquitectura y runtime

## Topología vigente

```text
React (`src/`)
  │ Tauri invoke / eventos
Tauri 2 shell (`src-tauri/`)
  │ pipe Windows autenticado, frames JSON
Python headless (`project/app/`)
  │ ApiLayer → servicios de dominio → puertos
Adapters: FFmpeg, FS/SQLite, monitor DXGI, WS, OneDrive, ML, native Rust
```

El JSON IPC transporta comandos y eventos de control. El contenido multimedia nunca usa esa vía: el protocolo `watcher://` de Tauri sirve JPEG de preview y archivos de video con soporte HTTP Range y lista de rutas permitidas.

## Hexágono Python

`project/app/core/` no debe importar FFmpeg, sistema de archivos, pywin32, `screeninfo`, Tauri ni infraestructura. Comportamiento nuevo se expresa primero como puerto en `core/ports/`; su implementación pertenece a `adapters/`; `main.py` es el único lugar que hace DI de implementaciones concretas.

Áreas principales:

| Área | Responsabilidad | Implementaciones destacadas |
|---|---|---|
| `recording_service` | workers por monitor, segmentos, retención, restarts y clips de evento | recorder/trim/timestamp FFmpeg, storage filesystem |
| `core/api` | APIs de recording/settings/editor/clips/requests/delivery, DTOs y EventBus | `IpcRouter` es el consumidor de entrada |
| `editor` | timeline de reel, orden y trims | exportador FFmpeg y compilador de segmentos |
| `analytics` / `auto_event_service` | detección, tracking, zonas, eventos y consultas | mock/ONNX, SQLite, batch y live inference |
| `player` | inspección de clips | `ffprobe` |
| `recording_health` / `disk_monitor` | degradación, recuperación y protección por disco | callbacks publicados al bus |

## Arranque

1. `main.py` configura logs, adquiere el mutex `TheWatcher_SingleInstance`, carga settings y usuario.
2. Aplica política de rol, autostart/watchdog y selecciona encoder/hardware.
3. Crea directorios, detecta monitores (sin monitor es error solo para roles que graban) y construye el backend por rol.
4. Crea `ApiLayer`, bus, solicitudes WS y servidor IPC; el pipe queda disponible antes de que termine el arranque potencialmente lento de grabación.
5. La inicialización de FFmpeg/servicios ocurre en hilo de fondo. Se recuperan segmentos existentes para completar clips tras un reinicio.

## Modos de proceso

| Modo | Quién lo usa | Terminación |
|---|---|---|
| `--daemon` | Operator | Independiente de la ventana; solo señales/parada explícita. |
| `--sidecar` | IT, Supervisor y sin rol | Se detiene por `shutdown` o EOF en stdin del padre Tauri. |

No se debe matar el sidecar con `process.kill()`: con PyInstaller puede sobrevivir el hijo del bootloader. Se ordena el shutdown por stdin.

## Captura y construcción

```text
MonitorDetectionService (poll 5 s)
  → MonitorWorker por pantalla
    → FFmpegRecorderAdapter: ddagrab preferido, gdigrab fallback
    → MPEG-TS `seg_*.ts` + `preview.jpg` a 2 fps
    → BufferManager: retención circular
    → HourlyRecordingBuilder: raw MP4 por monitor
    → CombinedClipBuilder: grid MP4 multi-monitor

EventService / AutoEventService
  → ClipBuilder: ventana pre/post y espera de post-roll
  → trim/remux + overlay temporal → clips_events/
```

Los índices de captura `ddagrab` proceden de DXGI `EnumOutputs` (`screeninfo_adapter.py`); no coinciden necesariamente con el orden de `screeninfo`.

## Rust

- `src-tauri/`: shell Windows, IPC, tray y protocolo de media.
- `project/native/watcher_segments/`: extensión PyO3/maturin. El código declara `ENGINE_READY=true`; se usa cuando la extensión está instalada y cae a FFmpeg si no está presente o falla. `CLIP_ENGINE=ffmpeg` fuerza el rollback para el camino de clips.
- El README de ese crate que lo llama “scaffold” está desactualizado frente a `src/lib.rs`, sus tests y el selector Python.

