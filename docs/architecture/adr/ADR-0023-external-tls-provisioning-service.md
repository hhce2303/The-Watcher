# ADR-0023 — Aprovisionamiento TLS como servicio externo (`the-watcher-certs`)

- **Estado**: Propuesto
- **Fecha**: 2026-09-30
- **Requisitos**: NFR-Seg-4, NFR-Seg-5
- **Relacionado**: [ADR-0020](ADR-0020-browser-local-daily-channel.md), [ADR-0021](ADR-0021-supervision-lan-live-view.md), [ADR-0011](ADR-0011-local-ipc-security.md); contrato de archivos en [`../tls-provisioning-contract.md`](../tls-provisioning-contract.md)

## Contexto

`live_view_lan` (ADR-0021) exige TLS con la CA interna, y `browser_local` (ADR-0020) un
certificado loopback. Hoy el material lo produce a mano `the-watcher-certs`
(`New-OperatorTestDeployment.ps1`, mkcert) *antes* de construir el instalador, y el daemon solo lee
`*_FILE` del `.env` (`app/infrastructure/config.py`). Consecuencias:

- El certificado de una estación va **dentro del instalador**: rotarlo o revocarlo implica
  reconstruir y reinstalar. Con el certificado caducado el listener falla cerrado y el Supervisor
  pierde la vista hasta que alguien intervenga.
- The Watcher ya no contiene tooling de certificados (extraído a `the-watcher-certs`), pero sigue
  acoplado a *cuándo* se emite el material: solo en tiempo de build.
- El daemon ya tiene una identidad Ed25519 enrolada por dispositivo
  (`adapters/browser_local/identity.py`) con la que firma heartbeats hacia Daily. Es el ancla natural
  para autenticar una petición de certificado.

## Decisión

1. **Nuevo puerto `TlsMaterialPort`** en `core/ports/`, con `ensure() -> TlsMaterial(cert_file,
   key_file, ca_files, not_after)` y `renew_if_due()`. `live_view_lan` y `browser_local` piden el
   material al puerto en vez de leer `config.*_cert_file` directamente. `core/` sigue sin conocer
   HTTP, archivos ni CAs.
2. **Dos adaptadores intercambiables**, elegidos por `TLS_PROVISIONING_MODE`:
   - `file` (por defecto): comportamiento actual, lee los `*_FILE` del `.env`. Cero cambios para
     instalaciones existentes y para desarrollo.
   - `remote`: enrola contra el servicio `the-watcher-certs` en `TLS_PROVISIONING_URL`.
3. **Protocolo `remote` (CSR, la clave privada nunca sale de la estación)**:
   - El daemon genera par de claves y CSR localmente, con los SAN del endpoint de la estación.
   - Envía `POST /v1/certificates` con CSR + `device_id` + `station_id` + nonce, firmados con la clave
     Ed25519 enrolada del dispositivo (mismo esquema de firma de los heartbeats).
   - El servicio verifica que el dispositivo esté enrolado y ligado a esa estación (consulta a
     Daily/Supabase), firma con la CA interna y responde con cadena + CAs de confianza.
   - Certificados de vida corta (objetivo: 30 días); renovación al consumir 2/3 de la vida, con
     reintento y backoff. El transporte hacia el servicio es HTTPS validado contra un ancla de
     confianza que viaja en el instalador (`certs/trust/`), no contra el almacén del sistema.
4. **Falla cerrada, nunca degradada**: sin material válido, el listener TLS no arranca. Nunca baja a
   HTTP ni a certificados autofirmados. Un certificado vigente sigue sirviendo mientras la renovación
   falla; solo al vencer se desactiva la vista en vivo y se emite un evento de salud/heartbeat.
5. **El daemon no modifica el almacén de confianza en runtime.** La confianza en la CA de los
   navegadores del Supervisor sigue siendo del instalador/gestión de endpoints (contrato de archivos
   `certs/trust/*.pem`), no del daemon.
6. **`the-watcher-certs` pasa a ser un servicio desplegable** además de contener los scripts. Los
   scripts mkcert quedan como *proveedor de pruebas* (CA de prueba); producción usa la CA
   corporativa detrás del servicio. El contrato entre repos es solo este ADR más el contrato de
   archivos; no hay dependencia de código en ningún sentido.

## Consecuencias

- Rotación y revocación dejan de requerir reinstalar; el instalador ya no embebe la clave privada de
  la estación cuando se usa `remote` (solo el ancla de confianza).
- Nuevo punto de disponibilidad: si el servicio cae, las estaciones siguen con su certificado vigente
  hasta `not_after`; el margen 1/3 de vida es el presupuesto de indisponibilidad tolerada.
- Nueva superficie de seguridad: el endpoint de emisión es un firmante de CA. Debe autenticar
  dispositivo y estación, limitar SAN a lo asociado a esa estación, tasa por dispositivo y auditar
  cada emisión (mismo criterio de auditoría que ADR-0011).
- `TlsMaterialPort` obliga a refactorizar `live_view_lan` y `browser_local` para no leer rutas de
  config directamente; el modo `file` mantiene la compatibilidad y las pruebas actuales.
- Coste operativo: alguien opera el servicio y la CA. Hasta que exista, el modo `file` es el único
  usable y este ADR no cambia el despliegue actual.

## Opciones no elegidas

- **El servicio entrega el par de claves ya generado**: la clave privada viajaría por red; CSR local
  evita ese riesgo sin coste real.
- **Certificado comodín o compartido para toda la flota**: una estación comprometida expone a todas y
  no permite revocar por estación.
- **Daemon con acceso a la CA**: la clave de CA en cada estación de Operator es inaceptable.
- **Supabase Edge Function como CA**: mezcla el plano de identidad de Daily con firma de CA y
  dificulta auditar y aislar la clave.
- **Mantener el certificado solo en el instalador**: es lo que hay hoy; no resuelve rotación ni
  revocación.

## Preguntas abiertas (bloquean pasar de Propuesto a Aceptado)

1. ¿Qué CA corporativa firma en producción (ADCS, step-ca u otra) y quién opera el servicio?
2. ¿Vida del certificado y ventana de renovación definitivas? (30 d / 2/3 es un punto de partida.)
3. ¿Cómo se revoca? ¿Vida corta basta o hace falta CRL/OCSP para los navegadores del Supervisor?
4. ¿`browser_local` (loopback) entra en el mismo servicio o conserva su emisión local? Su certificado
   es de otra naturaleza (`localhost`, un solo usuario).

## Plan por fases (cada una entregable y reversible)

1. Introducir `TlsMaterialPort` + adaptador `file`; migrar `live_view_lan`/`browser_local`; sin cambio
   de comportamiento.
2. Esbozo del servicio y esquema OpenAPI en `the-watcher-certs`, con la CA de prueba (mkcert).
3. Adaptador `remote` con CSR, renovación y pruebas de falla cerrada (vencido, servicio caído, SAN
   inválido).
4. Piloto en una estación; después decidir sobre la CA de producción.
