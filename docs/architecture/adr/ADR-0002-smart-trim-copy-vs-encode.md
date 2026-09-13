# ADR-0002 — Trim/export "inteligente": stream-copy + re-encode del GOP de borde

- **Estado**: Aceptado
- **Fecha**: 2026-06-22
- **Requisitos**: R-5, R-NF1

## Contexto

Al recortar y concatenar clips hay un compromiso clásico:

- **Stream-copy (`-c copy`)**: sin pérdida y rapidísimo, pero los cortes solo caen en *keyframes*
  (cada ~1–3 s en H.264/H.265), así que el corte no es exacto al frame.
- **Re-encode**: corte exacto al frame, pero recodifica todo (lento, depende del encoder por
  hardware y aplica una leve recompresión — indeseable para evidencia).

La evidencia exige máxima fidelidad; el operador a veces necesita un corte preciso.

## Decisión

Estrategia **inteligente** por clip:
1. Si IN **y** OUT caen dentro de una tolerancia de un keyframe → **stream-copy** del clip completo.
2. Si no → **re-encode solo del GOP de borde** (el grupo de imágenes que contiene el punto de corte)
   y stream-copy del interior; luego concatenar las partes.

El interior sin pérdida y la concatenación los hace el motor Rust ([ADR-0006](ADR-0006-rust-segment-engine.md));
el re-encode del GOP de borde lo hace FFmpeg con el encoder de `encoder_selector.py`.

## Consecuencias

- ✅ Sin pérdida en el 99% del material (R-NF1); recompresión limitada al GOP de borde cuando hace
  falta precisión.
- ✅ Rápido en el caso común (cortes alineados a keyframe → copy puro).
- ➖ Complejidad: hay que consultar keyframes (ffprobe) y orquestar dos rutas.
- 📚 Referencia de la técnica: LosslessCut (modo "smart cut"). Un smart-cut 100% en Rust se descartó
  por no compensar (requiere un encoder en Rust); FFmpeg cubre el borde.
