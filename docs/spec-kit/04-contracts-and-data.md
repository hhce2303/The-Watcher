# 04 — Contratos, seguridad y datos

## Framing IPC

La shell y el backend intercambian frames JSON delimitados por longitud. Request: `{id, cmd, payload}`. Response: `{id, ok, result? , error?}`. Los errores de comando se devuelven en el frame y no deben tumbar el servidor. El pipe acepta un cliente a la vez y reconexión.

La fuente de verdad de comandos es `IpcRouter._build_handlers()`; `src/lib/ipc.ts` debe reflejarla. Cambiar un DTO exige actualizar `dto.py`, `src/types/dto.ts` y el snapshot generado `dto.gen.ts`.

## Comandos públicos

| Dominio | Comandos |
|---|---|
| Grabación | `get_recording_state`, `get_monitors`, `get_preview_server_info`, `trigger_event`, `start_recording`, `stop_recording`, `toggle_monitor` |
| Ajustes | `get_settings`, `get_media_roots`, `set_clips_dir`, `set_driver_index`, `set_codec`, `set_autorecord`, `set_autostart`, `apply_encoder_now`, `set_role`, `unlock_it` |
| Editor | `add_clip`, `add_clip_trimmed`, `add_files_from_urls`, `remove_clip`, `move_clip`, `set_trim`, `clear_timeline`, `export_timeline`, `editor_clip_count`, `get_timeline` |
| Clips | `list_clips`, `load_clip`, `list_directory`, `transcode_clip`, `cancel_transcode` |
| Solicitudes | `list_storages`, `list_operators`, `list_all_operators`, `send_clip_request`, `inbox_requests`, `my_requests`, `update_request_status` |
| Delivery | `compute_folder_path`, `ensure_folder_and_link`, `reset_onedrive`, `save_reel_privately` |
| Analítica | `analytics_counts`, `analytics_dwell`, `analytics_zone_events` |

## Eventos backend → frontend

El EventBus Python publica DTOs Pydantic y el pipe los reemite. Rust los vuelve eventos Tauri usando el discriminador snake_case; el payload completo conserva `{event, ...campos}`.

| Familia | Eventos |
|---|---|
| Grabación | `recording_state_changed`, `monitors_changed`, `recording_failed`, `recording_degraded`, `recording_recovered` |
| Clips/media | `clips_changed`, `clip_failed`, `transcode_started`, `transcode_progress`, `transcode_finished`, `transcode_failed` |
| Editor | `timeline_changed`, `export_started`, `export_progress`, `export_finished`, `export_failed` |
| Delivery | `onedrive_changed`, `onedrive_failed`, `onedrive_save_started`, `onedrive_saved`, `onedrive_save_failed` |
| Solicitudes/rol | `request_received`, `request_status_changed`, `role_changed`, `request_show_window` |
| Sistema | `log_message`, `encoder_restart_started`, `encoder_restart_finished`, `encoder_restart_failed` |

## Reglas de media y rutas

- `get_media_roots` entrega `segments_dir`, `clips_dir` y `storage_roots` después de conectar; Tauri los conserva para el protocolo.
- Antes de servir un archivo, Rust hace `canonicalize()` y exige que esté bajo una raíz permitida. Una ruta fuera de esas raíces responde 403.
- `Range` debe conservarse para reproducción/seek. Los JPEG se sirven `no-store`; video con `no-cache`.
- El servidor MJPEG HTTP es auxiliar y exclusivo de Operator; debe seguir ligado a `127.0.0.1`, nunca a LAN.

## Persistencia relevante

- User config: `%LOCALAPPDATA%\The Watcher\user_config.json`.
- Auditoría y eventos/analítica: SQLite bajo el área de datos (`events.db` se construye junto a `segments`).
- Solicitudes: adaptador JSON local y WebSocket `websockets` para IT/Supervisor.
- `.env` es local y no se versiona; no poner credenciales NAS ni secretos OneDrive en commits.

