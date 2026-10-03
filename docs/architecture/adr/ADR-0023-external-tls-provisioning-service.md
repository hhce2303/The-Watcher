# ADR-0023 — Aprovisionamiento TLS como servicio externo (`the-watcher-certs`)

- **Estado**: Aceptado (preguntas abiertas resueltas 2026-10-02)
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
   - En el primer arranque tras una instalación, el daemon genera par de claves y CSR localmente,
     con los SAN del endpoint de la estación.
   - Envía `POST /v1/certificates` con CSR + `device_id` + `station_id` + nonce, firmados con la clave
     Ed25519 enrolada del dispositivo (mismo esquema de firma de los heartbeats).
   - El servicio verifica que el dispositivo esté enrolado y ligado a esa estación (consulta a
     Daily/Supabase), firma con la CA local de IT y responde con cadena + CA.
   - **Sin renovación.** Un equipo se formatea cada ~3 meses y la reinstalación vuelve a enrolar y
     emitir, así que el certificado se emite una vez por instalación con una validez larga (objetivo:
     10 años, "permanente" en la práctica; X.509 exige un `notAfter`). No hay lógica de renovación ni
     de reintento periódico en el daemon: solo reintento de la emisión inicial con backoff.
   - El transporte hacia el servicio es HTTPS validado contra la CA local, cuyo ancla de confianza
     viaja en el instalador (`certs/trust/`), no contra el almacén del sistema.
4. **Falla cerrada, nunca degradada**: sin material válido, el listener TLS no arranca. Nunca baja a
   HTTP ni a certificados autofirmados. Si el servicio no responde en la primera emisión, la vista en
   vivo queda desactivada y se reporta en el heartbeat/salud hasta que IT lo recupere.
5. **El daemon no modifica el almacén de confianza en runtime.** La confianza en la CA de los
   navegadores del Supervisor sigue siendo del instalador/gestión de endpoints (contrato de archivos
   `certs/trust/*.pem`), no del daemon.
6. **`the-watcher-certs` pasa a ser un servicio desplegable**, operado solo por IT dentro de la LAN,
   que firma con una **CA local propia** (sin CA pública ni corporativa certificada; consistente con
   ADR-0021). Los scripts mkcert actuales siguen sirviendo como proveedor de pruebas. El contrato
   entre repos es solo este ADR más el contrato de archivos; no hay dependencia de código.
7. **`browser_local` queda fuera del servicio.** Su certificado loopback (`localhost`, un usuario)
   sigue emitiéndose localmente; `TlsMaterialPort` solo cubre `live_view_lan`.

## Consecuencias

- Reinstalar una estación ya no requiere reconstruir el instalador con un certificado por equipo: el
  instalador solo lleva el ancla de confianza y la URL del servicio. No hay clave privada de estación
  en el instalador.
- **Revocación = vida de la instalación.** No hay CRL/OCSP: el certificado es de transporte y la
  autorización real es la assertion de Daily (ADR-0021), así que dar de baja una estación se hace
  deshabilitando su dispositivo en Daily y negándole nueva emisión en el servicio. Un certificado
  extraviado de un equipo dado de baja no da acceso por sí solo. Riesgo residual: con validez de 10
  años, un certificado filtrado seguirá siendo válido para suplantar el *servidor* hasta rotar la CA;
  la rotación de CA es la medida extrema (reemite todas las estaciones al reinstalar/re-enrolar).
- Nuevo punto de disponibilidad solo en el momento de instalar/enrolar: si el servicio cae, las
  estaciones ya enroladas no se ven afectadas.
- Nueva superficie de seguridad: el endpoint de emisión es un firmante de CA. Debe autenticar
  dispositivo y estación, limitar SAN a lo asociado a esa estación, tasa por dispositivo y auditar
  cada emisión (criterio de ADR-0011). La clave de la CA vive solo en el servidor de IT.
- `TlsMaterialPort` obliga a refactorizar `live_view_lan` para no leer rutas de config directamente;
  el modo `file` mantiene la compatibilidad y las pruebas actuales.
- Coste operativo: IT opera el servicio y la CA local. Hasta que exista, el modo `file` es el único
  usable y este ADR no cambia el despliegue actual.

## Opciones no elegidas

- **El servicio entrega el par de claves ya generado**: la clave privada viajaría por red; CSR local
  evita ese riesgo sin coste real.
- **Certificado comodín o compartido para toda la flota**: una estación comprometida expone a todas y
  no permite revocar por estación.
- **Daemon con acceso a la CA**: la clave de CA en cada estación de Operator es inaceptable.
- **Supabase Edge Function como CA**: mezcla el plano de identidad de Daily con firma de CA y
  dificulta auditar y aislar la clave.
- **Mantener el certificado por estación dentro del instalador**: es lo que hay hoy; obliga a
  construir un instalador por equipo en cada reformateo.
- **Certificados de vida corta con renovación automática**: descartado; con reformateos cada ~3
  meses la renovación no aporta y añade un bucle y modos de fallo al daemon.

## Preguntas resueltas (2026-10-02)

1. **CA y operación**: CA local intra-LAN, sin CA certificada ni corporativa; opera solo IT.
2. **Vida del certificado**: permanente en la práctica, sin renovación; un reformateo (~3 meses)
   reinstala y re-emite.
3. **Revocación**: basta la vida de la instalación; ver Consecuencias para el riesgo residual.
4. **`browser_local`**: sigue emitiéndose localmente.

## Pendiente para la fase 2

- Implementación de la CA local (mkcert-compatible, step-ca o propia) y dónde se protege su clave.
- Validez exacta del `notAfter` (10 años es el punto de partida).

## Plan por fases (cada una entregable y reversible)

1. Introducir `TlsMaterialPort` + adaptador `file`; migrar `live_view_lan`/`browser_local`; sin cambio
   de comportamiento.
2. Esbozo del servicio y esquema OpenAPI en `the-watcher-certs`, con la CA de prueba (mkcert).
3. Adaptador `remote` con CSR, emisión única y pruebas de falla cerrada (servicio caído, SAN
   inválido, dispositivo no enrolado).
4. Piloto en una estación; después decidir la implementación de la CA local de IT.
