from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from loguru import logger

from app.core.ports.request_port import ClipRequest, RequestPort


def _default_requests_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    return base / "The Watcher" / "requests"


class JsonRequestAdapter(RequestPort):
    """Persists ClipRequest objects as individual JSON files.

    Each request → one file: ``{requests_dir}/{id}.json``

    Used by both Supervisor (outbox) and IT (inbox) — same format, different
    directories if needed, but defaults to the same location since each PC
    only has one role and therefore one perspective (send OR receive).
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._dir = path or _default_requests_dir()
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, req: ClipRequest) -> None:
        fpath = self._dir / f"{req.id}.json"
        try:
            fpath.write_text(
                json.dumps(req.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("Request saved: {}", fpath.name)
        except OSError:
            logger.exception("Failed to save request {}.", req.id)

    def load_all(self) -> list[ClipRequest]:
        requests: list[ClipRequest] = []
        for fpath in sorted(self._dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                requests.append(ClipRequest.from_dict(data))
            except Exception:  # noqa: BLE001
                logger.warning("Skipping malformed request file: {}", fpath.name)
        return requests

    def update_status(self, req_id: str, status: str) -> None:
        fpath = self._dir / f"{req_id}.json"
        if not fpath.exists():
            logger.warning("update_status: request {} not found on disk.", req_id)
            return
        try:
            data = json.loads(fpath.read_text(encoding="utf-8"))
            data["status"] = status
            fpath.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.debug("Request {} status → {}.", req_id, status)
        except OSError:
            logger.exception("Failed to update request {} status.", req_id)
