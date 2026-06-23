from __future__ import annotations

from loguru import logger

from app.core.ports.cloud_share_port import CloudSharePort, ShareResult


class CloudShareService:
    """
    Orchestrates the "ensure folder, then share it" flow for the OneDrive panel.

    Core business logic — no Qt, no I/O, no infrastructure imports.  All side
    effects go through the injected :class:`CloudSharePort`, so the same service
    drives the local adapter today and the Microsoft Graph adapter later without
    changing a line here.
    """

    def __init__(self, port: CloudSharePort) -> None:
        self._port = port

    def ensure_folder_and_link(self, folder_path: str) -> ShareResult:
        """Search for ``folder_path`` (creating it and any missing parents if
        absent), then return a read-only share link for it.

        Idempotent: re-running against an existing folder reuses it and reports
        ``created=False``.  Any error raised by the port propagates to the
        caller, which is responsible for surfacing it to the UI.
        """
        normalized = self._normalize(folder_path)
        if not normalized:
            raise ValueError("folder_path must not be empty")

        created = self._port.ensure_folder(normalized)
        share_link = self._port.create_share_link(normalized)
        web_url = self._port.web_url(normalized)

        logger.info(
            "CloudShare: folder '{}' {} → link ready.",
            normalized,
            "created" if created else "reused",
        )
        return ShareResult(
            folder_path=normalized,
            web_url=web_url,
            share_link=share_link,
            created=created,
        )

    @staticmethod
    def _normalize(folder_path: str) -> str:
        """Collapse separators and strip surrounding whitespace/slashes so that
        ``" SLC / clips-supervisor / 2026-06 "`` and
        ``"SLC\\clips-supervisor\\2026-06"`` resolve to the same logical path."""
        if not folder_path:
            return ""
        parts = [
            seg.strip()
            for seg in folder_path.replace("\\", "/").split("/")
            if seg.strip()
        ]
        return "/".join(parts)
