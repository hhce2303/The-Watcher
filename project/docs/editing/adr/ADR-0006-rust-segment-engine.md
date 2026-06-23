# ADR-0006 — Rust como motor de compilación de segmentos tras un port

- **Estado**: Aceptado
- **Fecha**: 2026-06-22
- **Requisitos**: R-6, R-NF1, R-NF3, R-NF4, R-NF5

## Contexto

El *hot path* de "compilar/construir segmentos" (parsear MPEG-TS `.ts`, remuxear a MP4, concatenar
varios y recortar por keyframe — todo **sin pérdida**) hoy delega siempre a `ffmpeg.exe` por
subprocess. Es trabajo CPU/IO de manipulación de paquetes: ideal para Rust (seguridad de memoria, sin
coste de lanzar procesos, latencia predecible). El owner pidió Rust como **componente directo del
core** para esta tarea.

Restricciones: AGENTS.md prohíbe importar Qt/FFmpeg/screeninfo en `core/`; el build es PyInstaller +
venv en Windows; los entornos son multi-PC (OneDrive) y los venvs se recrean por máquina.

## Decisión

- Crate Rust `native/watcher_segments/` compilado a `.pyd` con **PyO3 + maturin**, usando crates
  **puros** `mpeg2ts-reader` + `muxide` (MIT/Apache). **Sin dependencia de FFmpeg ni DLLs externas.**
- La **capacidad** se expone como contrato de core: `SegmentCompilerPort` (`core/ports/`). Esa es la
  pieza "del core". El **motor por defecto** es el adapter Rust
  (`adapters/native/rust_segment_compiler.py`); FFmpeg queda como **fallback** detrás del mismo port.
- Un `.pyd` de Rust no es Qt/FFmpeg/screeninfo, así que no viola la regla de AGENTS.md; aun así se deja
  tras un Protocol para no acoplar el core a un artefacto compilado y poder mockearlo.
- Rust hace solo lo **sin pérdida**; cualquier decode/scale/encode (grid multi-monitor, GOP de borde,
  timestamp) sigue en FFmpeg.

## Consecuencias

- ✅ Rendimiento y latencia predecibles en el caso común; bundle limpio (un solo `.pyd`, sin DLLs).
- ✅ Core testeable (port mockeable); la app arranca aunque falte el `.pyd` (fallback FFmpeg).
- ✅ Establece la cadena PyO3/maturin, reutilizable para la inferencia ONNX/`ort` futura ([ADR-0005](ADR-0005-yolo-licensing.md)).
- ➖ Nueva dependencia de build: toolchain Rust (rustup + MSVC) y maturin en `setup_env.ps1`/`build.ps1`;
  el `.pyd` se compila por máquina.
- ➖ Hay que respetar el `segment_floor` ([buffer_manager.py L79](../../app/core/recording_service/buffer_manager.py#L79)):
  el motor solo recibe segmentos de dimensiones compatibles (R-NF5).
- ➖ Cuidado con la detección de DLLs transitivas del `.pyd` en PyInstaller (mitigado por usar crates puros).
