from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_APP_NAME = "The-Watcher"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def is_autostart_enabled() -> bool:
    """Return True if The Watcher is registered to launch at Windows login."""
    if sys.platform != "win32":
        return False
    try:
        import winreg  # type: ignore[import]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except Exception:  # noqa: BLE001
        return False


def set_autostart(enabled: bool) -> None:
    """Register or de-register The Watcher for Windows auto-start.

    Only works on Windows; silently no-ops on other platforms.
    Only meaningful when running as a frozen PyInstaller executable.
    """
    if sys.platform != "win32":
        return

    try:
        import winreg  # type: ignore[import]

        exe_path = (
            str(Path(sys.executable))
            if getattr(sys, "frozen", False)
            else sys.executable
        )
        # Wrap path in quotes to handle spaces
        launch_cmd = f'"{exe_path}"'

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, launch_cmd)
                logger.info("Auto-start enabled: {}", launch_cmd)
            else:
                try:
                    winreg.DeleteValue(key, _APP_NAME)
                    logger.info("Auto-start disabled.")
                except FileNotFoundError:
                    pass  # already not registered
    except Exception:  # noqa: BLE001
        logger.exception("Failed to {} auto-start registry entry.", "set" if enabled else "clear")
