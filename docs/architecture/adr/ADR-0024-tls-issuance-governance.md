# ADR-0024 — Gobernanza de emisión TLS: step-ca tras broker, claves separadas, nonce duradero y piloto de 90 días

- **Estado**: Aceptado (enmienda [ADR-0023](ADR-0023-external-tls-provisioning-service.md): fija CA, claves, nonce,
  autoridad de política y vida del certificado para el piloto)
- **Fecha**: 2026-10-03
- **Requisitos**: NFR-Seg-4, NFR-Seg-5
- **Relacionado**: [ADR-0023](ADR-0023-external-tls-provisioning-service.md) (protocolo CSR, `TlsMaterialPort`,
  fail-closed, exclusión de `browser_local` — no reabiertos aquí), [ADR-0021](ADR-0021-supervision-lan-live-view.md);
  esquema de payloads en [`../tls-provisioning-contract.md`](../tls-provisioning-contract.md)

## Contexto

ADR-0023 dejó pendientes explícitos para la fase 2 ("Pendiente para la fase 2"): la implementación concreta de la
CA local ("mkcert-compatible, step-ca o propia") y el `notAfter` exacto ("10 años es el punto de partida"). Antes
de entrar en el piloto de una estación (ADR-0023, plan por fases, punto 4) quedan además tres vacíos en lo ya
decidido:

- ADR-0023 (punto 3) firma `POST /v1/certificates` con la **misma** clave Ed25519 enrolada que firma los
  heartbeats (`adapters/browser_local/identity.py`). Una sola clave para dos roles —identidad de salud ante Daily
  y autenticación de emisión de certificados— acopla su blast radius: filtrar una compromete la otra.
- ADR-0023 dice que el servicio "verifica que el dispositivo esté enrolado y ligado a esa estación (consulta a
  Daily/Supabase)" sin fijar qué pasa si esa consulta falla, da timeout o responde de forma ambigua. Sin esa regla
  explícita, un fallback implícito a "permitir" expondría emisión sin autorización verificada.
- ADR-0023 exige que la emisión sea de una sola vez, con reintento solo de la petición inicial, pero no exige que
  el nonce de esa petición sea de un solo uso de forma **duradera**. Un broker con nonces solo en memoria trata un
  reinicio (despliegue, crash) como si reabriera la ventana de repetición, y un reintento de red podría leerse
  como una petición nueva en vez de devolver el material ya emitido.
