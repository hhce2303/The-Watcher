# Instalación simple del daemon con certificados — Plan

> **Para Hermes:** plan de implementación únicamente. No autoriza cambios, despliegues, acceso a secretos, creación de CA, firma de binarios ni publicación.

**Objetivo:** una persona Operator sin conocimientos de sistemas instala The Watcher en Windows mediante un único instalador; la emisión de TLS sucede automáticamente en el primer arranque y cualquier bloqueo se presenta como una instrucción breve para contactar a IT, sin rutas para eludir las verificaciones de seguridad.

**Arquitectura:** separar el flujo en dos roles. IT prepara, opera y monitorea el broker/step-ca, la política Daily y el paquete firmado; el Operator únicamente ejecuta el instalador distribuido por IT. El daemon genera CSR y solicita emisión en background mediante el adaptador remoto, con fallo cerrado; no se entregan llaves de estación ni CA privada al usuario.

**Tecnologías establecidas:** Inno Setup/PowerShell/PyInstaller para la instalación Windows (`installer/`), daemon Python con `TlsMaterialPort`, broker Python mínimo en `the-watcher-certs`, protocolo HTTP v1 con Ed25519 y CSR, trust anchor PEM distribuida por el instalador.

---

## Resultado de los agentes

| Agente | Estado | Aporte incorporado |
|---|---|---|
| `@investigator` | completó | Instalador de doble clic + emisión silenciosa en primer arranque; no debe existir botón Operator para aprobar/reintentar enrolamiento. Detectó que el broker real, observabilidad de estado y recuperación todavía no existen. |
| `@devops` | incompleto: límite de sesión 429 | Alcanzó a inspeccionar el flujo, pero no devolvió plan. Este documento usa solo evidencia de repositorio y marca sus decisiones operativas como gates. |
| `@backendengineer` | incompleto: límite de sesión 429 | No devolvió informe. Sus decisiones de producto se mantienen como fases de diseño y TDD, no como hechos confirmados por el agente. |

## Evidencia y restricciones

- El instalador ya ofrece un flujo de doble clic mediante `Setup.bat`/`install.ps1`; Inno Setup instala el daemon y FFmpeg va embebido: `the-watcher-daemon/installer/build.ps1:259-370`, `installer/The Watcher.iss:81-120`.
- El build actual todavía puede incrustar bundle de certificados generado antes de empaquetar: `installer/build.ps1:202-239`. Esto debe conservarse como modo `file` de contingencia, no como experiencia objetivo del Operator remoto.
- El daemon ya cuenta con modo `remote`, URL, CA pinneada, timeout y directorio de material: `app/infrastructure/config.py:199-224`; el contrato exige CSR local y fallo cerrado: `docs/architecture/adr/ADR-0023-external-tls-provisioning-service.md:34-49`.
- El broker de `the-watcher-certs` es una fundación con fakes/in-memory, sin signer ni lookup de enrolamiento reales: `the-watcher-certs/README.md:10-16,34-46`.
- Actualizaciones preservan `.env` y `certs/`: `installer/Update-Watcher.ps1:3-12,56-85`.
- La CA privada nunca se entrega en repo/instalador: `docs/architecture/tls-provisioning-contract.md:32-33`.

## Experiencia objetivo

### Operator (una única interacción)

1. IT entrega un único archivo firmado `Setup-The Watcher.exe` por canal corporativo.
2. Operator hace doble clic, acepta el diálogo estándar de Windows y espera “Instalación completada”.
3. El daemon se inicia automáticamente y en segundo plano solicita su certificado TLS a `the-watcher-certs`.
4. La interfaz visible no pide URL, estación, certificado, CA, token ni decisiones de seguridad. Muestra una sola tarjeta/tray notification:
   - **Listo:** “The Watcher está activo. Vista supervisada disponible.”
   - **Grabación activa, vista pendiente:** “The Watcher está activo; la vista supervisada aún no está disponible. Contacta a IT con el código <request-id>.”
5. Un reinicio del daemon vuelve a usar el idempotency key/material existente; no solicita al Operator que repita el enrolamiento.

### IT (preparación separada)

1. Opera broker y step-ca en red IT; solo el broker recibe tráfico de Operator.
2. Publica el endpoint de política Daily que decide `device_id → station_id → SAN`, con timeout y fallo cerrado.
3. Prepara un perfil no secreto para la estación: `TLS_PROVISIONING_MODE=remote`, URL del broker, CA pública pinneada y station ID. El instalador incorpora solamente ese perfil y la CA pública.
4. Firma el instalador y distribuye el artefacto por un canal corporativo autenticado.
5. Observa emisión, errores y salud; IT, no el Operator, resuelve bloqueo de enrolamiento.

## Plan por fases

### Fase 0 — Decisiones y definición de done

**Objetivo:** cerrar los gates que impiden prometer instalación “un clic”.

- Decidir ownership de Daily policy API, broker/step-ca, certificados de firma de Windows y soporte de primer nivel.
- Definir el código de correlación no secreto que aparece al Operator y su enlace a logs/auditoría IT.
- Confirmar qué cuenta instala y ejecuta el daemon, y qué almacén de confianza se usa por usuario/máquina.
- Definir la política al expirar el piloto de 90 días (renovación gobernada o reinstalación); hoy es una decisión abierta.

**Gate:** no pasar a piloto sin owner nombrado para broker, Daily policy, firma de instalador y soporte IT.

### Fase 1 — Broker operable por IT (sin tocar UX del Operator)

**Objetivo:** convertir los fakes actuales en servicio operable, sin exponer CA al cliente.

