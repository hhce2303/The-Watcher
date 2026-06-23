# Matriz de Trazabilidad (RTM) — Tab de Edición

> Enlaza cada **requisito** ([`goals.md`](goals.md)) con su **diseño**, su **código** y su **prueba**.
> El estado refleja el avance real; se actualiza con cada PR.
>
> Estados: ⬜ pendiente · 🟦 en progreso · ✅ hecho · 🔵 solo diseño (costura)
> Fecha: 2026-06-22

---

## Estado de implementación (2026-06-22)

**Fases 0–2: completas y verificadas — 268 tests en verde** (159 base + 109 nuevos), sin regresiones.
Cableado aditivo en [main.py](../../app/main.py) (registro de `EditorBridge`, selección del motor de
segmentos, `EventStore` + persistencia de eventos manuales). **Capa QML implementada** (reel multi-clip,
zoom espacial, `FullscreenPlayer`, export, seam de marcadores) y validada con `qml_smoke.py`
(tipos) + `qml_runtime_smoke.py` (instanciación con `EditorBridge` real, 0 warnings). **Falta solo
verificación visual ejecutando la GUI.**

| Pieza | Estado | Tests |
|-------|--------|-------|
| `core/editor` (models, sequencer) | ✅ | test_editor_models, test_editor_sequencer |
| `core/analytics` (Detection, AnalyticEvent, sidecar, manual_event) | ✅ | test_analytics_models, test_sidecar, test_manual_event |
| Ports (segment_compiler, editor_export, detector, event_store) | ✅ | (ejercitados por adapters) |
| `FFmpegSegmentCompilerAdapter` + `FFmpegEditorExportAdapter` | ✅ | test_segment_compiler, test_editor_export |
| Motor Rust: selector + wrapper (fallback FFmpeg) | ✅ | test_native_segment_compiler |
| Crate Rust `native/watcher_segments` | 🟦 scaffold | `cargo test` (requiere toolchain Rust) |
| `EditorBridge` (QObject) | ✅ | test_editor_bridge |
| `SqliteEventStoreAdapter` | ✅ | test_event_store |
| `MockDetectorAdapter` + `AutoEventService` | ✅ | test_auto_event_service |
| Persistencia de eventos manuales (EventService.on_clip_built) | ✅ | test_manual_event |
| **QML** (reel multi-clip, zoom espacial, FullscreenPlayer, export, seam markers) | 🟦 impl. + smoke | qml_smoke.py, qml_runtime_smoke.py |

**Pendiente** (no automatizable aquí):
- **Verificación visual** ejecutando la GUI (rol IT): cargar clips → ＋ al reel → reordenar/recortar →
  exportar; zoom de imagen con rueda + arrastre; toggle pantalla completa. El render lógico ya está
  validado headless (tipos + instanciación), falta confirmar el aspecto/interacción reales.
- **Overlay visual de marcadores** sobre el timeline: el *dato* ya está disponible
  (`EditorBridge.eventsForClip`), pero el pintado de pines se difiere a cuando haya eventos sub-clip
  (Fase 3); los eventos manuales actuales abarcan el clip completo.
- **Implementación nativa del crate Rust** (requiere toolchain Rust; el fallback FFmpeg cubre la
  funcionalidad y está testeado).

---

## R-1 — Línea de tiempo multi-clip (reel)

| Aspecto | Referencia |
|---------|-----------|
| Diseño | Plan Parte A1 · [ADR-0001](adr/ADR-0001-evidence-reel-single-track.md) |
| Código (dominio) | `app/core/editor/models.py` (`ClipEntry`, `EditTimeline`), `app/core/editor/sequencer.py` (`TimelineSequencer`) |
| Código (puente) | `app/adapters/ui/editor_bridge.py` (`EditorBridge`) |
| Código (UI) | `app/adapters/ui/qml/VideoEditor.qml` (track → `Repeater`), `ClipBrowser.qml` ("Añadir al timeline") |
| Prueba | `tests/editor/test_models.py` (add/remove/move/total_duration), `tests/editor/test_sequencer.py` (mapeo posición↔clip en límites) |
| Estado | ⬜ |

## R-2 — Recorte (trim) por clip

