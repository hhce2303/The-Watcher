# Architecture Decision Records

Registro de decisiones de arquitectura del repo (nació en la tab de Edición; hoy es el log de ADRs
del proyecto). Formato: contexto → decisión → consecuencias. Una decisión aceptada no se edita; si
cambia, se crea un ADR nuevo que la *supersede*.

| ADR | Título | Estado |
|-----|--------|--------|
| [0001](ADR-0001-evidence-reel-single-track.md) | Timeline = reel de evidencia de una sola pista | Aceptado |
| [0002](ADR-0002-smart-trim-copy-vs-encode.md) | Trim/export "inteligente": copy + re-encode del GOP de borde | Aceptado |
| [0003](ADR-0003-fullscreen-separate-window.md) | Fullscreen en ventana propia con reparent del videoOutput | Aceptado |
| [0004](ADR-0004-ai-detection-seams.md) | Costuras para IA: DetectorPort / EventStorePort / sidecar | Aceptado |
| [0005](ADR-0005-yolo-licensing.md) | Licencia de YOLO: modelo ONNX propio en vez de Ultralytics AGPL | Aceptado |
| [0006](ADR-0006-rust-segment-engine.md) | Rust como motor de compilación de segmentos tras un port | Aceptado |
| [0007](ADR-0007-dxgi-capture-deferred.md) | Captura DXGI en Rust: diferida | Diferido |
| [0008](ADR-0008-tauri-ui-migration.md) | Migrar la UI a Tauri 2.0 + React (core Python como sidecar) | Aceptado (roadmap) |
| [0009](ADR-0009-input-port-facade.md) | Puerto de entrada: Application Facade + Event Bus | Aceptado (roadmap) |
| [0010](ADR-0010-role-conditional-topology.md) | Topología de proceso condicional por rol (daemon vs sidecar) | Aceptado (roadmap) |
| [0011](ADR-0011-local-ipc-security.md) | Canal IPC local autenticado (named pipe/token + audit) | Aceptado (roadmap) |
| [0012](ADR-0012-rust-hexagon-endgame.md) | Hexágono Rust vía PyO3 como destino (extiende 0006) | Aceptado (roadmap) |

ADR-0008..0012 son la migración de UI a Tauri 2.0 — ver [`docs/migration/`](../../migration/README.md).
