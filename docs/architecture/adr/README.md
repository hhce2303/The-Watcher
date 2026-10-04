# Architecture Decision Records

Registro de decisiones de arquitectura de `the-watcher-daemon`. Formato: contexto → decisión → consecuencias →
opciones no elegidas (ver plantilla en cualquier ADR). Una decisión aceptada no se edita; si cambia, un ADR nuevo
la *supersede*.

## ADRs de este repo

Numeración: 0001–0005 reservados para este repo (los 0001–0005 del monorepo, de editor/IA, no se copiaron);
los siguientes ADRs nuevos usan **0024** en adelante (el siguiente libre es **0027**), para no chocar con los heredados.

| ADR | Título | Estado |
|-----|--------|--------|
| [0001](ADR-0001-recording-streaming-source-of-truth.md) | Fuente de verdad de grabación y streaming | Aceptado |
| [0002](ADR-0002-thin-composition-root-and-daemon-api.md) | Raíz de composición delgada y `DaemonApi` mínima | Aceptado |
| [0003](ADR-0003-exclude-auto-event-service-and-preview-server.md) | `auto_event_service` y `preview_server` MJPEG quedan fuera del daemon | Aceptado |
| [0024](ADR-0024-tls-issuance-governance.md) | Gobernanza de emisión TLS: step-ca tras broker, claves separadas, nonce duradero y piloto de 90 días (enmienda 0023) | Aceptado |
| [0025](ADR-0025-persistent-pilot-ca-in-github-secret.md) | CA de piloto persistente, con restricción de nombres, en un secreto de GitHub | Aceptado |
| [0026](ADR-0026-standard-field-steps-as-installed-scripts.md) | Pasos de campo del piloto (firewall, enrolamiento) como scripts versionados instalados con el daemon | Aceptado |

## ADRs heredados del monorepo (IDs del monorepo, copiados tal cual)

Contexto histórico; pueden mencionar roles, IPC, Tauri o eventos que no existen en este repo. Los enlaces a ADRs
no copiados (0001–0005, 0008–0012, 0018, 0020) se muestran como texto. Solo se tocaron enlaces/rutas
(`project/app/…` → `app/…`), no el contenido de las decisiones.

| ADR | Título | Estado |
|-----|--------|--------|
| [0006](ADR-0006-rust-segment-engine.md) | Rust como motor de compilación de segmentos tras un port | Aceptado |
| [0007](ADR-0007-dxgi-capture-deferred.md) | Captura DXGI en Rust: diferida | Diferido |
| [0013](ADR-0013-ddagrab-capture-cursor-flicker.md) | Captura por ddagrab (DXGI) para eliminar el titileo del cursor (realiza parcial 0007) | Aceptado |
| [0014](ADR-0014-zerocopy-qsv-capture-pipeline.md) | Pipeline de captura zero-copy (D3D11→QSV/CUDA) tras ddagrab (PoC-1) | Aceptado |
| [0015](ADR-0015-batch-ffmpeg-governance.md) | Gobernanza de FFmpeg batch: Job Object compartido + semáforo + telemetría (PoC-2) | Aceptado |
| [0016](ADR-0016-recorder-supervision-ctypes-not-rust.md) | Supervisión del recorder: fix ctypes en vez de crate Rust (Track R2 M2-M4 diferidos) | Aceptado |
| [0017](ADR-0017-adr0007-sla-verdict-confirmed.md) | Gate 0007 resuelto: CPU de captura confirmada dentro de SLA, Track R3 no se activa | Aceptado |
| [0019](ADR-0019-auto-event-clip-build-coalescing.md) | Auto-eventos: build de clip por EventService (retry+logging) + coalescencia de ventana (fix sobreesfuerzo) | Aceptado |
| [0021](ADR-0021-supervision-lan-live-view.md) | Supervisión LAN autenticada para vistas en vivo | Aceptado (transporte enmendado por 0022) |
| [0022](ADR-0022-live-view-h264-websocket.md) | Live view: H.264 sobre un único WebSocket, MJPEG como respaldo | Aceptado |
| [0023](ADR-0023-external-tls-provisioning-service.md) | Aprovisionamiento TLS como servicio externo (`the-watcher-certs`), CSR desde el daemon, emisión única, CA local de IT | Aceptado (pendientes de fase 2 fijados por [0024](ADR-0024-tls-issuance-governance.md)) |

Los ADR-0008..0012 (migración de UI a Tauri 2.0, IPC, roles) permanecen solo en el monorepo y no aplican aquí:
este daemon no tiene UI Tauri ni pipe IPC (ADR-0002).
