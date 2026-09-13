# ADR-0001 — Timeline = reel de evidencia de una sola pista

- **Estado**: Aceptado
- **Fecha**: 2026-06-22
- **Requisitos**: R-1, R-2, R-5

## Contexto

El tab de edición debe permitir "añadir varios clips a una línea de tiempo". Hay tres ambiciones
posibles: (a) **reel de evidencia** — una sola pista, varios clips recortados y reordenados que se
concatenan en un único MP4; (b) **editor multipista (NLE)** — varias pistas, solapamientos,
transiciones, audio independiente; (c) **solo revisión** — añadir clips para compararlos, sin export
combinado.

El caso de uso real es vigilancia: un operador IT arma una secuencia de momentos relevantes para
entregar como evidencia. Un NLE completo multiplica por 3–4 el esfuerzo (sincronización de pistas,
transiciones, modelo de datos mucho más complejo) sin aportar al caso de uso.

## Decisión

Implementar **(a) reel de evidencia de una sola pista**. Modelo de datos: `EditTimeline` con una
lista ordenada de `ClipEntry` (cada uno con `source_path`, `in_point_s`, `out_point_s`). Sin pistas
múltiples, sin solapamientos, sin transiciones.

## Consecuencias

- ✅ Modelo de datos simple, puro y testeable (`core/editor/`), sin estado de sincronización.
- ✅ La exportación es una concatenación de cortes → encaja directamente con el motor de segmentos
  ([ADR-0006](ADR-0006-rust-segment-engine.md)) y el trim inteligente ([ADR-0002](ADR-0002-smart-trim-copy-vs-encode.md)).
- ➖ No hay crossfades ni mezcla de audio (fuera de alcance, ver [`goals.md`](../goals.md) §4).
- 🔁 Si en el futuro se requiere multipista, será un ADR nuevo que supersede a este; el `EditTimeline`
  actual podría envolverse como "una pista" de un modelo mayor.
