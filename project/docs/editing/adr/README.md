# Architecture Decision Records — Tab de Edición

Registro de decisiones de arquitectura. Formato: contexto → decisión → consecuencias.
Una decisión aceptada no se edita; si cambia, se crea un ADR nuevo que la *supersede*.

| ADR | Título | Estado |
|-----|--------|--------|
| [0001](ADR-0001-evidence-reel-single-track.md) | Timeline = reel de evidencia de una sola pista | Aceptado |
| [0002](ADR-0002-smart-trim-copy-vs-encode.md) | Trim/export "inteligente": copy + re-encode del GOP de borde | Aceptado |
| [0003](ADR-0003-fullscreen-separate-window.md) | Fullscreen en ventana propia con reparent del videoOutput | Aceptado |
| [0004](ADR-0004-ai-detection-seams.md) | Costuras para IA: DetectorPort / EventStorePort / sidecar | Aceptado |
| [0005](ADR-0005-yolo-licensing.md) | Licencia de YOLO: modelo ONNX propio en vez de Ultralytics AGPL | Aceptado |
| [0006](ADR-0006-rust-segment-engine.md) | Rust como motor de compilación de segmentos tras un port | Aceptado |
| [0007](ADR-0007-dxgi-capture-deferred.md) | Captura DXGI en Rust: diferida | Diferido |
