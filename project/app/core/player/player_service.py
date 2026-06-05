from __future__ import annotations

from pathlib import Path
from typing import Optional

from loguru import logger

from app.core.player.models import ClipInfo, PlaybackState
from app.core.ports.clip_inspector_port import ClipInspectorPort


class PlayerService:
    """Domain service for the clip player.

    Holds playback state and clip metadata.  The UI adapter calls this service
    to load clips and record state changes; the service never touches Qt directly.
    """

    def __init__(self, inspector: ClipInspectorPort) -> None:
        self._inspector = inspector
        self._current:   Optional[ClipInfo]  = None
        self._state:     PlaybackState       = PlaybackState.STOPPED

    # ── clip management ───────────────────────────────────────────────

    def load(self, path: Path) -> ClipInfo:
        """Inspect *path* and cache its metadata.  Returns :class:`ClipInfo`."""
        info = self._inspector.inspect(path)
        self._current = info
        self._state   = PlaybackState.STOPPED
        logger.info(
            "PlayerService loaded: {} | {} | {} | {}",
            path.name,
            info.resolution,
            info.video_codec,
            info.duration_str,
        )
        return info

    # ── state transitions ─────────────────────────────────────────────

    def set_playing(self) -> None:
        self._state = PlaybackState.PLAYING

    def set_paused(self) -> None:
        self._state = PlaybackState.PAUSED

    def set_stopped(self) -> None:
        self._state = PlaybackState.STOPPED

    # ── read-only properties ──────────────────────────────────────────

    @property
    def current_clip(self) -> Optional[ClipInfo]:
        return self._current

    @property
    def state(self) -> PlaybackState:
        return self._state