- Reemplazar signer fake por integración step-ca delimitada al broker.
- Reemplazar enrollment fake por cliente Daily policy con autenticación de servicio, timeout y `503` fail-closed.
- Persistir nonce/idempotencia/auditoría en almacenamiento durable; registrar solo metadata segura (device/station, SAN, serial, request id, motivo), nunca claves/CSR completo en logs por defecto.
- Exponer health/readiness solo para IT, separando liveness de autorización.
- Añadir runbook IT: backup/rotación de CA, recuperación del broker, consulta de request-id y rollback a modo `file` para contingencia.

**Archivos/sistemas probables:** `the-watcher-certs/enrollment_broker/`, configuración de step-ca fuera de git, nueva documentación/runbook, proveedor Daily.

**Validación:** pruebas de integración con step-ca de prueba, outage Daily, nonce/retry tras reinicio, SAN no autorizado, dispositivo deshabilitado y verificación de que la clave TLS nunca abandona la estación.

### Fase 2 — Perfil remoto autocontenible para instalador

**Objetivo:** un artefacto de instalación contiene toda configuración pública necesaria, nunca material secreto por estación.

- Definir `operator-remote-deployment.env` con URL, station id y paths relativos para CA pública.
- Extender el build para validar el perfil remoto como ya valida los bundles `file`; rechazar URL vacía, CA faltante y placeholders.
- Incluir la CA pública de broker bajo `certs/trust/` y el perfil en el instalador; no incluir leaf/key de estación en modo remote.
- Mantener `TLS_PROVISIONING_MODE=file` como rollback explícito solo para IT/pilotos, no como fallback automático.

**Archivos probables:** `the-watcher-daemon/installer/build.ps1`, `installer/The Watcher.iss`, `installer/Update-Watcher.ps1`, `the-watcher-certs/templates/` y `.env.example`.

**Validación:** build reproducible del instalador remote; inspección de artefacto que confirma ausencia de claves/leaf; primera instalación en Windows limpia; actualización preservando material remoto ya emitido.

### Fase 3 — Estado comprensible para Operator

**Objetivo:** ninguna persona no técnica busca certificados, `.env` o logs para saber qué hacer.

- Crear un único estado `TLS_ENROLLMENT`: `not_started`, `issuing`, `ready`, `blocked_by_it`, `temporary_failure`.
- Adaptar `RemoteTlsMaterialAdapter`/composition root para emitir resultado estructurado sin impedir grabación cuando falle TLS; el listener LAN permanece fail-closed.
- Añadir tray notification o pantalla de estado mínima con texto fijo y request-id. No incluir “reintentar aprobando” ni credenciales.
- Incluir enlace/instrucción de soporte: “Contacta a IT y proporciona código X”.
- Health/heartbeat debe enviar estado seguro para que IT vea la estación bloqueada sin leer los archivos privados.

**Archivos probables:** `app/adapters/tls_provisioning/remote_adapter.py`, `app/daemon_root.py`, `app/adapters/live_view_lan/server.py`, puerto/DTO de estado si la arquitectura lo requiere, tests de health/heartbeat.

**Validación:** emisión exitosa, broker caído, política Daily denegada, CA pinneada incorrecta, respuesta inválida y restart tras respuesta perdida. En todos: grabación continúa; TLS no baja a HTTP; Operator recibe un mensaje accionable sin detalle sensible.

### Fase 4 — Empaquetado one-click y soporte

**Objetivo:** el único manual del Operator cabe en una tarjeta de una página.

- Generar únicamente el instalador firmado Inno Setup como artefacto soportado; ZIP/PowerShell se etiquetan “IT/diagnóstico”, no para Operator.
- Verificar firma, versión y hash antes de distribución; documentar la cadena de distribución corporativa.
- Instalar/actualizar sin pedir rutas ni certificados. Reintentos de actualización no destruyen `.env`/material emitido.
- Publicar guía Operator: doble clic, esperar, interpretar los dos estados, cómo contactar soporte. Publicar runbook IT separado.

**Validación:** prueba de usabilidad observada con alguien no técnico: desde archivo entregado a daemon grabando y estado TLS visible sin abrir PowerShell; éxito sin intervención IT durante el flujo del usuario.

## Pruebas y gates obligatorios

- TDD para todo cambio de comportamiento; test RED→GREEN por state transition y errores.
- `python -m pytest -q`, incluido `tests/test_import_purity.py`, en daemon.
- `python3 -m unittest discover -s tests -t .` y tests de integración delimitados en certs.
- `git diff --check`; inspección del artefacto para ausencia de claves/CA privada.
- Piloto Windows administrado por IT: primera instalación, actualización, corte del broker, corte Daily, rechazo SAN, expiración y recuperación.
- No declarar “one-click” hasta pasar una prueba de usuario no técnico y obtener aprobación de soporte/IT.

## Riesgos y no-goals

- No hay atajo seguro para que el Operator autorice su propio certificado; la política debe seguir en Daily/IT.
- Un certificado piloto de 90 días sin flujo posterior puede convertir “simple” en incidente recurrente; resolver antes de escala.
- No automatizar instalación de CA privada, generación manual de certs ni modificación de firewall por el Operator.
- No usar el health endpoint como prueba de autorización.

## Handoff de implementación tras aprobación

1. `@governor`: crear worktrees separados para daemon y certs, con plan de revertir a modo `file` bajo control IT.
2. `@backendengineer`: Fase 1 broker real y Fase 3 state machine/diagnóstico, por TDD y contrato versionado.
3. `@devops`: Fase 2/4, build remoto, firma/distribución, runbooks y piloto Windows; no tocar infraestructura/secretos sin aprobación explícita.
4. `@document-generator`: guía Operator (how-to), runbook IT (how-to), referencia de perfil remoto/OpenAPI y actualización de ADR/contratos si cambian decisiones.
