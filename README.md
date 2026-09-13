# The Watcher

Always-on screen recorder with pre/post event capture, built for a Windows fleet
of Operator / IT / Supervisor roles. Python + FFmpeg headless backend (hexagonal
architecture) with a **Tauri 2.0 + React** desktop UI talking to it over an
authenticated named pipe.

The full product documentation — architecture, project structure, configuration,
build & install — lives in **[`project/README.md`](project/README.md)**.

## Quick links

- [**Onboarding**](ONBOARDING.md) — setup, dev mode, the 3 test suites, lint/CI, one path start to finish
- [Product README](project/README.md) — architecture, configuration, build & install
- [Migration docs](docs/migration/README.md) — QML/PySide6 → Tauri 2.0 + React,
  Python core → Rust hexagon (Track R)
- [Architecture decision records](docs/architecture/adr/README.md)
- [Glossary](docs/architecture/glossary.md) / [Non-functional requirements](docs/architecture/nfr.md)
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — decision governance, ADR template, ID conventions
- [`docs/backlog/`](docs/backlog/README.md) — feature intake: feedback → epic → story
- [`.env.example`](project/.env.example) — every supported environment variable
- [`TODOS.md`](TODOS.md) / [`CHANGELOG.md`](CHANGELOG.md) — current work and release history

## Start the complete development topology

From the repository root, use the root launcher:

```powershell
.\Start-TheWatcher.ps1
```

It starts the Python backend and the Tauri + React development shell. The persisted role selects
the backend topology automatically: Operator uses a detached daemon; IT, Supervisor and a
first-run machine use a sidecar that receives a graceful shutdown when the UI exits. Use
`-NoUi` for headless execution, `-BackendMode Daemon|Sidecar` to override selection temporarily,
or `-Bootstrap` to force a `uv` dependency repair. The launcher automatically creates or repairs
the missing Python 3.13 venv with `uv`. The production Tauri bundle does not yet embed
the backend (`externalBin` is intentionally empty), so this script is the complete local dev
launcher.

## Repository layout

```
project/    Python core + backend, tests, docs
src/        React UI (TypeScript, Vite)
src-tauri/  Tauri 2.0 Rust shell
scripts/    Dev tooling (DTO codegen, etc.)
```

For setup instructions (Python venv, Rust toolchain, `npm install`, running in dev
mode, and the three test suites), see **[`ONBOARDING.md`](ONBOARDING.md)**.
