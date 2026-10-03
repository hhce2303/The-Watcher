# AGENTS.md — the-watcher-daemon

Entry point for AI agents. Keep it short; details live in `docs/`.

- Purpose: Operator recording + LAN streaming daemon. Source of truth for these pieces (ADR-0001).
- Hard rule: **no import of editor, player, analytics, cloud, role, IPC, Qt or Tauri code**. `tests/test_import_purity.py`
  enforces it statically (all imports, including lazy ones) and by booting the daemon. Never weaken it to get green.
- Facade rule: if an adapter needs more from the app, add it to `DaemonApi` with its port (ADR-0002). Do not copy `ApiLayer`.
- Tests: `python -m pytest -q` (venv from `requirements-dev.txt`). TDD for behavior changes. Windows-only tests are listed in
  `tests/conftest.py::_WINDOWS_ONLY`; do not claim them passing from Linux.
- Decisions: one structural decision per ADR in `docs/architecture/adr/` (Spanish, template Estado/Fecha/Requisitos/
  Contexto/Decisión/Consecuencias/Opciones no elegidas). Records are append-only. New ADRs start at 0024.
- Commits: Conventional Commits. No secrets, no `.env`, no TLS material in git.
- Known defects are tracked in `docs/backlog/known-recording-issues.md`; unverified Windows items in `docs/pending-verification.md`.
- Conventions adopted from the monorepo's `CONTRIBUTING.md`: decision-first ADRs, stable IDs, append-only records, ask before
  cascading renames. Dropped: story/epic backlog tree, `TODOS.md`, `graphify`/gstack requirements (not set up here).
