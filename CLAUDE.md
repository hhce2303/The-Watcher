## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- NOTE: the `graphify.exe` launcher is broken on this machine (`ModuleNotFoundError`). Use `python -m graphify <cmd>` instead (e.g. `python -m graphify update .`). Subcommands available: `update`, `explain`, `path`, `diagnose` (`query` may not exist in this build).

## Tauri Migration — contexto permanente (leer para TODO trabajo de UI / arquitectura / iteración)

The Watcher migra la UI de **PySide6/QML → Tauri 2.0 (Rust) + React**, con el **core Python como
sidecar ahora** y destino **hexágono Rust vía PyO3** (port por port). Roadmap aprobado (2026-06-30),
revisado por ingeniería. **Antes de proponer o iterar cualquier cosa de UI/arquitectura, ten presente
esto.** Docs completas: [`project/docs/migration/`](project/docs/migration/README.md) ·
ADRs 0008-0012 en [`project/docs/editing/adr/`](project/docs/editing/adr/README.md) ·
deuda técnica y buenas prácticas: [`project/docs/migration/tech-debt-and-best-practices.md`](project/docs/migration/tech-debt-and-best-practices.md).

**No negociables (decisiones ya tomadas):**
- La costura está limpia: `app/core/` NO importa Qt. Migrar = reemplazar `adapters/ui/`, no el negocio.
- Puerto de entrada nuevo `core/api` (Facade + DTOs Pydantic + event bus thread-safe). QML y el nuevo
  canal IPC son adaptadores intercambiables sobre él (ADR-0009). El Facade llama a *ports*, nunca a adapters concretos.
- IPC local **autenticado** (named pipe / token build-time + audit), NUNCA TCP loopback abierto (ADR-0011).
- Topología condicional por rol: Operador = daemon always-on desacoplado (watchdog); IT/Supervisor =
  sidecar que muere con la app (ADR-0010).
- QML + PySide6 se **eliminan por completo** en F3. Pruebas visuales/build reutilizan `run.ps1` / `installer/build.ps1` (evolucionados, no paralelos).
- Destino Rust comprometido (postura A), pero Track R **no arranca** sin toolchain Rust + spike de paridad + owner (riesgo F7).

**Roadmap por fases (orden estricto):**
| Fase | Qué | Gate/nota |
|------|-----|-----------|
| **F0** | GO/NO-GO **bloqueante**: 6 spikes en máquina real de operador | Sin GO no hay F1 |
| **F1** | Backend headless: `core/api`, `adapters/ipc`, arranque por rol; QML sigue vivo | pytest verde |
| **F2** | UI React a paridad, vista por vista (editor = 40-60%, al final); F2a-d + buffer | por vista |
| **F3** | Cutover por cohorte + **eliminación total de QML/PySide6** + packaging Tauri | rollback def. |
| **Track R** | Hexágono Rust port-por-port (PyO3), post-cutover | flag `ENGINE_READY` |

**Tecnologías + buenas prácticas (cheat-sheet; detalle en el doc de deuda técnica):**
- **HEVC en WebView2 es HW-dependiente, sin fallback SW** (ruta Edge/MFT) → editor/player pueden romper en la flota → **transcode a H.264** (TD-1). Es el bloqueador #1 del gate F0.
- **Scrub frame-exact NO desde `<video>`** (`currentTime` es tiempo, no frame) → frames server-side o WebCodecs; el export ya es server-side (TD-7).
- **Preview en vivo: NO uses la invoke JSON de Tauri** (serializa a strings) → WS binario (~100ms) / custom protocol / MJPEG (TD-5). SLA F0: ≤1s, ≤5% CPU/monitor.
- **Sidecar: `process.kill()` no mata el PyInstaller one-file** → shutdown por stdin/stdout (TD-3). `externalBin` requiere sufijo `-<target-triple>` (TD-6).
- **Rust:** semillas = `windows-capture` (Rust+Python, WGC/DXGI) para `RecorderPort`; `shiguredo_mp4` (Sans-I/O, HEVC) para `ClipPort`. Footgun: `ffmpeg-next` en modo mantenimiento (TD-4).
- **Tauri prod:** capabilities default-deny; updater con firma minisign obligatoria; IPC tipado con `tauri-specta`/`TauRPC`; CI con `tauri-action` (MSI/NSIS).

## gstack (REQUIRED — global install)

**Before doing ANY work, verify gstack is installed:**

```bash
test -d ~/.claude/skills/gstack/bin && echo "GSTACK_OK" || echo "GSTACK_MISSING"
```

If GSTACK_MISSING: STOP. Do not proceed. Tell the user:

> gstack is required for all AI-assisted work in this repo.
> Install it:
> ```bash
> git clone --depth 1 https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
> cd ~/.claude/skills/gstack && ./setup --team
> ```
> Then restart your AI coding tool.

Do not skip skills, ignore gstack errors, or work around missing gstack.

Using gstack skills: After install, skills like /qa, /ship, /review, /investigate,
and /browse are available. Use /browse for all web browsing.
Use ~/.claude/skills/gstack/... for gstack file paths (the global path).
