# Explicación — Por qué migrar la UI a Tauri 2.0

Este documento explica **por qué** The Watcher migra su UI de PySide6/QML a Tauri 2.0 + React,
qué problema resuelve, qué se entrega a cambio, y hacia dónde escala. No describe *cómo* hacerlo
(eso está en los [how-tos](README.md)) ni el detalle técnico (eso está en la
[referencia](reference-target-architecture.md)).

## El problema

The Watcher es un grabador de pantalla **always-on** para flotas de operadores gestionadas por IT,
con roles Operador / IT / Supervisor. Hoy la UI es **PySide6/QML**:

- **29 archivos QML (~10 K LOC)** + **6 bridges Python (~2.1 K LOC)** en `project/app/adapters/ui/`.
- Empaquetado PyInstaller → bundle **~259 MB** (el motor Qt pesa la mayor parte).

El stack funciona, pero tres necesidades del negocio no las cubre bien:

1. **Tamaño / memoria.** Empacar Qt infla el bundle a ~259 MB. En una flota grande eso es disco,
   descarga y RAM por estación.
2. **Alcance remoto / móvil.** No hay forma de dar a IT un panel de revisión de clips en el
   navegador ni una app móvil companion: QML no se sirve a un browser.
3. **Velocidad de iteración de UI.** Iterar la interfaz en QML es más lento que en web (menos
   herramientas de diseño, menos reuso de componentes, sin HMR de navegador).

Si el único objetivo fuera el #3, existe un camino más barato (mejorar tooling QML + el pipeline de
diseño Pencil que ya existe). Lo que **justifica** una migración de framework es la combinación de
**#1 + #2**: QML simplemente no te da un panel web ni un target móvil.

## El hallazgo que lo hace viable — la costura limpia

La arquitectura hexagonal de The Watcher está bien hecha. Verificado en código:

```bash
# 0 coincidencias — el core no conoce Qt:
grep -rE "QObject|Signal|Slot|Property|Qml" project/app/core   # → (vacío)
```

Qt/PySide6 vive **solo** en:

- `project/app/adapters/ui/*` → la capa que se reemplaza (objetivo de la migración).
- `project/app/adapters/ws/{request_server,request_client}.py` → solo usan `QObject` por el
  argumento `parent`; limpieza menor.
- `project/app/main.py` → bootstrap de `QApplication`/`QQmlApplicationEngine`.

**Consecuencia:** migrar a Tauri = **reemplazar la capa UI (`adapters/ui/`)**, no reescribir el
negocio. El motor de grabación, clips, editor, OneDrive, watchdog y roles (`core/` + los otros
`adapters/`) quedan intactos. Ver [ADR-0008](../editing/adr/ADR-0008-tauri-ui-migration.md).

## La forma de la transición

```
   HOY                        TRANSICIÓN (F1-F2)                  DESTINO (Track R)
   ┌─────────┐                ┌─────────┐  ┌─────────┐            ┌───────────────────┐
   │ QML/Qt  │                │  QML    │  │  React  │            │  React (Tauri)    │
   │ bridges │      ──►       │ (fino)  │  │ (Tauri) │    ──►     │  comandos nativos │
   └────┬────┘                └────┬────┘  └────┬────┘            └─────────┬─────────┘
        │ llamada directa          └─────┬──────┘                           │
        ▼ (Qt mezclado)                  ▼ mismo Facade                     ▼ traits Rust
   ┌─────────┐                ┌──────────────────┐                ┌───────────────────┐
   │ servicios│               │ core/api (Facade)│                │ core en Rust      │
   │  + core  │               │  + servicios     │                │  + adapters Rust  │
   └─────────┘                └──────────────────┘                └───────────────────┘
   Python (Qt en UI)          Python sidecar + UI React           Binario único (sin Python)
```

Tres ideas sostienen la transición:

1. **Un puerto de entrada nuevo (`core/api`).** Hoy los bridges QML llaman a los servicios
   directamente y mezclan Qt con orquestación. Se introduce el puerto de entrada que falta: un
   Application Facade + DTOs + un event bus que reemplaza las Qt Signals. QML y el nuevo canal IPC se
   vuelven **adaptadores de entrada intercambiables** sobre el mismo facade — por eso pueden coexistir
   sin duplicar lógica durante la transición. Ver
   [ADR-0009](../editing/adr/ADR-0009-input-port-facade.md).

