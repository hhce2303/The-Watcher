# 05 — Calidad, operación y guía de cambios

## Entorno y comandos

Windows 10/11 es requisito de producto. Usar `uv`, Node 22+, FFmpeg en PATH y Rust/MSVC para shell/motor nativo. `setup_env.ps1` usa `uv` para instalar/seleccionar Python 3.13 y deja el venv en `%LOCALAPPDATA%\The Watcher\venv` para no sincronizarlo con OneDrive; no depende de un `python` global en PATH.

```powershell
# Raíz: setup y frontend
.\setup_env.ps1
npm install
npm run lint
npx tsc --noEmit -p tsconfig.json
npm run test
npm run gen:dto:check

# Backend (desde raíz; CI también usa esta forma)
$env:PYTHONPATH = "project"
$twPython = Join-Path $env:LOCALAPPDATA "The Watcher\venv\Scripts\python.exe"
& $twPython -m pytest project/tests -q

# Shell Tauri
cd src-tauri
cargo test

# Ejecución completa desde raíz
.\Start-TheWatcher.ps1
.\Start-TheWatcher.ps1 -NoUi -BackendMode Daemon
.\Start-TheWatcher.ps1 -NoUi -BackendMode Sidecar
```

El CI de GitHub Actions es Windows y ejecuta pytest con FFmpeg, lint, type-check, Vitest, comprobación DTO y `cargo test`. No construye aún el instalador Tauri.

`Start-TheWatcher.ps1` es el lanzador recomendado para desarrollo completo: lee el rol persistido,
inicia el backend y la shell Tauri, conserva el daemon de Operator y manda `shutdown` por stdin a
los sidecars. `project/run.ps1` sigue siendo el lanzador histórico equivalente, pero su limpieza
actual usa una finalización brusca del proceso Python; no usar ese patrón para rutas nuevas.

## Playbooks de cambio

### Cambio de comportamiento backend

1. Mantener la lógica en `core/`; declarar/extender el puerto requerido.
2. Implementar el adapter fuera del core y cablearlo únicamente en `main.py` o el builder apropiado.
3. Añadir prueba unitaria del dominio y prueba del adapter/contrato cuando aplique.

### Cambio de comando o evento IPC

1. Cambiar el API especializado y DTOs en `project/app/core/api/`.
2. Registrar el comando en `IpcRouter`; actualizar `src/lib/ipc.ts`.
3. Reflejar tipos manualmente en `src/types/dto.ts` y ejecutar `npm run gen:dto:check` para el snapshot.
4. Consumir comandos desde hooks/store, no directamente desde componentes React.

### Cambio de UI o media

1. React solo cruza al backend mediante `src/lib/ipc.ts` y escucha con `useBackendEvent`/Tauri events.
2. Nunca transportar preview o video por `invoke`/JSON. Usar `mediaUrl.ts` y `watcher://`.
3. Mantener la política de cierre también en Rust: no delegarla solo a JavaScript.

### Cambio de grabación/FFmpeg

1. Mantener segmentos `.ts`; la implementación actual de `FilesystemStorageAdapter.list_segments()` ya busca `seg_*.ts`.
2. Usar `subprocess` directamente, no `ffmpeg-python` (la dependencia está presente pero no es el mecanismo usado).
3. Conservar el Job Object, semáforo global y límites batch para trabajo offline; no aplicar el hard cap batch al recorder vivo.
4. Probar recuperación, hot-plug y cancelación, no solo construcción de argumentos FFmpeg.

## Riesgos conocidos / trabajo pendiente

- Falta pipeline de release/installer Tauri y bundle productivo del backend como `externalBin`.
- El Scheduled Task reinicia caídas, no un proceso completamente congelado; no hay heartbeat de proceso.
- Si el Scheduled Task no puede registrarse se usa Run key degradada y esa condición no se reporta remotamente a IT.
- El PIN IT por defecto sigue siendo débil hasta que se defina un flujo de provisión seguro.
- Hay cobertura pendiente en varias vistas/hooks React y capas Tauri dependientes de `AppHandle`; `tauri::test::mock_app()` falla en este entorno, por lo que se extraen y prueban funciones puras.
- La preview truncada tiene corrección en runtime; queda añadir el caso negativo explícito según `TODOS.md`.

## Documentación histórica que requiere cuidado

- Migración, traceability y varios ADRs describen fases QML previas. Conservarlos como evidencia de decisión, pero no recrear QML/PySide6 ni rutas `adapters/ui/`.
- El README del crate `watcher_segments` conserva texto de “scaffold”; el código actual y `ENGINE_READY=true` son la referencia de implementación.
- `project/README.md` y `.env.example` son la referencia operativa de directorios/configuración; verificar siempre contra `config.py` al introducir una variable nueva.
