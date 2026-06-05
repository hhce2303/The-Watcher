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
_ffmpeg_exe = shutil.which("ffmpeg")

if not _ffmpeg_exe:
    # winget (Gyan.FFmpeg) — search without PATH
    _winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if _winget_base.exists():
        for _f in _winget_base.glob("Gyan.FFmpeg*/**/ffmpeg.exe"):
            _ffmpeg_exe = str(_f)
            break

if not _ffmpeg_exe:
    raise SystemExit(
        "ERROR: ffmpeg.exe not found — install FFmpeg before building:\n"
        "  winget install --id Gyan.FFmpeg"
    )

print(f"[spec] Bundling FFmpeg: {_ffmpeg_exe}")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(SPECPATH).parent)
_MAIN_SCRIPT  = str(Path(SPECPATH).parent / "app" / "main.py")
_ENV_EXAMPLE  = str(Path(SPECPATH).parent / ".env.example")

# ---------------------------------------------------------------------------
# Collect the app's own QML files (Main.qml + qml/ tree + qmldir module files).
# main.py loads them from Path(__file__).parent/"adapters"/"ui". PyInstaller
# places the entry script (app/main.py) at the bundle ROOT as main.py, so in a
# frozen build __file__ is <bundle>/main.py and ui_dir resolves to
# <bundle>/adapters/ui (NOT <bundle>/app/adapters/ui). The dest path is made
# relative to app/ to drop the leading "app" and match that layout.
# Without this the engine fails to load Main.qml -> "QML failed to load" -> exit.
# ---------------------------------------------------------------------------
_app_path = Path(SPECPATH).parent / "app"
_ui_datas = []
for _f in (_app_path / "adapters" / "ui").rglob("*"):
    if _f.is_file() and (_f.suffix == ".qml" or _f.name == "qmldir"):
        _ui_datas.append((str(_f), str(_f.parent.relative_to(_app_path))))
print(f"[spec] Bundling {len(_ui_datas)} QML/qmldir files")

# ---------------------------------------------------------------------------
# Analysis
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
        # App QML UI (Main.qml + qml/ tree + qmldir module files)
        *_ui_datas,
    ],
    hiddenimports=[
        # screeninfo platform-specific enumerator (not auto-discovered)
        "screeninfo.enumerators.windows",
        # PySide6 extras that may not be picked up automatically
        "PySide6.QtSvg",
        "PySide6.QtXml",
        "PySide6.QtDBus",
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
    console=False,          # no console window — system tray / GUI only
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
