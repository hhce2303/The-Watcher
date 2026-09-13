# Tab de Edición — Metas y Requisitos

> Documento de **metas** (la "M" de trazabilidad). Define *qué* se construye y *por qué*.
> Cada requisito tiene un ID estable que se referencia desde
> [`traceability-matrix.md`](traceability-matrix.md), los [ADRs](adr/) y los commits.
>
> Estado: **propuesta aprobada** · Fecha: 2026-06-22 · Rol objetivo: **IT** (vista `ITEditorView`).

---

## 1. Visión

Convertir el tab de edición del rol IT en una herramienta de **armado de reels de evidencia**:
el operador IT carga uno o varios clips grabados, los recorta, los ordena en una sola línea de
tiempo y exporta **un único MP4** — manteniendo la calidad de origen siempre que sea posible.
Todo el diseño deja preparadas las **costuras** para un futuro motor de detección de eventos
(YOLO) + analíticos, sin construirlo todavía.

Principios rectores:
- **Sin pérdida por defecto.** La cadena de custodia de la evidencia exige no recodificar salvo
  cuando sea imprescindible (corte exacto por frame o composición multi-monitor).
- **Hexagonal.** El dominio (`core/`) no conoce Qt ni FFmpeg ni Rust; todo va detrás de *ports*.
- **Degradación elegante.** Las optimizaciones nativas (Rust) son opcionales: si faltan, la app
  funciona igual con la ruta FFmpeg.
- **Linealidad hacia IA.** Cada decisión de diseño se elige de modo que el pipeline de inferencia
  futuro se acople sin reescrituras (ver [`roadmap.md`](roadmap.md)).

---

## 2. Requisitos funcionales

| ID | Requisito | Detalle / criterio de aceptación |
|----|-----------|----------------------------------|
| **R-1** | Línea de tiempo multi-clip (reel) | Una sola pista. Se pueden **añadir varios clips** (de distintos archivos/monitores), **reordenarlos** y **eliminarlos**. El playhead recorre todo el reel y la reproducción salta de un clip al siguiente sin intervención. |
| **R-2** | Recorte (trim) por clip | Cada clip tiene marcas **IN/OUT** editables (reutiliza las ya existentes en `VideoEditor.qml`). El recorte se refleja en la duración del reel y en el export. |
| **R-3** | Zoom de video | **(a) Temporal**: zoom 1×–8× del timeline (ya existe). **(b) Espacial**: zoom + paneo sobre la imagen del `VideoOutput` **sin pérdida** hasta la resolución nativa del clip. |
| **R-4** | Pantalla completa sin perder calidad | Modo fullscreen en ventana propia a resolución nativa del monitor; reusa el `MediaPlayer` ya inicializado (sin doble decodificación). Toggle por botón + teclas F/ESC. |
| **R-5** | Exportación concatenada inteligente | Exporta el reel a un único MP4. **Copia de stream sin pérdida** cuando el corte cae cerca de un keyframe; **re-encode solo del GOP de borde** cuando se exige corte exacto por frame. |
| **R-6** | Motor nativo de compilación de segmentos (Rust) | El *hot path* sin pérdida (remux MPEG-TS→MP4 + concatenación + recorte por keyframe) lo ejecuta un crate Rust (`.pyd` vía PyO3/maturin) detrás de `SegmentCompilerPort`, con **FFmpeg como fallback**. |
| **R-AI** | Costuras para IA (solo diseño) | Existen los *ports* y esquemas (`DetectorPort`, `EventStorePort`, esquema de `Detection`/`AnalyticEvent`, sidecar `*.events.json`) y una **capa de marcadores** en el timeline lista para poblarse, sin implementar inferencia. |

---

## 3. Requisitos no funcionales

| ID | Requisito | Métrica / objetivo |
|----|-----------|--------------------|
| **R-NF1** | Calidad de exportación | El video copiado por *stream-copy* es **bit-idéntico** al origen (mismo códec, SPS/PPS y nº de frames). Solo el GOP de borde recodificado difiere. |
| **R-NF2** | Latencia de compilación del clip | El remux/concat sin pérdida de un reel de ~5 min debe ser **notablemente más rápido** que el re-encode equivalente; objetivo: dominado por I/O, no por CPU. Se mide en la fase de implementación de R-6. |
| **R-NF3** | Pureza del core | `core/editor` y `core/analytics` **no importan** Qt/FFmpeg/Rust/torch. Verificable por inspección + tests sin dependencias gráficas. |
| **R-NF4** | Empaquetado | El `.pyd` de Rust se incluye en el bundle PyInstaller **sin DLLs externas** (crates puros). Si falta, la app arranca igual (fallback FFmpeg). |
| **R-NF5** | Compatibilidad de segmentos | Nunca se concatenan segmentos de configuraciones de monitor distintas (dimensiones incompatibles); se respeta el `segment_floor` de `buffer_manager.py`. |

---

## 4. Fuera de alcance (en esta iteración)

- Editor multipista/NLE (varias pistas, solapamientos, transiciones/crossfade). — *Descartado en [ADR-0001](adr/ADR-0001-evidence-reel-single-track.md).*
- Tab de Analíticos y modelo YOLO real. — *Roadmap Fases 3–4, ver [`roadmap.md`](roadmap.md).*
- Captura de pantalla nativa DXGI en Rust. — *Diferido, ver [ADR-0007](adr/ADR-0007-dxgi-capture-deferred.md).*
- Edición de audio (mezcla, niveles), corrección de color.

---

## 5. Trazabilidad

Cada requisito de arriba se enlaza con su **diseño → código → prueba** en
[`traceability-matrix.md`](traceability-matrix.md). Las decisiones que afectan a varios requisitos
se registran como [ADRs](adr/). La secuencia temporal y los criterios de salida por fase están en
[`roadmap.md`](roadmap.md).
