# ADR-0004 — Costuras para IA: DetectorPort / EventStorePort / sidecar

- **Estado**: Aceptado
- **Fecha**: 2026-06-22
- **Requisitos**: R-AI · Roadmap Fases 1–4

## Contexto

El producto tendrá en el futuro detección de eventos con YOLO + analíticos. Si no se dejan las
costuras ahora, añadir ML más tarde obligaría a reescribir el editor y el pipeline de eventos. La
arquitectura de referencia (Frigate NVR, MIT) muestra el patrón: **decode → detect → track → event**,
donde los eventos son *clip + metadatos* y el timeline son *marcadores consultables*, y la inferencia
nunca bloquea la grabación.

## Decisión

Declarar **ahora** (sin implementar inferencia) estas costuras:

- **`DetectorPort`** (`core/ports/detector_port.py`, ABC): `analyze(frame, meta) -> list[Detection]`
  + callback `on_detections`. Adapter futuro en `adapters/ml/`; adapter **mock** para tests.
- **`EventStorePort`** (`core/ports/event_store_port.py`, ABC): persistir/consultar detecciones y
  eventos por tiempo/tipo/monitor. Adapter v1 futuro: SQLite.
- **Esquema versionado** (`core/analytics/models.py`, pydantic): `Detection` y `AnalyticEvent` con
  `schema_version`.
- **Sidecar** `<clip>.events.json` versionado y regenerable, junto a cada clip.
- **Capa `events`** en el timeline (vacía ahora) lista para pintar marcadores clicables.
- Reutilizar el `EventContext` inmutable de [`event_service.py`](../../app/core/event_service.py) y el
  flujo `snapshot_event()`/`build()` para disparos automáticos (`AutoEventService` futuro) — mismo
  código que el disparo manual.

## Consecuencias

- ✅ La IA se acopla por adapters, sin tocar el core ni el editor.
- ✅ El pipeline de eventos manual y el automático comparten implementación → menos código, misma
  garantía de determinismo.
- ➖ Coste de mantener ports/esquemas "vacíos" hasta la Fase 2–3 (bajo; son contratos + un mock).
- 🔗 Detalle de fases y criterios de salida en [`roadmap.md`](../roadmap.md).
