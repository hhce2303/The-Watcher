# -*- mode: python ; coding: utf-8 -*-
#
# The Watcher — PyInstaller spec (Milestone 8)
#
# Build command (from project/ directory):
#   pyinstaller installer/The Watcher.spec
#
# Output: dist/The Watcher/  (one-dir bundle)

import os
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve FFmpeg binary to bundle
# ---------------------------------------------------------------------------
# A package-manager shim (Chocolatey's bin\ffmpeg.exe is ~50 KB and just forwards
# to ..\lib\ffmpeg\tools\ffmpeg\bin\ffmpeg.exe) is NOT bundleable: it dies with
# rc=-1 once the forwarded target is missing.  A real ffmpeg.exe is 50+ MB.
_MIN_REAL_FFMPEG_BYTES = 5 * 1024 * 1024


def _is_real_ffmpeg(path) -> bool:
    try:
        return Path(path).is_file() and Path(path).stat().st_size >= _MIN_REAL_FFMPEG_BYTES
    except OSError:
        return False


def _ffmpeg_candidates():
    on_path = shutil.which("ffmpeg")
    if on_path:
        yield on_path
    # Chocolatey: the real binary lives under lib/, PATH only has the shim.
    _choco = os.environ.get("ChocolateyInstall", r"C:\ProgramData\chocolatey")
    yield str(Path(_choco) / "lib" / "ffmpeg" / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe")
    # winget (Gyan.FFmpeg) — search without PATH
    _winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if _winget_base.exists():
        yield from (str(_f) for _f in _winget_base.glob("Gyan.FFmpeg*/**/ffmpeg.exe"))


_ffmpeg_exe = next((c for c in _ffmpeg_candidates() if _is_real_ffmpeg(c)), None)

if not _ffmpeg_exe:
    raise SystemExit(
        "ERROR: a real ffmpeg.exe (>= 5 MB, not a package-manager shim) was not found —\n"
        "  install FFmpeg before building:  winget install --id Gyan.FFmpeg\n"
        "  (Chocolatey: the real binary is under <choco>\\lib\\ffmpeg\\tools\\ffmpeg\\bin)"
    )

print(f"[spec] Bundling FFmpeg: {_ffmpeg_exe}")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(SPECPATH).parent)
_MAIN_SCRIPT  = str(Path(SPECPATH).parent / "app" / "main.py")
_ENV_EXAMPLE  = str(Path(SPECPATH).parent / ".env.example")

# ---------------------------------------------------------------------------
# Analysis
#
# QML/PySide6 are gone (F3) — this bundle is the headless daemon/sidecar only.
# The React/Tauri UI is a separate app that connects over the named pipe; see
# docs/migration/reference-target-architecture.md. Packaging that
# Tauri UI (and wiring this exe as its externalBin sidecar) is future work —
# scope was "dev + purge" for this migration pass.
# ---------------------------------------------------------------------------
a = Analysis(
    [_MAIN_SCRIPT],
    pathex=[_PROJECT_ROOT],
    binaries=[
        # Bundle ffmpeg.exe inside the 'bin/' sub-directory of the package.
        # ffmpeg_path.py checks sys._MEIPASS/bin/ffmpeg.exe in frozen mode.
        (_ffmpeg_exe, "bin"),
    ],
    datas=[
        # Ship .env.example so users can customise paths on first run
        (_ENV_EXAMPLE, "."),
    ],
    hiddenimports=[
        # screeninfo platform-specific enumerator (not auto-discovered)
        "screeninfo.enumerators.windows",
        # Native Rust segment engine (.pyd). Imported lazily inside
        # rust_segment_compiler._load_native(), so PyInstaller's static analysis
        # can't see it — declare it here so the .pyd is bundled when installed.
        # Harmless if absent from site-packages: PyInstaller just skips it and
        # the app uses the FFmpeg fallback.
        "watcher_segments",
        # ADR-0010/0011: the IPC + headless-runtime modules and pywin32
        # submodules are imported LAZILY inside main()'s daemon/sidecar setup
        # (the only path now — F3), so static analysis misses them. Declare
        # them so the daemon/sidecar work in the frozen build.
        "app.adapters.ipc.pipe_server",
        "app.adapters.ipc.pipe_client",
        "app.adapters.ipc.router",
        "app.runtime.headless",
        "win32pipe",
        "win32file",
        "win32security",
        "win32process",
        "winerror",
        "pywintypes",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test and dev tools — not needed at runtime
        "pytest",
        "pytest_timeout",
        "_pytest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="The Watcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # no console window — headless daemon/sidecar (tray lives in Tauri)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # Uncomment and add icon.ico to assets/ if desired
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="The Watcher",
)
