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
# Resolve mkcert binary to bundle (used by the enrollment tool to issue the
# browser-local loopback TLS certificate on the target machine).
# ---------------------------------------------------------------------------
_mkcert_exe = shutil.which("mkcert")

if not _mkcert_exe:
    _winget_base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if _winget_base.exists():
        for _f in _winget_base.glob("FiloSottile.mkcert*/**/mkcert.exe"):
            _mkcert_exe = str(_f)
            break

if not _mkcert_exe:
    raise SystemExit(
        "ERROR: mkcert.exe not found -- install it before building:\n"
        "  winget install FiloSottile.mkcert"
    )

print(f"[spec] Bundling mkcert: {_mkcert_exe}")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(SPECPATH).parent)
_MAIN_SCRIPT  = str(Path(SPECPATH).parent / "app" / "main.py")
_ENROLL_SCRIPT = str(Path(SPECPATH).parent / "app" / "tools" / "browser_local_enroll.py")
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
        # mkcert.exe, resolved by browser_local_enroll.py's _find_mkcert() at
        # Path(sys.executable).parent/"bin"/"mkcert.exe" in a frozen build.
        (_mkcert_exe, "bin"),
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

a_enroll = Analysis(
    [_ENROLL_SCRIPT],
    pathex=[_PROJECT_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "pytest_timeout", "_pytest"],
    noarchive=False,
    optimize=0,
)

# NOTE: deliberately NOT using PyInstaller's MERGE() here. MERGE removes a
# "duplicate" pure-python module from every Analysis but the first, assuming
# it only needs to be embedded once — that only holds for modules loaded
# from loose files on disk (binaries/datas), not for .pure modules, which
# live INSIDE each executable's own PYZ archive. Since importing
# app.adapters.browser_local.identity (Task 1) also executes
# app/adapters/browser_local/__init__.py -> server.py -> aiohttp, "The
# Watcher Enroll.exe" genuinely needs aiohttp bundled in ITS OWN PYZ too —
# MERGE strips it from a_enroll.pure (already claimed by `a`), producing a
# ModuleNotFoundError at runtime. Each Analysis instead bundles its own full
# closure; the only intentional overlap (ffmpeg.exe/mkcert.exe) is already
# assigned exclusively to `a`'s binaries=[...] above (a_enroll's is empty),
# so COLLECT still places exactly one copy of each in dist/The Watcher/.
pyz = PYZ(a.pure)
pyz_enroll = PYZ(a_enroll.pure)

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

exe_enroll = EXE(
    pyz_enroll,
    a_enroll.scripts,
    [],
    exclude_binaries=True,
    name="The Watcher Enroll",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,           # prints device_id/public key/cert fingerprint to the caller's terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    exe_enroll,
    a_enroll.binaries,
    a_enroll.zipfiles,
    a_enroll.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="The Watcher",
)
