# Extraction from the monorepo — provenance, scope and deviations

Implements `docs/superpowers/specs/2026-10-03-daemon-extraction-design.md` of the monorepo
(`The-Watcher`, branch `stream-display-stations`, commit `ed5fd98`). That monorepo worktree was read-only during the
extraction: nothing in it was modified, committed or deleted.

## How the history was copied

1. `git filter-repo` is **not installed** on the extraction machine and no global tool was installed.
2. Documented fallback: fresh `git clone --no-local` of the monorepo into a scratch directory (origin removed), then
   `git filter-branch --prune-empty --index-filter` with an explicit allow-list of paths (a small script that removes
   every index entry not in the list). 83 monorepo commits became 51 commits touching the kept paths.
3. The filtered history was fetched into this repo (`main`), then a single pure-move commit relocated `project/*` to
   the repository root (git follows the renames: `git log --follow app/adapters/live_view_lan/server.py`).
4. Caveats: path filtering does not follow renames that happened *before* the kept paths existed (e.g. the earlier
   `docs/editing -> docs/architecture` move), and filter-branch is deprecated upstream; for a re-run prefer `git filter-repo`
   (`sudo pacman -S git-filter-repo` on Arch). Commit hashes differ from the monorepo's.

## What was copied (repo-root layout, was `project/…` in the monorepo)

| Area | Paths |
|---|---|
| Recording core | `app/core/recording_service/`, `recording_health/`, `disk_monitor.py`, `monitor_detection/` |
| Ports (8 of 24) | `clip_port`, `monitor_port`, `recorder_port`, `segment_compiler_port`, `storage_port`, `timestamp_port`, `live_view_port`, `tls_material_port` |
| ffmpeg adapters (11 files) | `recorder_adapter`, `trim_adapter`, `timestamp_adapter`, `hourly_recording_builder`, `combined_clip_builder`, `builder_process_mixin`, `clip_window`, `process_guard`, `encoder_selector`, `ffmpeg_path`, `segment_compiler_adapter` |
| Other adapters | `adapters/native/`, `adapters/monitor/screeninfo_adapter.py`, `adapters/filesystem/storage_adapter.py`, `adapters/live_view_lan/`, `adapters/tls_provisioning/`, `adapters/browser_local/{auth,identity}.py` |
| Operation | `app/infrastructure/` (config, logging_setup, proc_telemetry, autostart, scheduled_task, relaunch, launch_target) |
| Native | `native/watcher_segments/` |
| Delivery | `installer/` (`.spec`, `.iss`, `build.ps1`, `install.ps1`, `Setup.bat`, `Update-Watcher.ps1`), `.github/workflows/build-daemon.yml`, `.env.example`, `requirements.txt` |
| Docs | ADR 0006, 0007, 0013–0017, 0019, 0021–0023; `docs/architecture/tls-provisioning-contract.md`; `docs/migration/ffmpeg-pipeline-optimization-research.md` |
| Tests (28 test files carried) | recording core, ffmpeg/native/monitor/infra, live view, TLS — see `git log --stat` of the import; rewritten: `test_logging_setup.py`; `test_launch_target`, `test_relaunch`, `test_scheduled_task` only changed `app.main` → `app.daemon_root` |

## What was written new

`app/daemon_root.py`, `app/daemon_api.py`, `app/runtime/headless.py` (rewritten, no IPC), `app/runtime/instance.py`,
empty `app/adapters/browser_local/__init__.py`, `tests/test_daemon_api.py`, `test_daemon_root.py`,
`test_headless_runtime.py`, `test_instance.py`, `test_import_purity.py`, `.github/workflows/ci.yml`, ADRs 0001–0003,
`pytest.ini`, `requirements-dev.txt`, this documentation set.

## Excluded (and why)

- Not in the spec's "no entra": `core/api`, `ipc/`, `ws/`, editor, player, analytics, `cloud_share_service`,
  `browser_local/server.py`, `role.py`/`policy.py`, `src/`, `src-tauri/`, Qt/QML.
- Decided here with evidence: `auto_event_service` and `preview_server` (ADR-0003), `native/watcher_h264_encoder`
  (editor-export spike, ADR-0003), `infrastructure/clip_migration.py` (event-clip migration used only by `main.py`),
  `adapters/storage/` (sqlite analytics/event store), `core/ports` of editor/player/analytics/audit/user-config,
  `adapters/ffmpeg/{clip_inspector,editor_export,mp4_converter,preview,live_preview}`, `runtime/mode.py`.
- Tests not carried (mixed or for excluded code): `test_backend_builder` (targets `runtime/backend.py`, superseded by
  `test_daemon_root`), `test_runtime_headless` (IPC pipe; superseded by `test_headless_runtime`), `test_parity_*`
  (use `clip_inspector_adapter`/`core.player`), `test_f3_batch`, `test_f4_realtime`, `test_audit_store`,
  `test_preview_server`, `test_auto_event_service`, all IPC/facade/editor/cloud/role tests.

## Deviations from the spec (all evidence-based)

| Spec says | Reality / what was done |
|---|---|
| `browser_local/{auth,identity}.py` only | The package `__init__.py` imports `server.py` → `core.api` → editor/player/role. Replaced by an empty `__init__.py`. |
| `adapters/storage/` | That is the sqlite analytics adapter (imports `core/analytics`). The recording stack needs `adapters/filesystem/storage_adapter.py`. |
| `runtime/headless.py` enters | Coupled to `ApiLayer` + named-pipe server; rewritten, only the signal/teardown logic survives. |
| `adapters/ffmpeg/` and ports as directories | Whole directories pull editor/player/analytics; only the closure files were kept. |
| `native/watcher_h264_encoder` enters | It is an editor-export spike; nothing imports it. Excluded. |
| `logging_setup` as-is | Lazily imported `core.api.dto` for an event-bus log sink; the sink was removed. |
| Installer as-is | Entry script, hidden imports (IPC, pywin32), `user_config.json` writer and version source changed. |
| `config.py` as-is | Unused monorepo settings removed (IT PIN, request system, NAS, OneDrive, ONNX, tracker, preview HTTP, events flags). |

## Import closure

`app/` has 65 Python files. The static check in `tests/test_import_purity.py` walks every import statement at any depth
(including `# noqa: PLC0415` lazy imports and `import_module("literal")`), and a dynamic check boots the real headless
startup in a clean interpreter and inspects `sys.modules`.