| Aspecto | Referencia |
|---------|-----------|
| Diseño | Plan Parte A2 |
| Código | `ClipEntry.in_point_s/out_point_s` en `app/core/editor/models.py`; handles IN/OUT en `VideoEditor.qml` (reusa marcas existentes [L65](../../app/adapters/ui/qml/VideoEditor.qml#L65)) |
| Prueba | `tests/editor/test_models.py` (trim afecta duración y orden) |
| Estado | ⬜ |

## R-3 — Zoom de video (temporal + espacial)

| Aspecto | Referencia |
|---------|-----------|
| Diseño | Plan Parte A3 |
| Código (temporal) | Ya existe: `zoom`/`tickCount` + Flickable en `VideoEditor.qml` ([L43](../../app/adapters/ui/qml/VideoEditor.qml#L43)) |
| Código (espacial) | `VideoOutput` + `WheelHandler`/`DragHandler` + `layer.smooth` en `VideoEditor.qml` (patrón de `Main.qml` [L1038](../../app/adapters/ui/Main.qml#L1038)) |
| Prueba | Manual (checklist [`goals.md`](goals.md) §verificación del plan); sin lógica core que testear |
| Estado | 🟦 (temporal hecho; espacial pendiente) |

## R-4 — Pantalla completa sin pérdida

| Aspecto | Referencia |
|---------|-----------|
| Diseño | Plan Parte A4 · [ADR-0003](adr/ADR-0003-fullscreen-separate-window.md) |
| Código | `app/adapters/ui/qml/FullscreenPlayer.qml` (Window propio, reparent del `videoOutput`); toggle en `VideoEditor.qml` |
| Prueba | Manual (toggle F/ESC, calidad a resolución nativa) |
| Estado | ⬜ |

## R-5 — Exportación concatenada inteligente

| Aspecto | Referencia |
|---------|-----------|
| Diseño | Plan Parte A2 · [ADR-0002](adr/ADR-0002-smart-trim-copy-vs-encode.md) |
| Código (port) | `app/core/ports/editor_export_port.py` (`EditorExportPort`) |
| Código (adapter) | `app/adapters/ffmpeg/editor_export_adapter.py` (`FFmpegEditorExportAdapter`); reusa `_write_concat_file` de [trim_adapter.py](../../app/adapters/ffmpeg/trim_adapter.py#L281) y `encoder_selector.py` |
| Código (UI) | `OutputPanel.qml` → `EditorBridge.exportTimeline` + progreso |
| Prueba | `tests/editor/test_export_adapter.py` (construcción de args, subprocess mockeado); paridad sin pérdida |
| Estado | ⬜ |

## R-6 — Motor nativo de segmentos en Rust

| Aspecto | Referencia |
|---------|-----------|
| Diseño | Plan Parte C · [ADR-0006](adr/ADR-0006-rust-segment-engine.md) |
| Código (port) | `app/core/ports/segment_compiler_port.py` (`SegmentCompilerPort`) |
| Código (crate) | `native/watcher_segments/` (`Cargo.toml`, `src/lib.rs`: demux `mpeg2ts-reader` + mux `muxide` + concat + trim por keyframe) |
| Código (adapter) | `app/adapters/native/rust_segment_compiler.py` (default) + fallback FFmpeg (reusa `ClipPort._build_single`) |
| Código (build) | `setup_env.ps1` (maturin develop), `installer/build.ps1` + `The Watcher.spec` (bundle del `.pyd`) |
| Prueba | `cargo test` (remux/concat/trim, propiedad sin pérdida); `tests/native/test_segment_parity.py` (Rust vs FFmpeg) |
| Estado | ⬜ |

## R-AI — Costuras para IA (solo diseño)

| Aspecto | Referencia |
|---------|-----------|
| Diseño | Plan Parte B · [`roadmap.md`](roadmap.md) · [ADR-0004](adr/ADR-0004-ai-detection-seams.md) |
| Código (esquema) | `app/core/analytics/models.py` (`Detection`, `AnalyticEvent`, `schema_version`) |
| Código (ports) | `app/core/ports/detector_port.py`, `app/core/ports/event_store_port.py` (ABCs vacíos) |
| Código (UI) | capa `events` en `EditTimeline`/timeline (vacía, lista para poblar) |
| Prueba | `tests/analytics/test_schema.py` (validación pydantic); adapter mock de `DetectorPort` |
| Estado | 🔵 |

---

## Requisitos no funcionales

| ID | Verificación | Estado |
|----|-------------|--------|
| R-NF1 (sin pérdida bit-idéntico) | `tests/native/test_segment_parity.py` + comparación de códec/SPS-PPS/nº frames | ⬜ |
| R-NF2 (latencia de compilación) | benchmark Rust vs FFmpeg sobre reel de ~5 min | ⬜ |
| R-NF3 (pureza del core) | inspección + tests core sin import de Qt/FFmpeg/Rust | ⬜ |
| R-NF4 (empaquetado del .pyd) | build limpio + arranque con y sin `.pyd` | ⬜ |
| R-NF5 (compatibilidad de segmentos) | respeta `segment_floor` ([buffer_manager.py L79](../../app/core/recording_service/buffer_manager.py#L79)) | ⬜ |
