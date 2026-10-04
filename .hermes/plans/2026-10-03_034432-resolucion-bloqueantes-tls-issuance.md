# Resolución de bloqueantes — emisión TLS de The Watcher

> **Para Hermes:** esto es una propuesta de decisión y ejecución por fases. No autoriza implementación ni publicación de ADR todavía.

**Objetivo:** desbloquear el diseño de `the-watcher-certs` para emitir una sola vez certificados TLS de `live_view_lan`, con control de IT y sin convertir mkcert en un emisor productivo.

**Arquitectura propuesta:** un servicio de enrolamiento propio, pequeño y dentro de la LAN, aplica la política de negocio/seguridad; `step-ca` autoalojado queda aislado como firmante. El daemon crea localmente una clave TLS y CSR; su identidad Ed25519 existente solo autentica la petición. La CA raíz se mantiene offline y la intermedia online en infraestructura de IT.

**Tecnologías:** Python/aiohttp para el broker si se conserva el stack del daemon; `step-ca` como CA; PostgreSQL o la base ya operada por IT para estado de nonces/idempotencia/auditoría; HTTPS con ancla de la CA distribuida por el instalador.

---

## Decisiones propuestas para aprobación

### D1 — Emisor y alcance

**Decisión propuesta:** usar `step-ca` como firmante, detrás de un broker `the-watcher-certs`; conservar mkcert solo para `dev`/fixtures/piloto manual.

**Motivo:** mkcert actual es scripts-only (`the-watcher-certs/README.md:8-16`) y no proporciona endpoint de emisión, autorización por dispositivo, persistencia anti-replay, auditoría ni rate limiting. `step-ca` aporta el ciclo de vida de CA y política X.509; el broker implementa la autorización específica de SIG.

**Alternativa condicionada:** CFSSL detrás del mismo broker únicamente si IT prefiere operar explícitamente más piezas de CA, almacenamiento/auditoría y upgrades a cambio de una huella menor. No escribir un firmante X.509 propio.

**Criterio de aceptación:** el endpoint público nunca recibe una credencial que permita firmar SANs arbitrarios; solo el broker tiene una credencial de provisioner limitada hacia `step-ca`.

### D2 — Protocolo de identidad, integridad y replay

**Decisión propuesta:** el daemon genera un par TLS nuevo (ECDSA P-256, salvo que IT determine otro algoritmo) y un CSR local. La identidad Ed25519 existente firma una representación canónica versionada de:

`version | audience | method | path | device_id | station_id | issued_at | nonce | idempotency_key | sha256(csr_der)`.

Usar el dominio de firma dedicado `the-watcher-tls-issuance:v1:`; no reutilizar los dominios de desafío (`identity.py:16`) ni heartbeat (`identity.py:17`).

**Servidor:** valida ventana corta de `issued_at`, firma, dispositivo↔estación y audience; consume el nonce en la misma transacción que reserva `idempotency_key`. La primera solicitud reserva un registro `pending`; la respuesta posterior de la misma clave devuelve exactamente el mismo resultado/serial, incluso si se perdió la respuesta anterior.

**Criterio de aceptación:** dos POST iguales no producen dos certificados; nonce expirado, ya consumido, firma inválida o CSR con digest distinto fallan cerrados y quedan auditados.

### D3 — Fuente de verdad de enrolamiento

**Decisión propuesta:** Daily/Supabase sigue siendo la fuente de verdad del vínculo `device_id → station_id → SAN permitido`; el broker consulta un endpoint interno de lectura mínimo autenticado por identidad de servicio de IT. No replicar tablas en la primera versión.

**Regla de fallo:** error, timeout o respuesta ambigua de Daily/Supabase bloquea emisión. El broker no acepta un SAN declarado por el CSR como autorización.

**Contrato mínimo para Daily:** `GET /internal/watcher-devices/{device_id}/certificate-policy` devuelve `enabled`, `station_id`, `allowed_dns_sans`, `allowed_ip_sans`, `policy_version`; no expone secretos ni datos no necesarios.

**Criterio de aceptación:** una estación deshabilitada o vinculada a otra estación no puede emitir; una indisponibilidad de Daily no degrada el listener a HTTP.

### D4 — Vida, cadena y revocación

**Decisión propuesta:** para el piloto, leaf de 90 días y renovación explícitamente deshabilitada; medir coste operativo real. Antes de producción, tomar decisión separada sobre 1 año frente a 10 años tras threat-model de pérdida de clave. La raíz offline tendrá 15 años y la intermedia online al menos 5 años; ningún leaf puede expirar después de su issuer.

**Motivo:** el ADR-0023 admite el riesgo residual de una hoja filtrada con vida de 10 años (`ADR-0023:65-70`). El reformateo cada ~3 meses no revoca una clave ya extraída.

**Criterio de aceptación:** documentar el plan de rotación de intermedia/raíz y confirmar que todo leaf encadena contra una CA válida durante su vigencia.

### D5 — Custodia de claves de estación

**Decisión propuesta:** no ampliar el poder de la actual identidad Ed25519 hasta que se proteja mediante DPAPI de usuario o certificado no exportable del Windows Certificate Store. Para el piloto controlado se acepta el archivo actual solo con ACL verificada por el instalador y una alerta de incumplimiento; producción requiere el almacenamiento protegido.

