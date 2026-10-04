# ADR-0025 — CA de piloto persistente, con restricción de nombres, en un secreto de GitHub

- **Estado**: Aceptado (piloto `file`; se retira cuando entre en servicio el modo `remote` de
  [ADR-0023](ADR-0023-external-tls-provisioning-service.md)/[ADR-0024](ADR-0024-tls-issuance-governance.md))
- **Fecha**: 2026-10-04
- **Requisitos**: NFR-Seg-4, NFR-Seg-5
- **Relacionado**: [ADR-0021](ADR-0021-supervision-lan-live-view.md),
  [ADR-0023](ADR-0023-external-tls-provisioning-service.md), [ADR-0024](ADR-0024-tls-issuance-governance.md)

## Requisitos

- Un supervisor importa la CA pública **una sola vez**, no una por instalador.
- Reconstruir o reinstalar una estación no invalida la confianza de las demás.
- La clave privada de la CA no entra en git, artefactos, logs ni instaladores.

## Contexto

El workflow `build-pilot-installer.yml` generaba una CA mkcert efímera por ejecución. Cada instalador nuevo traía
una CA distinta y cada supervisor tenía que importarla otra vez; la guía operativa lo exigía por estación. Con una
decena de estaciones esto no escala, y el procedimiento de reemisión (ADR-0023) todavía no existe porque el
broker + step-ca no están desplegados.

## Decisión

1. Una **única CA de piloto** firma todos los certificados *leaf* de estación. Su certificado público es el que
   importan los supervisores (artefacto `the-watcher-pilot-supervisor-trust-*`, idéntico en cada ejecución).
2. La clave privada vive **solo** en el secreto de GitHub `WATCHER_PILOT_CA_KEY` (certificado en
   `WATCHER_PILOT_CA_CERT`). El workflow la escribe en `RUNNER_TEMP`, la borra al terminar (`if: always()`) y nunca
   la sube como artefacto ni la pasa a `build.ps1`. El workflow se ejecuta solo por `workflow_dispatch`.
3. La CA lleva **`nameConstraints` críticas**: DNS `sig.com` y `localhost`; IP `127.0.0.1` y `192.168.0.0/16`.
   `pathlen:0`. Una clave filtrada no puede firmar certificados válidos para otros dominios.
4. El workflow **falla cerrado**: sin secretos, con clave que no corresponde al certificado o con la CA a menos de
   30 días de caducar, no genera ninguna CA de reemplazo.
5. Vida de la CA: 3 años. Rotación = nueva CA, secretos nuevos y reimportación por supervisores.
6. El certificado de la CA **no se versiona** (AGENTS.md: sin material TLS en git); se distribuye por el artefacto
   y el canal de IT, comprobando su huella SHA-256.

## Consecuencias

- Los supervisores confían una vez. Rehacer una estación solo reemite su *leaf*.
- Quien pueda leer secretos del repositorio o ejecutar workflows con ellos puede firmar certificados dentro de las
  restricciones de nombres. El riesgo queda acotado a `sig.com` y la LAN 192.168/16, pero existe.
- Una estación fuera de `sig.com` o de 192.168.0.0/16 no puede usar esta CA; hay que rotarla con otras restricciones.
- El secreto no se puede leer de vuelta desde GitHub: si se pierde, se rota la CA.
- Estaciones ya instaladas con una CA efímera previa siguen funcionando con esa CA hasta reinstalarlas.

## Opciones no elegidas

- **CA efímera por ejecución** (estado anterior): máxima contención, pero reimportación por cada instalador.
- **CA corporativa de SIG** firmando cada estación: no requiere importación alguna, pero depende de que IT emita un
  certificado por estación y de que el instalador acepte certificados externos. Sigue siendo la mejor vía a corto
  plazo si IT puede asumirla.
- **CA sin `nameConstraints`**: más simple, pero una filtración permitiría suplantar cualquier sitio en los PC que
  la importaron.
- **Esperar al modo `remote`** (ADR-0023/0024): es el diseño definitivo, pero aún no hay broker ni step-ca.
