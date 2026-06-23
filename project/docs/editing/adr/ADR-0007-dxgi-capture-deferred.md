# ADR-0007 — Captura DXGI en Rust: diferida

- **Estado**: Diferido
- **Fecha**: 2026-06-22
- **Requisitos**: Roadmap Track Rust (Rust-4)

## Contexto

La captura actual usa `ffmpeg -f gdigrab` (GDI BitBlt), probada y robusta para todos los monitores
(incluidas coordenadas negativas y GPUs secundarias). La API **DXGI Desktop Duplication** (crates
`windows` / `windows-capture`) entrega frames directamente como texturas GPU, evitando copias a
memoria de sistema, y puede reducir ~15–25% la CPU en captura 4K.

## Decisión

**Diferir.** No se reemplaza gdigrab por DXGI ahora. Se reconsiderará **solo si** el profiling
demuestra que la captura es el cuello de botella de CPU, y después de que el motor de segmentos Rust
([ADR-0006](ADR-0006-rust-segment-engine.md)) esté en producción y el equipo tenga rodaje con la
cadena Rust.

## Consecuencias

- ✅ Se evita riesgo en una ruta crítica y ya probada; foco en entregables de mayor ROI.
- ➖ Se deja sobre la mesa una mejora de CPU para 4K.
- 🔁 Cuando se retome, será un ADR nuevo (medición de profiling + plan de migración con fallback a
  gdigrab) que supersede el estado "Diferido" de este.