**Motivo:** la identidad actual persiste la PKCS8 sin cifrado (`app/adapters/browser_local/identity.py:64-85`) y `icacls` es best-effort (`identity.py:107-139`). Convertirla en credencial de emisión aumenta el impacto de una exfiltración.

**Criterio de aceptación:** el servicio rechaza una estación cuyo estado de protección no cumpla la política; ninguna clave TLS ni de CA viaja al servidor.

### D6 — Correcciones de contrato y ADR

**Decisión propuesta:** crear ADR-0024 como enmienda de ADR-0023, sin editar el ADR aceptado, que fije D1–D5 y aclare que `TlsMaterialPort` cubre exclusivamente `live_view_lan`. Añadir después el OpenAPI v1 del servicio y el contrato del adaptador remoto.

**Motivo:** el índice exige ADRs nuevos desde 0024 (`docs/architecture/adr/README.md:3-10`); ADR-0023 tiene tensión entre sus puntos 1 y 7 respecto a `browser_local` (`ADR-0023:26-29,57-58`). Además, el daemon no define actualmente `TLS_PROVISIONING_URL` (`app/infrastructure/config.py:199-212`).

**Criterio de aceptación:** ADR-0024, índice ADR, contrato de archivos y OpenAPI no se contradicen; el modo `file` permanece el default compatible.

---

## Orden de ejecución propuesto (tras aprobación)

### Fase A — Cerrar gobierno y contratos

1. Aprobar D1–D6 y registrar ADR-0024 en `the-watcher-daemon/docs/architecture/adr/` e índice.
2. En `the-watcher-certs`, crear `docs/openapi/v1.yaml` para `POST /v1/certificates` y `GET /healthz`; declarar errores: `401 signature`, `403 policy`, `409 nonce/idempotency`, `422 csr/san`, `429 limit`, `503 enrollment/CA`.
3. Acordar con Daily el endpoint interno de política y su SLA/timeout.
4. Definir la tabla transaccional de emisión: `nonce_hash`, expiración, idempotency key, CSR digest, device/station, SANs autorizados, serial, estado, timestamps y motivo de denegación.

### Fase B — Servicio aislado y CA de prueba

1. Crear un worktree gobernado para `the-watcher-certs`.
2. Implementar tests de contrato primero: firma canónica, replay, idempotencia, SAN derivado, dispositivo deshabilitado y outage de Daily.
3. Crear el broker sin acceso público a la clave de CA; integrar un provisioner limitado de `step-ca`.
4. Usar mkcert solo para fixtures de integración local; nunca para el endpoint productivo.
5. Validar que la CA raíz permanece offline y que el material público integra `certs/trust/*.pem` conforme a `docs/architecture/tls-provisioning-contract.md:15-33`.

### Fase C — Adaptador remoto del daemon

1. En un worktree gobernado de `the-watcher-daemon`, añadir configuración explícita para URL, CA trust file, timeout y directorio de material remoto.
2. Añadir el adaptador `remote` detrás de `TlsMaterialPort`, generando clave TLS y CSR localmente, persistiéndolos con permisos restringidos y usando el protocolo D2.
3. Probar fallo cerrado: CA no confiable, servicio down, respuesta/cadena inválida, SAN no permitido y retry que devuelve la misma emisión.
4. Mantener `file` como default y no tocar `browser_local`.

### Fase D — Piloto operacional

1. Piloto con una estación Windows bajo control de IT, leaf 90 días y observabilidad completa.
2. Ensayar pérdida de respuesta, reinicio del daemon, caída de Daily y rotación simulada de intermedia.
3. Revisar métricas/auditoría y decidir vida final del leaf antes del despliegue general.

## Archivos que previsiblemente cambiarán tras aprobación

- Crear en `the-watcher-daemon`: `docs/architecture/adr/ADR-0024-...md`; actualizar `docs/architecture/adr/README.md`, `docs/architecture/tls-provisioning-contract.md`, `app/infrastructure/config.py`, `app/adapters/tls_provisioning/remote_adapter.py`, `tests/test_tls_material.py` y nuevos tests de protocolo.
- Crear en `the-watcher-certs`: `docs/openapi/v1.yaml`, servicio/broker, pruebas de integración, configuración de step-ca y documentación de operación. Los paths concretos se fijarán al inspeccionar el manifiesto del repo antes de implementar.

## Gates de validación

- OpenAPI contract tests y vectores de firma canónica compartidos entre ambos repos.
- Pruebas de replay/idempotencia y SAN authorization con base de datos real de prueba.
- `python -m pytest -q` y `tests/test_import_purity.py` en daemon; no se debilita la pureza de imports.
- `git diff --check`, auditoría de secretos y revisión de la cadena con herramientas X.509.
- Prueba manual Windows: permisos/DPAPI, ancla de confianza, primer arranque, listener TLS y recuperación tras respuesta perdida.

## Riesgos que permanecen abiertos

- La vida definitiva de 10 años no debe aprobarse sin aceptar formalmente el riesgo de suplantación tras exfiltración.
- Debe verificarse que Daily puede ofrecer el endpoint de política sin mezclar la firma de CA con Supabase Edge Functions, coherente con ADR-0023.
- El repositorio `the-watcher-certs` sigue scripts-only (`README.md:8-16`); sus convenciones, manifiesto y CI deben inspeccionarse antes de seleccionar framework o persistencia.
