# How-to — Migrar una vista QML a React (detrás del Facade)

Cómo portar **una** vista concreta de QML a React sin regresión, aprovechando que QML y React son
adaptadores intercambiables sobre el mismo `core/api` Facade. Al terminar, la vista React tiene
paridad funcional con su equivalente QML y el resto de la app sigue igual.

> Prerequisito de arquitectura: la Fase 1 ya creó `core/api` (Facade + DTOs + event bus) y
> `adapters/ipc`. Ver [ADR-0009](../editing/adr/ADR-0009-input-port-facade.md). Si la vista usa una
> operación que aún no está en el Facade, se añade primero al Facade (no en el adaptador).

## Prerequisitos

- `core/api` y `adapters/ipc` operativos (Fase 1 completa).
- El proyecto React (`src/`) con el tema portado desde `Tokens.qml` y la librería de componentes
  desde los `W*` (`WToggle`, `WDropdown`, `WStepper`, `WPathInput`, `WSeg`, `WHotkey`,
  `WSettingsRow`).
- Tipos TS generados desde `core/api/dto.py`.

## Orden recomendado (menor a mayor riesgo)

1. `SettingsView` (formularios) → 2. `Statusbar`/`HealthBadge`/`NotificationStrip`/`MonitorSelector`
→ 3. `ClipBrowser`/`OutputPanel` → 4. `SupervisorView`/`ITInboxPanel` → 5. `FullscreenPlayer` →
6. **`VideoEditor`/`ITEditorView`** (lo más difícil, al final) → 7. wizard/mini/overlays.

## Pasos

1. **Inventaria la superficie de la vista QML.** Abre el `.qml` bajo `project/app/adapters/ui/qml/`
   y lista: qué comandos del bridge invoca (`AppBridge.xxx()`), a qué señales se suscribe
   (`Connections { onXxx: }`), y qué propiedades lee. Cada uno ya está mapeado en el
   [contrato IPC](reference-target-architecture.md#contrato-ipc--mapeo-bridges-qml--comandoseventos).

2. **Verifica que el Facade cubre esos comandos/eventos.** Si falta uno, **añádelo al Facade**
   (`core/api/*_api.py` + DTO en `dto.py`), no al adaptador. Regenera los tipos TS. Así QML y React
   siguen hablando el mismo contrato.

3. **Construye el componente React.** Usa el tema y la librería de componentes. Consume el canal IPC:
   comandos como request/response, eventos como suscripción al stream (nada de polling nuevo).

4. **Verifica paridad contra la vista QML.** Con el mismo backend, compara comportamiento estado por
   estado (loading, vacío, error, éxito). La vista QML sigue disponible como oráculo hasta el cutover.

5. **Cubre los estados que el web hace distinto.** Reproducción de video (HEVC → ver
   [how-to F0](howto-f0-gate.md)), scrub frame-exact, y el preview en vivo (transporte del gate F0).

## Verificación

- `run.ps1` muestra la vista React; comportamiento idéntico a la QML equivalente en los 4 estados.
- `pytest` sigue verde (no tocaste el core ni el Facade salvo añadir comandos).
- Smoke de la vista en el webview.

## Troubleshooting

- **Un evento no llega a React:** confirma que el adaptador Qt fino y el `adapters/ipc` se suscriben
  al **mismo** event bus; el bus es la fuente, no las Qt Signals.
- **Necesitas lógica nueva en el componente:** huele a lógica que debería estar en el Facade. Muévela
  al Facade — los adaptadores de entrada no llevan lógica de negocio (ver
  [ADR-0009](../editing/adr/ADR-0009-input-port-facade.md)).
- **La vista es el editor:** no la tomes como "una vista más" — es 40-60% del esfuerzo de F2;
  sub-fásea (prototipo de scrub primero) y déjala al final.

## Relacionado
- [Referencia — Contrato IPC](reference-target-architecture.md) · [ADR-0009](../editing/adr/ADR-0009-input-port-facade.md)
