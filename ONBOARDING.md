# Onboarding — The Watcher

One path from a fresh clone to a running dev build and green test suites.
Windows only — the whole stack (`pywin32`, DXGI/ddagrab capture, WebView2 HEVC
playback) is Windows-specific by design.

## 1. Prerequisites

- **Windows 10/11.**
- **uv** — [astral.sh/uv](https://docs.astral.sh/uv/). It installs/selects Python 3.13 for the
  project and synchronizes the venv, so a global `python` on `PATH` is not required.
- **Node.js 22+** and npm — confirm with `node --version`.
- **FFmpeg** on `PATH` — `winget install Gyan.FFmpeg`.
- **Rust (optional but recommended)** — [rustup.rs](https://rustup.rs), MSVC toolchain.
  Needed to build the Tauri dev shell (`npm run tauri -- dev`) and the optional
  native clip engine; without it, `setup_env.ps1` still works and clip assembly
  falls back to FFmpeg (`ENGINE_READY` gate — nothing breaks, it's just slower).

## 2. First-time setup

From the repo root:

```powershell
.\setup_env.ps1
```

This uses `uv` to install/select Python 3.13 and creates a venv at
`%LOCALAPPDATA%\The Watcher\venv` (deliberately *outside* the repo/OneDrive — a
venv is machine-specific and must not sync between PCs). It synchronizes
`project/requirements.txt` and — only if Rust is available — compiles the
optional native clip engine. Safe to re-run; it detects and repairs a broken
venv. If `uv` is missing, install it with `winget install --id=astral-sh.uv -e`.

Then install the frontend dependencies:

```powershell
npm install
```

## 3. Running in dev mode

```powershell
.\project\run.ps1
```

Starts the Python backend (role-aware: `--daemon` for Operator, `--sidecar`
otherwise, per `user_config.json`) and the Tauri dev shell together; `Ctrl+C`
stops both. First run with no role configured shows the role-selection wizard.

Useful variants:

```powershell
.\project\run.ps1 -Mode daemon      # headless Operator daemon only, no UI
.\project\run.ps1 -Mode sidecar     # headless IT/Supervisor sidecar only, no UI
.\project\run.ps1 -ResetRole        # wipe the persisted role, wizard reappears
.\project\run_dev.ps1               # same idea, always --sidecar, quickest loop
```

## 4. Running the test suites

Three independent suites — none require the others to pass first.

**Python (pytest)**, from the repo root:

```powershell
$env:PYTHONPATH = "project"
$twPython = Join-Path $env:LOCALAPPDATA "The Watcher\venv\Scripts\python.exe"
& $twPython -m pytest project/tests -q
```

**Frontend (vitest)**:

```powershell
npm run test
```

**Rust (cargo test)**:

```powershell
cd src-tauri
cargo test
```

Scope note on the Rust suite: `commands.rs`/`tray.rs`/`policy.rs`'s
Tauri-`AppHandle`-dependent code isn't covered — `tauri::test::mock_app()`
crashes on this toolchain (`STATUS_ENTRYPOINT_NOT_FOUND`, tracked in
`TODOS.md` item 6, not being chased). What's covered: `ipc.rs`/
`media_protocol.rs`'s pure protocol logic, and `policy.rs`'s `AppPolicy`
(no `AppHandle` dependency).

## 5. Linting, types, and the DTO sync check

```powershell
npm run lint                              # ESLint (+ eslint-plugin-jsx-a11y)
npx tsc --noEmit -p tsconfig.json         # type-check, no build output
npm run gen:dto:check                     # dto.py vs dto.gen.ts drift check
```

`src/types/dto.ts` is the hand-maintained TypeScript mirror of
`project/app/core/api/dto.py` — the file app code actually imports.
`src/types/dto.gen.ts` is a *generated* snapshot that `gen:dto:check` diffs
against on every CI run; it catches drift between the two but is never
imported by app code itself. After adding/changing a DTO in `dto.py`, mirror
the shape by hand in `dto.ts`, then run the check locally before pushing.

All of the above (pytest, vitest, cargo test, lint, type-check, DTO check)
run automatically in CI — see `.github/workflows/ci.yml`.

## 6. Where to go next

- [`project/README.md`](project/README.md) — architecture, project structure,
  configuration reference, build & install.
- [`docs/migration/README.md`](docs/migration/README.md) —
  the QML/PySide6 → Tauri + React migration and the Rust hexagon roadmap.
- [`docs/architecture/adr/README.md`](docs/architecture/adr/README.md) —
  architecture decision records.
- [`TODOS.md`](TODOS.md) — deferred follow-ups and known gaps, with why they
  were deferred and what would trigger picking them back up.
- [`CHANGELOG.md`](CHANGELOG.md) — release history.
