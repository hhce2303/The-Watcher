# ADR-0009 — Puerto de entrada: Application Facade + Event Bus

- **Estado**: Aceptado (roadmap)
- **Fecha**: 2026-06-30
- **Origen**: `/plan-eng-review` — objeción del owner: "la comunicación UI↔core no está definida según la arquitectura"
- **Docs**: [referencia — puerto de entrada](../../migration/reference-target-architecture.md#puerto-de-entrada-coreapi--la-frontera-ui--core)

## Contexto

El repo formaliza **solo el lado derecho** del hexágono: los *driven ports* en
[`app/core/ports/`](../../../app/core/ports) (`RecorderPort`, `ClipPort`, `CloudSharePort`,
`EditorExportPort`, `PlayerPort`, `StoragePort`, `MonitorPort`, `RequestPort`). El **lado izquierdo
(driving) no tiene puerto explícito**: los bridges QML sostienen los servicios y los orquestan
directamente, mezclando Qt con lógica. Verificado:

- [`app/adapters/ui/app_bridge.py:367`](../../../app/adapters/ui/app_bridge.py#L367) → `self._recording_service.start()`
- [`app/adapters/ui/app_bridge.py:355`](../../../app/adapters/ui/app_bridge.py#L355) → `self._event_service.trigger_manual_event()`
- [`app/adapters/ui/editor_bridge.py:87`](../../../app/adapters/ui/editor_bridge.py#L87) → `self._timeline.add(ClipEntry(...))`

No existe `core/api`, `core/use_cases` ni `core/facade`. Si solo se cambia QML por un servidor WS, el
acoplamiento pasa de "Qt-en-bridge" a "WS-en-servidor" — mismo problema, otra capa.

## Decisión

Introducir el **puerto de entrada** que falta, en `app/core/api/` (**sin Qt, sin WS, sin JSON**):

- **Facade** (`recording_api.py`, `settings_api.py`, `editor_api.py`): la unión de lo que hacen los 3
  bridges, como métodos que aceptan **comandos** (DTOs) y devuelven **DTOs**. Por dentro llaman a los
  servicios existentes — las mismas llamadas que hoy hacen los bridges, movidas detrás del puerto.
- **Event bus** (`events.py`): registro de observadores thread-safe (`subscribe`/`publish`) que
  reemplaza las Qt Signals. Normaliza los callbacks de fondo del core (`on_segment_finalized`,
  `on_clip_built`, `on_monitors_changed`) a eventos tipados y hace fan-out.
- **DTOs** (`dto.py`, Pydantic): fuente única del contrato; de aquí se generan los tipos TS.
- **QML y el nuevo `adapters/ipc/` son adaptadores de entrada intercambiables** sobre el mismo
  facade. Los bridges QML se adelgazan a puro transporte (las Signals solo reenvían eventos del bus).
  Cada adaptador conoce su transporte, no la lógica. El único lugar con serialización es
  `adapters/ipc`.

## Consecuencias

- ✅ QML y React coexisten en F1-F2 **sin duplicar lógica** (un facade, dos adaptadores) → migración
  vista por vista sin regresión.
- ✅ Extensible: mañana un adaptador CLI o un arnés de test pueden driver el mismo puerto.
- ✅ En el endgame Rust, el Facade pasa a traits Rust + comandos Tauri nativos y `adapters/ipc`
  desaparece; la frontera lógica se conserva (ver [ADR-0012](ADR-0012-rust-hexagon-endgame.md)).
- ➖ Trabajo de F1: mover orquestación de los 3 bridges al Facade y construir el event bus
  thread-safe (riesgo de deadlock/backpressure al puentear callbacks de hilos a un servidor asyncio →
  `queue.Queue`/`asyncio.Queue` + tests de carga concurrente).
- ➖ Los callbacks del core corren en hilos de fondo (p. ej. `on_segment_finalized` desde el hilo del
  watchdog FFmpeg); hay que documentar el contexto de hilo de cada uno.

## Evidencia externa (investigación 2026-07)

- Para el contrato tipado: `tauri-specta` / `TauRPC` generan tipos TS desde el backend (un solo
  contrato, sin drift). La **invoke JSON de Tauri serializa a strings** (cuello de botella para
  binarios, TD-5) → el preview no va por el Facade JSON sino por canal binario. Ver
  [tech-debt-and-best-practices](../../migration/tech-debt-and-best-practices.md).
