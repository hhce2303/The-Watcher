# Pending verification (not provable on Linux)

The extraction was done and tested on Linux (Python 3.14.7 locally; CI targets 3.13). Everything below is **unverified**
and must be checked on `watcher-win` (Windows Operator test PC) or in Windows CI before any release.

| # | Check | Why it could not be verified here |
|---|---|---|
| V-1 | `pyinstaller installer/"The Watcher.spec"` builds, producing `The Watcher.exe` **and** `watcherctl.exe` in one `dist/The Watcher/`. | Windows-only; the two-`EXE` COLLECT is untested. |
| V-2 | The frozen daemon starts, `watcherctl status`, `health` and `stop` work against it (state files under `C:\WatcherData`). | Needs the bundle. `console=False` hides stdout of the windowed exe. |
| V-3 | Recording works: ddagrab/zero-copy capture, segments, hourly + combined clips, hot-plug. | ffmpeg `ddagrab` is Windows-only (ADR-0013/0014). |
| V-4 | LAN live view: `/api/v1/health`, `/api/v1/monitors`, H.264 stream over WebSocket with the TLS bundle from `the-watcher-certs`. | Needs TLS material and a Windows ffmpeg. |
| V-5 | Scheduled-Task watchdog registers with `--daemon` and restarts after a kill; benign second instance exits 0. | `schtasks`; the lock is now a file lock (`msvcrt.locking`) instead of the monorepo's named mutex. |
| V-6 | The 14 tests skipped on Linux (`tests/conftest.py::_WINDOWS_ONLY`, `subprocess.CREATE_NO_WINDOW`) plus the Job Object tests pass on Windows. | Windows-only code paths. |
| V-7 | `.github/workflows/ci.yml` and `build-daemon.yml` run green. | Not executed remotely (no remote exists). Only YAML syntax was parsed locally. |
| V-8 | Real recording boot (`start_recording=True`) imports nothing forbidden. | The purity test boots with `start_recording=False` to avoid spawning ffmpeg; the recording path is covered statically. |
| V-9 | `installer/build.ps1` and `The Watcher.iss` (`/DAppVersion`, removed profile writer) and `the-watcher-certs` scripts (`New-OperatorTestDeployment.ps1 -BuildScript` expects the monorepo layout `project\installer\build.ps1`). | PowerShell/Inno Setup, not run. |
| V-10 | Port consistency: firewall rule 8767 vs `LIVE_VIEW_PORT` 8766 (backlog B-16). | Needs the deployed station. |
