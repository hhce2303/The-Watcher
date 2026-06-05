from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from loguru import logger

from app.core.ports.user_config_port import UserConfig, UserConfigPort


def _default_config_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    return base / "The Watcher" / "user_config.json"


class JsonUserConfigAdapter(UserConfigPort):
    """Persists user preferences to %LOCALAPPDATA%\\The Watcher\\user_config.json."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = path or _default_config_path()

    def load(self) -> UserConfig:
        if not self._path.exists():
            return UserConfig()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return UserConfig(
                clips_dir=data.get("clips_dir"),
                selected_monitor_fingerprints=data.get(
                    "selected_monitor_fingerprints", []
                ),
                driver=data.get("driver", "auto"),
                codec=data.get("codec"),
                autorecord=data.get("autorecord", True),
                it_ws_hosts=data.get("it_ws_hosts", []),
                role=data.get("role", ""),
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to load user config from {}; using defaults.", self._path
            )
            return UserConfig()

    def save(self, config: UserConfig) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {
                        "clips_dir": config.clips_dir,
                        "selected_monitor_fingerprints": config.selected_monitor_fingerprints,
                        "driver": config.driver,
                        "codec": config.codec,
                        "autorecord": config.autorecord,
                        "it_ws_hosts": config.it_ws_hosts,
                        "role": config.role,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to save user config to {}.", self._path)
