from __future__ import annotations

from pathlib import Path

from loguru import logger

from app.core.ports.cloud_share_port import CloudSharePort


class LocalShareAdapter(CloudSharePort):
    """
    Local-filesystem implementation of :class:`CloudSharePort`.

    The folder operations are *real*: the destination is created under a
    configured root (the machine's OneDrive sync folder), so the OneDrive
    desktop client then syncs it to the cloud.  Because no Microsoft Graph
    credentials are required, the full click → search → create → link flow works
    and is fully testable today.

    The share "link" is a ``file://`` URL to the folder — honest for local mode.
    Swapping in :class:`OneDriveGraphAdapter` later yields true ``https://``
    SharePoint links with no change to the service, bridge, or UI.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _abs(self, folder_path: str) -> Path:
        # folder_path is already normalized to "/"-separated segments by the
        # service; Path joins them correctly on every platform.
        return (self._root / folder_path).resolve(strict=False)

    def ensure_folder(self, folder_path: str) -> bool:
        target = self._abs(folder_path)
        existed = target.exists()
        target.mkdir(parents=True, exist_ok=True)
        if existed:
            logger.debug("LocalShare: folder already present → {}", target)
        else:
            logger.info("LocalShare: created folder → {}", target)
        return not existed

    def create_share_link(self, folder_path: str) -> str:
        return self.web_url(folder_path)

    def web_url(self, folder_path: str) -> str:
        return self._abs(folder_path).as_uri()
