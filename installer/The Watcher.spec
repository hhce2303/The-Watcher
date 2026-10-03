# -*- mode: python ; coding: utf-8 -*-
#
# The Watcher daemon - PyInstaller spec (recording + LAN live view)
#
# Build command (from the repository root):
#   pyinstaller --noconfirm installer/"The Watcher.spec"
#
# Output: dist/The Watcher/  (one-dir bundle)
#   The Watcher.exe   windowed daemon (scheduled task / installer launch it)
#   watcherctl.exe    console build of the same entry point for the CLI:
#                     watcherctl stop|status|health   (the windowed exe has no stdout)
#
# The exe keeps the name "The Watcher" so existing installs (scheduled task,
# Update-Watcher.ps1, certs deployment scripts) keep working unchanged.

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
_MAIN_SCRIPT  = str(Path(SPECPATH).parent / "app" / "daemon_root.py")
_ENV_EXAMPLE  = str(Path(SPECPATH).parent / ".env.example")

# ---------------------------------------------------------------------------
# Analysis
#
# This bundle is the headless daemon only: no Qt, no Tauri, no IPC pipe, no
# pywin32 (nothing under app/ imports it - see tests/test_import_purity.py).
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
        # Imported lazily inside functions; declared so a frozen build never
        # depends on PyInstaller's static analysis catching them.
        "app.runtime.headless",
        "app.runtime.instance",
        "app.adapters.live_view_lan",
        "app.adapters.tls_provisioning",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Test and dev tools — not needed at runtime
        "pytest",
        "pytest_timeout",
        "_pytest",
        # Must never ship (import-purity gate): UI toolkits and ML stacks.
        "PySide6", "PyQt5", "PyQt6", "tkinter", "numpy", "onnxruntime", "PIL",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

_exe_common = dict(
    exclude_binaries=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon="assets/icon.ico",  # Uncomment and add icon.ico to assets/ if desired
)

# Windowed daemon: no console window on the operator's screen.
exe = EXE(pyz, a.scripts, [], name="The Watcher", console=False, **_exe_common)
# Console twin for the CLI (stdout is visible): watcherctl status / health / stop.
ctl = EXE(pyz, a.scripts, [], name="watcherctl", console=True, **_exe_common)

coll = COLLECT(
    exe,
    ctl,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="The Watcher",
)