- El objetivo de "10 años, permanente en la práctica" (ADR-0023, Preguntas resueltas #2) es razonable para
  operación estable, pero convierte cualquier defecto de autorización no detectado durante el piloto —primera vez
  que step-ca y el broker ven tráfico real— en un certificado irrevocable por una década, sin CRL/OCSP (ADR-0023,
  Consecuencias).

## Decisión

Este ADR no reabre el protocolo CSR, `TlsMaterialPort`, el fail-closed del listener ni la exclusión de
`browser_local` (ADR-0023, puntos 1–5, 7): fija los pendientes de fase 2 y corrige dos parámetros para el piloto.

1. **CA: step-ca detrás de un broker, nunca expuesto directamente a una estación.** `the-watcher-certs` pasa a
   tener dos componentes: un **broker** HTTP que atiende `POST /v1/certificates` y `GET /healthz` desde los
   daemons, y **step-ca** como firmante, alcanzable solo por el broker, en una red interna que el daemon no puede
   enrutar. El broker hace toda la validación de negocio —firma de la petición, enrolamiento, ligado a estación,
   nonce, idempotencia— antes de pedirle a step-ca que firme; step-ca nunca recibe una petición directamente de
   una estación Operator. Resuelve el pendiente de ADR-0023 ("CA local: mkcert-compatible, step-ca o propia").
2. **Clave TLS separada de la identidad Ed25519 existente.** El par de claves del CSR (TLS, generado localmente)
   es distinto de la clave Ed25519 enrolada: nunca se deriva ni se reutiliza una Ed25519 como clave TLS ni
   viceversa. Durante el piloto se reutiliza la identidad Ed25519 ya enrolada para autenticar
   `POST /v1/certificates`, con el dominio de firma exclusivo `the-watcher-tls-issuance:v1:` y una carga canónica
   versionada; una firma de emisión no es válida como challenge ni heartbeat. Antes de producción general, la
   custodia de esa clave se endurece con DPAPI o una clave no exportable de Windows, porque la persistencia PEM
   actual tiene ACL best-effort.
3. **Nonce duradero con idempotencia, no solo de un solo uso en memoria.** El broker persiste cada nonce aceptado
   (`device_id`, `nonce`, hash del CSR, resultado) en almacenamiento durable *antes* de pedir la firma a step-ca,
   con clave de idempotencia = `(device_id, nonce)`:
   - Una petición repetida con el mismo `(device_id, nonce)` y el mismo CSR devuelve la **misma** respuesta ya
     emitida (`status: "replayed"`, mismo cuerpo de certificado, mismo código HTTP), sin volver a firmar ni
     consultar a Daily. Cubre el caso de ADR-0023 "solo reintento de la emisión inicial con backoff" sin riesgo de
     doble emisión.
   - Un nonce ya usado con un CSR **distinto** es un intento de repetición o manipulación: `409 Conflict`, nunca
     reemisión.
   - El almacenamiento de nonces sobrevive un reinicio del broker: no es un cache en memoria. Un reinicio del
     servicio no reabre la ventana de repetición.
4. **Daily es la única autoridad de política; su indisponibilidad o ambigüedad es fallo cerrado.** El broker no
   emite ningún certificado sin una respuesta explícita y positiva de Daily/Supabase confirmando que `device_id`
   está enrolado y ligado a `station_id`. Si esa consulta falla, da timeout, o responde de forma ambigua, el
   broker devuelve `503` y **no** firma — nunca interpreta "no se pudo verificar" como "está autorizado". Esto
   hace explícito lo que ADR-0023 dejó implícito en "el servicio verifica... (consulta a Daily/Supabase)".
5. **Vida del certificado para el piloto: 90 días, no el objetivo de 10 años de ADR-0023.** Mientras dure el
   piloto (ADR-0023, plan por fases, punto 4), step-ca emite con `notAfter` = 90 días desde la emisión, alineado
   con el ciclo de reformateo (~3 meses) que ya motivaba "sin renovación" en ADR-0023. Un certificado de piloto
   con un defecto de autorización no detectado queda acotado a, como máximo, un ciclo de reformateo en vez de una
   década. Este ADR no fija la vida definitiva post-piloto — sigue abierto si el día 90 sin reformateo implica
   reinstalar, renovar, o ampliar el plazo — y se revisita con evidencia del piloto.
6. **`TlsMaterialPort` sigue cubriendo exclusivamente `live_view_lan`.** Se reafirma el punto 7 de ADR-0023:
   `browser_local` no pasa por el broker, step-ca ni `TlsMaterialPort`; su certificado loopback sigue
   emitiéndose localmente, sin cambios por este ADR.

## Consecuencias

- `the-watcher-certs` pasa de "un servicio" a dos procesos con una frontera de red real entre ellos: el broker
  expuesto en la LAN de estaciones, step-ca accesible solo desde el broker. El piloto exige desplegar y segmentar
  ambos, no solo levantar step-ca.
- El primer arranque genera un par TLS adicional para el CSR. La identidad Ed25519 enrolada permanece separada
  criptográficamente por dominio de firma; su custodia debe endurecerse antes de producción general.
- El broker necesita almacenamiento durable propio (no solo delegar en step-ca) para nonces/idempotencia: es
  estado nuevo que IT debe respaldar y operar, y que debe sobrevivir reinicios del broker.
- Una consulta a Daily caída bloquea emisión nueva (no renovación, por ADR-0023 punto 3) pero no afecta estaciones
  ya emitidas: mismo perfil de disponibilidad que ADR-0023, ahora explícito también para el fallo de la consulta
  de política, no solo para la caída del servicio completo.
- Con vida de 90 días, una estación que no se reformatea en ese plazo necesita una vía de reemisión antes de
  escalar el piloto a producción general; queda pendiente definir esa vía.
- El contrato de payloads (`tls-provisioning-contract.md`) se vuelve normativo para `POST /v1/certificates` y
  `GET /healthz`: el broker y el daemon dependen de ese esquema exacto, no solo de la descripción en prosa de
  ADR-0023.

## Opciones no elegidas

- **Exponer step-ca directamente al daemon, sin broker**: step-ca no sabe de Daily, estaciones ni nonce duradero;
  habría que meter esa lógica dentro de step-ca (plugins) o aceptar que cualquier CSR con firma Ed25519 válida
  llegue directo al firmante. El broker como frontera deja a step-ca como firmante puro, auditable por separado.
- **Usar la Ed25519 como clave TLS del CSR**: se descarta porque la clave privada TLS debe permanecer asociada a un
  certificado de servidor y el CSR exige un par de claves TLS distinto; la Ed25519 solo autentica la solicitud.
- **Nonce de un solo uso solo en memoria del broker**: más simple, pero un reinicio del broker reabre la ventana
  de repetición justo cuando el servicio es menos confiable; no cumple la durabilidad exigida por este ADR.
- **Mantener el objetivo de 10 años también para el piloto**: descartado para la fase de piloto por el riesgo de
  irrevocabilidad ya señalado en ADR-0023 (Consecuencias, "un certificado filtrado seguirá siendo válido... hasta
  rotar la CA"); 90 días acota ese riesgo mientras se valida el diseño.
- **Vida de certificado igual a cero (emisión manual caso por caso)**: niega el objetivo de ADR-0023 de no
  reconstruir el instalador por estación; no se considera.
- **Permitir emisión cuando Daily no responde, marcando el certificado para revisión posterior**: un certificado
  ya emitido es material de confianza en uso inmediato; no hay forma de "revisar después" sin revocación
  (ADR-0023 no tiene CRL/OCSP), así que un permiso condicional equivale a un permiso.

## Pendiente para después del piloto

- Vía de reemisión si una estación supera 90 días sin reformateo (reinstalar vs. renovar).
- Vida definitiva del certificado una vez el piloto valide broker + step-ca + nonce duradero.
- Segmentación de red exacta entre broker y step-ca (firewall, red separada, mTLS interno).
