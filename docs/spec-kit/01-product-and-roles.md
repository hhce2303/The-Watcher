# 01 — Producto, actores y reglas de rol

## Objetivo de producto

Mantener una grabación continua y recuperable de las pantallas de una estación Windows. A partir del buffer se crean clips de evento con contexto antes/después, clips periódicos por monitor y una composición de varios monitores. El producto también permite revisión, edición de un reel, solicitudes Supervisor–IT, entrega por OneDrive y analítica de detecciones.

## Roles

La configuración por máquina vive en `%LOCALAPPDATA%\The Watcher\user_config.json`; no se selecciona en `.env`. Un equipo sin rol queda inerte y muestra el asistente de primer uso.

| Rol | Graba | Inicio de grabación | Superficie principal | Regla operativa |
|---|---:|---|---|---|
| `operator` | Sí | Forzado | Grabación | Ventana no se cierra: se oculta al tray. Scheduled Task intenta relanzar el daemon. Sin ajustes ni clips. |
| `it` | Sí | Opt-in (`autorecord`) | Dashboard/editor IT | Administración, clips, editor, solicitudes entrantes y cambio de rol autorizado. |
| `supervisor` | No | Nunca | Shell de clips/solicitudes | Consulta material y solicita clips a IT; no se construye stack de capturadores. |
| `""` | No | Nunca | Wizard | Estado seguro de primer arranque; puede seleccionar rol. |

La fuente de verdad de capacidades es `project/app/core/policy.py`, no condicionales duplicados de UI. `role.py` aplica esas capacidades durante el arranque. Un cambio de rol implica relanzar la aplicación.

## Autorización y límites

- El PIN de IT protege el desbloqueo y cambio de rol donde corresponde; cada intento de `unlock_it` y `set_role` queda auditado por `AuditPort`.
- El valor predeterminado `IT_PIN=1234` sigue existiendo con advertencia visible al arrancar. No debe tratarse como una configuración de producción segura.
- El pipe IPC limita acceso al SID del usuario actual y `SYSTEM`; es una barrera local de usuario, no autenticación de red fuerte.
- La futura función `LiveViewPort` está bloqueada por una política pendiente sobre qué Supervisor puede ver a qué Operator. No habilitarla sin esa decisión explícita.

## Resultados que el usuario espera

1. Un Operator conserva el buffer aunque cierre la ventana Tauri.
2. Un evento manual o automático genera un clip de evidencia tras capturar el post-roll.
3. Cada monitor genera clips raw periódicos; una composición combina los monitores para revisión.
4. Un clip no reproducible en WebView2 por HEVC se puede transcodificar bajo demanda a H.264.
5. La edición y exportación sucede del lado backend; la posición de `<video>.currentTime` no es precisión de frame.

