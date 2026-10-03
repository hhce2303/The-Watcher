from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from loguru import logger

# Well-known Windows installation locations to search when ffmpeg is not on PATH.
_WINDOWS_CANDIDATE_GLOBS = [
    # winget (Gyan.FFmpeg) — version-agnostic glob
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Microsoft" / "WinGet" / "Packages",
    # Chocolatey
    Path("C:/ProgramData/chocolatey/bin"),
    # Scoop (current user)
    Path(os.environ.get("USERPROFILE", "")) / "scoop" / "shims",
    # Manual extraction under Program Files
    Path("C:/Program Files/ffmpeg/bin"),
    Path("C:/ffmpeg/bin"),
]


def resolve_ffmpeg() -> str:
    """Return a usable ffmpeg executable path.

    Search order:
    1. ``shutil.which`` — honours the current process PATH.
    2. Known Windows installation directories (winget, Chocolatey, Scoop, manual).
    3. The environment variables PATH as stored in the Windows registry so the
       call succeeds even in terminals that have not reloaded PATH since install.

    Raises ``FileNotFoundError`` if ffmpeg cannot be located.
    """
    # 0. PyInstaller frozen bundle — ffmpeg.exe bundled inside bin/
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "bin" / "ffmpeg.exe"  # type: ignore[attr-defined]
        if bundled.exists():
            logger.debug("ffmpeg found in PyInstaller bundle: {}", bundled)
            return str(bundled)

    # 1. Fast path — already on PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    # 2. Registry PATH fallback (Windows only) — reload machine + user PATH
    if sys.platform == "win32":
        try:
            import winreg  # type: ignore[import]

            def _reg_path(hive: int, subkey: str, value: str) -> str:
                with winreg.OpenKey(hive, subkey) as key:
                    data, _ = winreg.QueryValueEx(key, value)
                    return str(data)

            _env_key = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
            _user_key = r"Environment"
            machine_path = _reg_path(winreg.HKEY_LOCAL_MACHINE, _env_key, "Path")
            user_path = _reg_path(winreg.HKEY_CURRENT_USER, _user_key, "Path")
            registry_path = machine_path + os.pathsep + user_path
            found = shutil.which("ffmpeg", path=registry_path)
            if found:
                # Also patch the live PATH so child processes can find it too
                os.environ["PATH"] = registry_path + os.pathsep + os.environ.get("PATH", "")
                logger.debug("ffmpeg found via registry PATH: {}", found)
                return found
        except Exception:  # noqa: BLE001
            pass

    # 3. Brute-force known locations
    for base in _WINDOWS_CANDIDATE_GLOBS:
        if not base.exists():
            continue
        # The winget base is a directory of package sub-directories
        if "WinGet" in str(base):
            for candidate in base.glob("Gyan.FFmpeg*/**/ffmpeg.exe"):
                logger.debug("ffmpeg found via WinGet scan: {}", candidate)
                _add_to_path(candidate.parent)
                return str(candidate)
        else:
            candidate = base / "ffmpeg.exe"
            if candidate.exists():
                logger.debug("ffmpeg found via known path: {}", candidate)
                _add_to_path(candidate.parent)
                return str(candidate)

    raise FileNotFoundError(
        "ffmpeg executable not found. Install FFmpeg and ensure it is on PATH, "
        "or install via: winget install --id Gyan.FFmpeg"
    )


def resolve_ffprobe() -> str:
    """Return a usable ffprobe executable path.

    Derives the path from :func:`resolve_ffmpeg` — ffprobe lives in the same
    ``bin/`` directory as ffmpeg in every standard distribution.

    Raises ``FileNotFoundError`` if ffprobe cannot be located.
    """
    ffmpeg_path = resolve_ffmpeg()
    ffmpeg_bin = Path(ffmpeg_path)

    # Replace the executable name; preserve the directory and extension.
    stem = "ffprobe"
    suffix = ffmpeg_bin.suffix  # ".exe" on Windows, "" on Unix
    candidate = ffmpeg_bin.parent / (stem + suffix)
    if candidate.exists():
        return str(candidate)

    # Fallback: try PATH resolution in case only ffmpeg was found via PATH
    found = shutil.which("ffprobe")
    if found:
        return found

    raise FileNotFoundError(
        "ffprobe executable not found. It should be bundled with FFmpeg in the same "
        "directory. Ensure your FFmpeg installation includes ffprobe."
    )


def _add_to_path(directory: Path) -> None:
    """Prepend *directory* to ``os.environ['PATH']`` for the current process."""
    dir_str = str(directory)
    current = os.environ.get("PATH", "")
    if dir_str not in current:
        os.environ["PATH"] = dir_str + os.pathsep + current