2. **Topología de proceso condicional por rol.** El always-on es **solo del Operador**. El grabador
   del Operador corre como daemon desacoplado (gestionado por el scheduled-task watchdog existente),
   de modo que cerrar la UI no detiene la grabación. Para IT/Supervisor el backend es un sidecar que
   vive y muere con la app (sin daemon huérfano consumiendo recursos). Ver
   [ADR-0010](../editing/adr/ADR-0010-role-conditional-topology.md).

3. **Rust como destino, no como shell.** El core es el destino de Rust. Los `core/ports/*` son la
   costura por la que Rust entra, port por port vía PyO3, empezando por lo más crítico
   (grabación/segmentos). Ver [ADR-0012](../editing/adr/ADR-0012-rust-hexagon-endgame.md).

## Escalabilidad hacia mejores features de Tauri

La migración no es solo paridad: abre features que QML no da.

| Motivación | Qué desbloquea Tauri | Cuándo |
|------------|----------------------|--------|
| Tamaño/memoria | WebView2 reemplaza el motor QML; al colapsar el sidecar en Rust se elimina Python → binario de MB | Fase 3 (parcial), Track R (total) |
| Remoto/web | El mismo bundle React se sirve a un navegador desde el canal local → panel IT remoto sin reescribir UI | Tras Fase 2 |
| Móvil | Targets iOS/Android de Tauri 2.0 para una app companion (requiere lógica portable → Rust) | Track R+ |
| Velocidad UI | HMR, DevTools del navegador, reuso de componentes, pipeline Pencil | Desde Fase 2 |
| Operación | `updater` (auto-update vs PyInstaller manual), `notification`, `global-shortcut`, capabilities | Fase 3+ |
| Always-on | Plugins oficiales `single-instance` / `autostart` / `tray` mapean directo a lo que hoy se resuelve a mano | Fase 2 |

## Trade-offs (lo que se entrega a cambio)

Ninguna decisión es gratis. Lo que cuesta esta migración:

- **Reescritura de UI real** (~10 K LOC QML + 2.1 K de bridges), semanas sin ganancia funcional
  visible durante el proceso.
- **Lenguaje + IPC nuevos en la ruta crítica** de una app de la que depende evidencia grabada.
- **Compromiso multi-trimestre con Rust** (Track R) sobre un equipo hoy Python/Qt.
- **Piezas duras en web:** reproducción **HEVC en WebView2** (los clips son HEVC), preview en vivo
  multi-monitor, y scrub frame-exact.
- **Regresión de seguridad del IPC** si no se endurece (ver
  [ADR-0011](../editing/adr/ADR-0011-local-ipc-security.md)).
- **Dependencia de WebView2** en máquinas de flota que no controlas (+ auto-updates de Microsoft).

## Por qué se hace con red de seguridad — el gate F0

La revisión de ingeniería (`/plan-eng-review`, cross-model) encontró **3 bloqueadores TIER-1** que el
plan original no resolvía: HEVC en WebView2, latencia de preview, y scrub frame-exact. La respuesta no
es "confiar y empezar", sino un **gate F0 GO/NO-GO bloqueante**: probar esas tres piezas (más
seguridad IPC, WebView2 ausente y ciclo de vida daemon/sidecar) en una **máquina real de operador**
con criterios numéricos, **antes** de comprometer 6-10 semanas de reescritura. Si fallan, se reevalúa
la estrategia (transcode a H.264, frames server-side) o se aborta. Ver
[how-to F0](howto-f0-gate.md).

## Alternativas consideradas (y por qué no)

- **Quedarse en QML + trimear el bundle** (PyInstaller excludes / Nuitka): resuelve #1 parcialmente,
  no #2 (remoto/móvil). Descartada como solución completa, útil como comparación de esfuerzo.
- **PyTauri (bindings Pyo3, app Tauri en Python):** evita el segundo proceso pero es más nuevo y con
  asperezas (detección de libpython); menos battle-tested para un always-on. Descartada a favor del
  sidecar Python maduro ahora + Rust después.
- **Reescribir el core en Rust de una** (big-bang): descarta ~15 K LOC probadas y es multi-trimestre
  antes de entregar valor. Descartada; Rust entra incremental (Track R).

## Relacionado
- [Referencia — Arquitectura objetivo](reference-target-architecture.md)
- [ADR-0008](../editing/adr/ADR-0008-tauri-ui-migration.md) · [ADR-0012](../editing/adr/ADR-0012-rust-hexagon-endgame.md) · [ADR-0006 (motor de segmentos Rust)](../editing/adr/ADR-0006-rust-segment-engine.md)
