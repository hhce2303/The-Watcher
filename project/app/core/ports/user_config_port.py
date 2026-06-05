from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class UserConfig:
    """Persisted user preferences — survives app restarts.

    These live in ``%LOCALAPPDATA%\\The Watcher\\user_config.json`` and are
    per-machine: the same build runs on PCs with very different GPUs, so each
    one remembers its own encoder/driver choice.
    """

    clips_dir: Optional[str] = None
    selected_monitor_fingerprints: List[str] = field(default_factory=list)

    # Encoding — per-PC hardware choice.
    #   driver: "auto" | "nvidia" | "intel" | "amd" | "cpu"
    #     "auto" probes for the best hardware encoder; the others force a vendor
    #     and fall back to auto if that vendor's encoder is unavailable.
    #   codec:  "h264" | "hevc" | None (None → use .env VIDEO_CODEC default)
    driver: str = "auto"
    codec: Optional[str] = None

    # Start the rolling buffer automatically when the app launches.
    # Defaults True — The Watcher is an always-on recorder.
    autorecord: bool = True

    # Hostnames or IPs of the IT PCs this Supervisor sends requests to.
    # Edited from Ajustes → Red in the Supervisor UI.
    it_ws_hosts: List[str] = field(default_factory=list)

    # Per-machine role assignment.
    #   ""           → not yet configured; first-run wizard will be shown.
    #   "operator"   → 24/7 recording, no settings/clips UI, window indestructible.
    #   "supervisor" → clips playback/audit only, no recording.
    #   "it"         → full access (settings, editor placeholder, role change with PIN).
    role: str = ""


class UserConfigPort(ABC):
    @abstractmethod
    def load(self) -> UserConfig: ...

    @abstractmethod
    def save(self, config: UserConfig) -> None: ...
