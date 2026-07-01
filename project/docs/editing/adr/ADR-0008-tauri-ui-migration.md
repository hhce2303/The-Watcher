# ADR-0008 — Migrar la UI a Tauri 2.0 + React (core Python como sidecar)

- **Estado**: Aceptado (roadmap; implementación condicionada al gate F0)
- **Fecha**: 2026-06-30
- **Origen**: revisión `/office-hours` → `/plan-eng-review` (cross-model)
- **Docs**: [migración/](../../migration/README.md) · [explicación](../../migration/explanation-tauri-migration.md)

## Contexto

La UI es PySide6/QML: 29 archivos `.qml` (~10 K LOC) + 6 bridges Python (~2.1 K LOC) en
[`app/adapters/ui/`](../../../app/adapters/ui). El bundle PyInstaller pesa ~259 MB (Qt domina).
Tres necesidades no las cubre: **tamaño/memoria**, **UI reusable para panel IT remoto / móvil**, y
**velocidad de iteración de UI**. QML no se sirve a un navegador ni tiene target móvil.

Hallazgo habilitante (verificado): `app/core/` **no importa Qt** (`grep -rE
"QObject|Signal|Slot|Property|Qml" app/core` → vacío). Qt solo vive en `adapters/ui/*`, en
`adapters/ws/*` (solo el argumento `parent`) y en [`app/main.py`](../../../app/main.py) (bootstrap
Qt). La costura está limpia.

## Decisión

- Reemplazar la capa `adapters/ui/` por **Tauri 2.0 (shell Rust) + React**. El core y los demás
  adapters (`ffmpeg`/`filesystem`/`cloud`/`storage`/`monitor`/`native`) quedan **intactos**.
- **Ahora:** el core Python corre como **sidecar** empaquetado (PyInstaller `externalBin`); el
  frontend habla con él por un canal IPC local (ver [ADR-0011](ADR-0011-local-ipc-security.md)).
- **QML + PySide6 se eliminan por completo** en el cutover (F3): 0 `.qml`, 0 imports de PySide6, sin
  `PySide6*` en `requirements.txt`. La coexistencia QML↔nuevo backend es transitoria (F1-F2). No hay
  híbrido permanente.
- **Reutilizar** los scripts existentes [`run.ps1`](../../../run.ps1) (pruebas visuales) y
  [`installer/build.ps1`](../../../installer/build.ps1) (empaquetado), evolucionados — no scripts
  paralelos.
- **Gate F0 bloqueante** antes de comprometer F1+: HEVC en WebView2, latencia de preview, scrub
  frame-exact, seguridad IPC, WebView2 ausente, ciclo daemon/sidecar. Ver
  [how-to F0](../../migration/howto-f0-gate.md).

## Consecuencias

- ✅ Se preserva ~15 K LOC de core/adapters probados; solo se reescribe la UI (~12 K LOC).
- ✅ Desbloquea bundle menor, panel IT remoto en navegador (mismo React), target móvil futuro, HMR y
  plugins always-on (`tray`/`autostart`/`single-instance`) + `updater`.
- ➖ Reescritura de UI real (semanas sin ganancia funcional visible) y lenguaje+IPC nuevos en la ruta
  crítica de una herramienta de evidencia.
- ➖ **HEVC en WebView2** (los clips son HEVC) puede no reproducir → posible transcode a H.264 (gate F0).
- ➖ Dependencia de **WebView2** en máquinas de flota (+ auto-updates de Microsoft) — validar en F0.
- ➖ Reconstrucción de tests: `qml_smoke` y tests de bridges Qt → smoke Tauri + tests de contrato IPC.
- Relacionado: [ADR-0009](ADR-0009-input-port-facade.md), [ADR-0010](ADR-0010-role-conditional-topology.md), [ADR-0012](ADR-0012-rust-hexagon-endgame.md).

## Evidencia externa (investigación 2026-07)

Corrobora la decisión y afila el gate F0 (detalle + fuentes en
[tech-debt-and-best-practices](../../migration/tech-debt-and-best-practices.md)):
- **HEVC en WebView2 es HW-dependiente y sin fallback por software** (WebView2 usa la ruta de Edge/MFT,
  que requiere la HEVC Video Extension del SO + hardware). Confirma TD-1: transcode a H.264 en el plan.
- **Sidecar oficial:** `externalBin` con sufijo `-<target-triple>` obligatorio (TD-6). El ejemplo de
  referencia expone TCP+CORS abierto → inseguro (ver [ADR-0011](ADR-0011-local-ipc-security.md)).
- **Updater** con firma minisign obligatoria; **CI** con `tauri-action` (matriz OS → MSI/NSIS).
