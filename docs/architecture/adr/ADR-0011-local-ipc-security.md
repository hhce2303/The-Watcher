# ADR-0011 — Canal IPC local autenticado (named pipe/token + audit)

- **Estado**: Aceptado (roadmap)
- **Fecha**: 2026-06-30
- **Origen**: `/plan-eng-review` — hallazgo F4 (regresión de seguridad, confianza 9/10)
- **Docs**: [referencia — contrato IPC](../../migration/reference-target-architecture.md#contrato-ipc--mapeo-bridges-qml--comandoseventos)

## Contexto

Hoy la UI y el core viven en el **mismo proceso** (Qt): comandos sensibles como `stopRecording`,
`unlockIT` y `setRole` (ver
[`app/adapters/ui/settings_bridge.py`](../../../project/app/adapters/ui/settings_bridge.py)) son
**inalcanzables** desde fuera del proceso.

Al separar UI (Tauri) y backend (Python), esos comandos viajan por un canal IPC local. Si ese canal
fuera un **TCP WebSocket abierto en localhost**, cualquier proceso del mismo equipo podría conectarse
y emitir `stopRecording` (hueco de evidencia), forzar `unlockIT` por fuerza bruta, o cambiar el rol.
Agrava: la app **ya abre puertos de firewall** vía `netsh` (`SettingsBridge.openItWsPort`). Para una
herramienta de evidencia, esto es una **regresión de seguridad**.

## Decisión

- El canal IPC local **no** es un TCP WebSocket abierto. Usar **named pipe de Windows** (scoped al
  usuario/sesión) o, si se usa TCP en loopback, un **token burned-in en build-time** que el frontend
  Tauri y el backend comparten. Toda la infra de comandos/eventos viaja por ese canal autenticado.
- **Audit:** `startRecording`/`stopRecording`/`unlockIT`/`setRole` se loguean al event store
  (`adapters/storage`) con **origen y timestamp**.
- **Modelo de amenaza documentado:** el canal local **no es una frontera de seguridad** fuerte; se
  confía en el aislamiento de usuario del SO. El objetivo es cerrar el acceso trivial de cualquier
  proceso, no resistir a un atacante con privilegios del mismo usuario.
- El WS de [`app/adapters/ws/`](../../../project/app/adapters/ws) (IT↔Supervisor, inter-máquina) es **otro**
  canal, con su propia superficie; este ADR no lo cubre.
- Prototipo del rechazo (un cliente sin token no ejecuta `stopRecording`) es un criterio del
  [gate F0](../../migration/howto-f0-gate.md).

## Consecuencias

- ✅ Cierra el acceso trivial de procesos locales a comandos sensibles; deja rastro auditable de su
  uso (mejora respecto a hoy, donde solo se loguea a Loguru).
- ✅ Named pipe evita depender de un puerto TCP (sin binding conflictivo, sin firewall extra).
- ➖ Complejidad nueva: gestión del token/pipe en build y arranque; el frontend debe autenticar antes
  de operar.
- ➖ No protege contra un atacante con privilegios del mismo usuario (documentado como límite del
  modelo). Complementa, no reemplaza, el gate IT-PIN existente.
- Relacionado con los TODOs de auditoría de unlocks/roles en `TODOS.md`.

## Evidencia externa (investigación 2026-07)

(detalle + fuentes en [tech-debt-and-best-practices](../../migration/tech-debt-and-best-practices.md), TD-2)
- El ejemplo de referencia más citado (dieharders/example-tauri-v2-python-server-sidecar) hace
  exactamente lo que este ADR prohíbe: **FastAPI en `localhost:8008` (TCP loopback abierto) con acceso
  solo por CORS, sin token/JWT** → confirma la regresión que justifica named pipe/token.
- El modelo **capabilities** de Tauri v2 es **default-deny a remoto** (permisos por ventana/webview) y
  el **updater** exige firma minisign — ambos juegan a favor de la postura de este ADR.
