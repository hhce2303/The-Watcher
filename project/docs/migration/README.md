# Migración de UI a Tauri 2.0 — Documentación

Documentación completa de la transición de la UI de The Watcher desde **PySide6/QML** a
**Tauri 2.0 + React**, con el core Python como sidecar ahora y destino **hexágono Rust** vía PyO3.

> **Estado:** roadmap aprobado (2026-06-30), **no implementado todavía**. El código sigue siendo
> 100% QML. La implementación está **condicionada al GO del gate F0** (ver
> [how-to F0](howto-f0-gate.md)). Origen: revisión `/office-hours` → `/plan-eng-review`.

## Índice (Diataxis)

| Documento | Cuadrante | Para quién / cuándo |
|-----------|-----------|----------------------|
| [Explicación — Por qué migrar a Tauri](explanation-tauri-migration.md) | Explanation | Entender la decisión: motivaciones, costura limpia, pros/contras, escalabilidad |
| [Referencia — Arquitectura objetivo](reference-target-architecture.md) | Reference | Consultar la arquitectura destino, matriz de puertos, contrato IPC, archivos afectados, fases |
| [How-to — Ejecutar el gate F0](howto-f0-gate.md) | How-to | Correr los 6 spikes GO/NO-GO en máquina real antes de comprometer la migración |
| [How-to — Migrar una vista QML → React](howto-migrate-view.md) | How-to | Portar una vista concreta detrás del Application Facade sin regresión |
| [How-to — Portar un puerto a Rust (PyO3)](howto-port-to-rust.md) | How-to | Mover un driven port a Rust con tests de paridad (Track R) |
| [Deuda técnica y buenas prácticas](tech-debt-and-best-practices.md) | Reference | Tecnologías (con estado de mantenimiento), buenas prácticas por área, registro de deuda técnica/footguns — de la investigación `/deep-research` |

**Decisiones técnicas (ADRs)** — registro en [`../editing/adr/`](../editing/adr/README.md):

| ADR | Decisión |
|-----|----------|
| [ADR-0008](../editing/adr/ADR-0008-tauri-ui-migration.md) | Migrar la UI a Tauri 2.0 + React (core Python como sidecar) |
| [ADR-0009](../editing/adr/ADR-0009-input-port-facade.md) | Puerto de entrada: Application Facade + Event Bus |
| [ADR-0010](../editing/adr/ADR-0010-role-conditional-topology.md) | Topología de proceso condicional por rol (daemon vs sidecar) |
| [ADR-0011](../editing/adr/ADR-0011-local-ipc-security.md) | Canal IPC local autenticado (named pipe/token + audit) |
| [ADR-0012](../editing/adr/ADR-0012-rust-hexagon-endgame.md) | Hexágono Rust vía PyO3 como destino (extiende ADR-0006) |

> **Tutoriales:** diferidos. Un tutorial requiere un artefacto que funcione para recorrer; se
> escribirán cuando el gate F0 entregue un shell Tauri ejecutable. Hasta entonces, el
> [how-to del gate F0](howto-f0-gate.md) es el punto de entrada accionable.

## El resumen en una pantalla

- **Qué:** reemplazar la capa `adapters/ui/` (29 QML + 6 bridges) por Tauri 2.0 (Rust shell) + React.
- **Por qué es viable:** `project/app/core/` **no importa Qt** — la costura está limpia; se cambia la
  UI, no el negocio. Ver [ADR-0008](../editing/adr/ADR-0008-tauri-ui-migration.md).
- **Cómo hablan UI y core:** un puerto de entrada nuevo `core/api` (Facade + DTOs + event bus); QML y
  el nuevo canal IPC son adaptadores intercambiables sobre él. Ver
  [ADR-0009](../editing/adr/ADR-0009-input-port-facade.md).
- **Always-on:** solo el rol Operador; daemon desacoplado vs sidecar según rol. Ver
  [ADR-0010](../editing/adr/ADR-0010-role-conditional-topology.md).
- **Destino:** hexágono Rust, port por port, detrás de los `core/ports/*` existentes. Ver
  [ADR-0012](../editing/adr/ADR-0012-rust-hexagon-endgame.md).
- **Riesgo #1:** HEVC puede no reproducirse en WebView2 → gate F0.

## Integración con graphify

Estos docs viven bajo la raíz del repo, así que el knowledge graph los indexa. Para refrescar el
grafo tras editar la documentación:

```bash
python -m graphify update .
```

> Nota operativa: el CLI `graphify` (`graphify.exe`) está roto en esta máquina
> (`ModuleNotFoundError`), pero `python -m graphify ...` sí funciona. Usa esa forma.
