# Changelog

All notable changes to the daemon are documented here. The version lives in `VERSION` and
`app/__init__.py` (`__version__`; `installer/build.ps1` reads the latter and passes it to Inno Setup).

## [Unreleased]

### Added
- Repository extracted from the monorepo `The-Watcher` (`stream-display-stations` @ `ed5fd98`) with git history for the
  copied paths. See `docs/extraction.md` and ADR-0001.
- `app/daemon_root.py` composition root and `app/daemon_api.py::DaemonApi` (ADR-0002); CLI `start|stop|status|health`.
- Import-purity gate (`tests/test_import_purity.py`) and a pytest CI job (`.github/workflows/ci.yml`).

### Changed
- `installer/The Watcher.spec` builds from `app/daemon_root.py` and also emits `watcherctl.exe` (console CLI twin).
- Installer no longer writes `user_config.json` (roles/profiles do not exist here).
- `build-daemon.yml` runs from the repository root, runs the purity gate first, and triggers on `app/**` and `installer/**`.

### Removed
- Roles, IT PIN, IPC pipe, Tauri/Qt, event/ML pipeline and MJPEG preview server (ADR-0002, ADR-0003).
