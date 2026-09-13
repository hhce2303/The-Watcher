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
esto.** Docs completas: [`docs/migration/`](docs/migration/README.md) ·
ADRs 0008-0012 en [`docs/architecture/adr/`](docs/architecture/adr/README.md) ·
deuda técnica y buenas prácticas: [`docs/migration/tech-debt-and-best-practices.md`](docs/migration/tech-debt-and-best-practices.md).

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
| **F0** | GO/NO-GO **bloqueante**: 6 spikes en máquina real de operador | ✅ GO |
| **F1** | Backend headless: `core/api`, `adapters/ipc`, arranque por rol; QML sigue vivo | ✅ cerrada (pytest verde) |
| **F2** | UI React a paridad completa por rol (incluye editor); F2a-d + buffer | ✅ cerrada 2026-07-06 |
| **F3** | **Eliminación total de QML/PySide6** (`adapters/ui/` + `prototype/` borrados) + `run.ps1`/`run_dev.ps1` → Tauri | ✅ cerrada 2026-07-06 — packaging del instalador Tauri (`externalBin`) queda como fase posterior |
| **Track R** | Hexágono Rust port-por-port (PyO3), post-cutover | ✅ primer port live: motor de segmentos (`ENGINE_READY=true`) |

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

## react-hexagonal

Skill for React UI development in The Watcher: hexagonal boundary enforcement, component
design, performance optimization, and IPC adapter patterns. Skill file:
`.claude/skills/react-hexagonal/SKILL.md`.

Rules:
- When working on any file under `src/` (tabs, hooks, types, components), load this skill
  before writing or reviewing code.
- Before creating a component or hook: evaluate flags `HEX_BOUNDARY_CLEAN`,
  `COMPONENT_SIZE_OK`, `IPC_ADAPTER_ISOLATED`, and `TYPES_DEFINED`. All must be true before
  proceeding. A false flag is a gate — resolve it first.
- Before adding IPC communication: run CP-2 checklist (DTO type defined, hook isolation,
  backend facade method exists).
- Before applying memoization (`React.memo`, `useCallback`, `useMemo`): run CP-3 checklist.
  Never memoize speculatively — measure first.
- When the user types `/react-hexagonal`, load the skill before doing anything else.
