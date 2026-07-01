# ADR-0010 — Topología de proceso condicional por rol (daemon vs sidecar)

- **Estado**: Aceptado (roadmap)
- **Fecha**: 2026-06-30
- **Origen**: `/plan-eng-review` — matiz del owner sobre el always-on por rol
- **Docs**: [explicación](../../migration/explanation-tauri-migration.md) · [referencia](../../migration/reference-target-architecture.md)

## Contexto

El comportamiento **always-on** es **exclusivo del rol Operador** (memoria de proyecto: la grabación
nunca depende de que el usuario la inicie). IT y Supervisor usan la app de forma interactiva (revisar
clips, editar reel, requests) y **no** graban en continuo.

Al partir el proceso único actual (UI + core en el mismo proceso Python/Qt) en "UI Tauri + backend",
aparecen dos fallos si la topología es global:
- **Un daemon Python global** → en IT/Supervisor queda consumiendo recursos sin que nadie se conecte.
- **Backend como sidecar de Tauri para todos** → para Operador la grabación quedaría dependiendo de
  que la UI/Watcher esté viva, rompiendo el always-on.

## Decisión

Un único entrypoint Python que arranca en **dos modos según rol**, ambos hablando el **mismo contrato
IPC**; la diferencia es solo *quién lanza a quién* y el ciclo de vida:

| Rol | Modo | Lanzado por | Ciclo de vida | UI Tauri |
|-----|------|-------------|---------------|----------|
| **Operador** | `--daemon` (desacoplado) | scheduled-task watchdog (ya existe) | Independiente; sobrevive el cierre/cuelgue de la ventana | Ventana cliente *opcional/mínima* |
| **IT / Supervisor** | sidecar (`externalBin`) | el proceso Tauri | Vive y muere con la app; sin huérfanos | UI completa |

- El **single-instance**, **tray** y **autostart** del Operador los gobierna el daemon/watchdog, no la
  UI. El detect de rol al arrancar reusa `enforce_role`/`_peek_role` de
  [`app/core/role.py`](../../../app/core/role.py) y [`app/main.py`](../../../app/main.py).
- Cerrar la app IT/Supervisor → el sidecar termina limpio.

## Consecuencias

- ✅ La grabación del Operador **ya no depende de la UI** — cerrar la ventana no la detiene (mejora
  respecto a hoy, donde el bloqueo de ventana fullscreen era crítico).
- ✅ Sin daemon huérfano en IT/Supervisor: el backend vive lo que dura la sesión de trabajo.
- ➖ **Tray del daemon:** un daemon Python headless no tiene event loop Qt, así que `QSystemTrayIcon`
  no sirve → el tray del Operador se implementa con un plugin Rust/Tauri o `pystray`. No es trivial.
- ➖ Edge cases del ciclo de vida a testear en F1: detección de crash del daemon, respawn-loop si el
  canal IPC no bindea, zombie del sidecar si WebView2 crashea (Windows no mata al hijo
  automáticamente), y rol ambiguo al arrancar (fallar fuerte, no adivinar).
- Depende del scheduled-task watchdog ([`app/infrastructure/scheduled_task.py`](../../../app/infrastructure/scheduled_task.py)).

## Evidencia externa (investigación 2026-07)

- **Gotcha del sidecar (TD-3):** `process.kill()` **no** basta para un sidecar PyInstaller one-file
  (Tauri solo conoce el PID del bootloader) → shutdown por **stdin/stdout** al cerrar, para evitar
  zombies/puerto colgado. Reforzar en los tests de ciclo de vida daemon/sidecar. Ver
  [tech-debt-and-best-practices](../../migration/tech-debt-and-best-practices.md).
