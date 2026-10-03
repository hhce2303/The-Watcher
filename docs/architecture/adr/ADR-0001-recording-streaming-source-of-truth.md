# ADR-0001 — Fuente de verdad de grabación y streaming

- **Estado**: Aceptado
- **Fecha**: 2026-10-03
- **Requisitos**: criterio de éxito del spec de extracción (`docs/extraction.md`, §1): el daemon se construye, prueba y publica sin depender del estado del monorepo.

## Contexto

El monorepo `The-Watcher` mezcla roles (Operador/IT/Supervisor), editor, player, analítica, cloud-share, UI
Tauri y el daemon de grabación + streaming LAN. No se puede estabilizar entero a tiempo; el daemon sí está
cerca (streaming maduro, grabación con fallas conocidas, ver `docs/backlog/known-recording-issues.md`).
El acoplamiento no está en el negocio sino en la raíz de composición (`main.py`, `runtime/backend.py`,
`core/api/bootstrap.py::ApiLayer`).

El usuario decidió (no se reabre): la extracción es una **copia, no una mudanza**; el consumidor único es
operadores/supervisión LAN; y el repo nuevo es la fuente de verdad.

## Decisión

`the-watcher-daemon` es la **fuente de verdad** del código de grabación y de streaming LAN del Operador:
`core/recording_service`, `recording_health`, `disk_monitor`, `monitor_detection`, los adaptadores
`ffmpeg`/`native`/`monitor`/`filesystem`(storage)/`live_view_lan`/`tls_provisioning`/`browser_local.{auth,identity}`,
`infrastructure/`, el crate `native/watcher_segments`, el instalador y su CI.

- Todo cambio de comportamiento en esas piezas se hace **aquí**. El monorepo no evoluciona su copia.
- El monorepo no se modifica ni se borra nada por ahora; qué hacer con su copia (consumir el binario, dejarla
  congelada) es una decisión posterior del usuario. Una nota equivalente a este ADR (solo documentación) se
  añadirá allí cuando el usuario lo decida.
- La sincronización es **unidireccional y explícita**: no hay backports automáticos desde el monorepo; si un
  fix urgente aterriza allí, se porta aquí por revisión (cherry-pick manual) y se anota en el CHANGELOG.
- El historial de git de las rutas copiadas se conserva (ver `docs/extraction.md`).

## Consecuencias

- Positivas: release, CI y bundle independientes; superficie de pruebas acotada; el gate de pureza de imports
  (`tests/test_import_purity.py`) impide que editor/player/analítica/Qt/Tauri vuelvan a entrar.
- Negativas: **dos copias divergentes** del mismo código mientras el monorepo no decida; los consumidores del
  monorepo (UI Tauri vía `ApiLayer`) seguirán usando una copia que ya no recibe fixes; los ADRs heredados
  (0006–0023) existen en ambos repos y pueden desfasarse; la persistencia `user_config.json` y los
  controles IT/Supervisor no existen aquí (ver ADR-0002).
- Neutras: la numeración de ADRs heredados es la del monorepo; los ADRs nuevos de este repo usan 0001–0005
  (los 0001–0005 del monorepo, de editor/IA, no se copiaron) y luego 0024 en adelante.

## Opciones no elegidas

- **Mudanza** (borrar del monorepo): descartada por el usuario; el monorepo queda intacto.
- **Paquete compartido `watcher-core`** consumido por ambos repos: YAGNI en esta fase (spec §8); reabrir si la
  divergencia duele.
- **git submodule/subtree** del subconjunto: acopla el release del daemon al monorepo, que es justo lo que se evita.
