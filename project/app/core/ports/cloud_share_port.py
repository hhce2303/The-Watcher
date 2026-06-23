from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ShareResult:
    """Outcome of ensuring a destination folder exists and is shareable.

    ``folder_path`` is the logical path that was requested (e.g.
    ``"SLC/clips-supervisor/2026-06"``).  ``created`` is ``True`` only when the
    folder did not exist and was created by this operation — idempotent re-runs
    return ``False``.  ``share_link`` is the URL that can be handed to a
    Supervisor; ``web_url`` is where the folder lives (may equal ``share_link``
    for local-mode adapters).
    """

    folder_path: str
    web_url: str
    share_link: str
    created: bool


class CloudSharePort(ABC):
    """
    Port defining what the core expects from any cloud-folder share backend.

    Implementations are provided by adapters:

    - ``LocalShareAdapter`` (active today) — operates on a local directory
      tree (e.g. the machine's OneDrive sync root) and mints ``file://`` links.
    - ``OneDriveGraphAdapter`` (deferred) — talks to Microsoft Graph once an
      Azure AD app registration is available.

    Microsoft Graph mapping for the deferred adapter:
        ensure_folder      → GET  /me/drive/root:/{folder_path}          (probe)
                             POST /me/drive/root:/{parent}:/children     (create)
        create_share_link  → POST /me/drive/root:/{folder_path}:/createLink
                             body: {"type": "view", "scope": "organization"}
    """

    @abstractmethod
    def ensure_folder(self, folder_path: str) -> bool:
        """Search for ``folder_path``; create it (and any missing parents) if it
        does not exist.  Return ``True`` if it was newly created, ``False`` if it
        already existed.  Must be idempotent."""

    @abstractmethod
    def create_share_link(self, folder_path: str) -> str:
        """Create or fetch a read-only share link for ``folder_path`` and return
        its URL.  ``folder_path`` is expected to already exist."""

    @abstractmethod
    def web_url(self, folder_path: str) -> str:
        """Return the canonical location URL of ``folder_path`` (where it lives,
        as opposed to the shareable link)."""
