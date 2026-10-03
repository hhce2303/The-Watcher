# ADR-0002 — Raíz de composición delgada y `DaemonApi` mínima

- **Estado**: Aceptado
- **Fecha**: 2026-10-03
- **Requisitos**: ADR-0001; spec de extracción §4.

## Contexto

`app.main` arrastraba 134 de 142 archivos del monorepo porque `main.py`, `runtime/backend.py` y
`core/api/bootstrap.py::ApiLayer` cablean todo (roles, IPC, editor, player, analítica, cloud). `LiveViewLanAdapter`
recibía `ApiLayer` pero solo llama `api.recording.get_recording_state()` y `api.recording.get_monitors()`
(`app/adapters/live_view_lan/server.py`). El resto de sus dependencias son puertos (`LiveViewPort`, `TlsMaterialPort`).

## Decisión

- `app/daemon_root.py` sustituye a `main.py` + `runtime/backend.py`. Cablea config → monitores →
  `RecordingService` + salud + `DiskSpaceMonitor` → `LiveViewLanAdapter` (+ TLS vía `TlsMaterialPort`).
  Arranque: el endpoint LAN primero; el arranque de grabación (probes de ffmpeg, lentos) en un hilo de fondo.
- `app/daemon_api.py::DaemonApi` es la fachada mínima: `recording.get_recording_state()` y
  `recording.get_monitors()`. Los monitores exponen `index`, `x`, `y` y `resolution` con formato
  `"<ancho>×<alto>"` (U+00D7), el formato que `h264_feed.parse_resolution` consume. **Regla**: si un adaptador
  necesita algo más, se añade a `DaemonApi` junto con su puerto; no se copia `ApiLayer`.
- Rol Operador fijo: se elimina `enforce_role`, `core.role`, `core.policy`, `user_config.json` y el IT PIN. Se
  conservan autostart y el watchdog (Scheduled Task con restart-on-failure; fallback a la clave Run de HKCU).
- Sin IPC, sin Qt, sin Tauri. Control por CLI (`start`, `stop`, `status`, `health`) y archivos de estado en
  `<segment_dir>/..` (`daemon.lock`, `daemon-status.json`, `daemon.stop`); `--daemon` se acepta como alias de
  `start` porque las tareas programadas ya registradas lo pasan. `stop` usa un archivo y no una señal porque
  `os.kill` en Windows termina el proceso en seco y dejaría ffmpeg huérfano.
- `runtime/headless.py` se reescribe sin pipe ni `ApiLayer`: solo señales + stop-file + teardown idempotente.
- `browser_local/__init__.py` queda **vacío**: el original reexportaba `BrowserLocalAdapter` (`server.py` →
  `core.api` → editor/player/rol) y se ejecuta al importar `browser_local.auth`.

## Consecuencias

- Positivas: cierre de imports de ~55 archivos de `app/`; el test de pureza es verificable.
- Negativas: se pierde la configuración por usuario que vivía en `user_config.json` (`driver`, `codec`,
  `clips_dir`): ahora todo sale de `.env`. El instalador ya no escribe ese perfil. El `status`/`health` leen un
  archivo de estado (no un endpoint): no detectan nada si el disco del estado falla. El `LiveViewLanAdapter`
  sigue sin tests contra la fachada real fuera de los dobles (`SimpleNamespace`) de `test_live_view_stream.py`.
- `health` en Windows requiere `watcherctl.exe` (build de consola): `The Watcher.exe` es windowed y no tiene stdout.

## Opciones no elegidas

- Copiar `ApiLayer` con ramas deshabilitadas: arrastra editor/player/analítica y rompe el gate de pureza.
- Mantener el pipe IPC "por si acaso": viola el alcance (consumidor único LAN) y ADR-0011 exige autenticación.
