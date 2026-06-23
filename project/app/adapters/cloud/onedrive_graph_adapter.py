from __future__ import annotations

from app.core.ports.cloud_share_port import CloudSharePort


class OneDriveGraphAdapter(CloudSharePort):
    """
    Microsoft Graph implementation of :class:`CloudSharePort` — **DEFERRED**.

    This adapter is a documented stub.  It is intentionally *not* wired in
    ``main.py`` because the deployment has no Azure AD app registration yet
    (no ``client_id`` / ``tenant_id`` / admin consent).  It exists to prove the
    port contract is realizable against real OneDrive for Business and to make
    the future swap a one-line change in ``main.py``.

    Activation checklist (when IT provides credentials):
      1. Register an Azure AD app; grant delegated ``Files.ReadWrite`` (+
         ``Sites.ReadWrite.All`` for SharePoint document libraries) with admin
         consent on the SIG tenant.
      2. Add ``msal`` + ``httpx`` to ``requirements.txt``.
      3. Read ``ONEDRIVE_CLIENT_ID`` / ``ONEDRIVE_TENANT_ID`` from ``config.py``
         and acquire a token (device-code flow for per-user delegated access).
      4. Implement the three methods below using the endpoints noted inline.
      5. In ``main.py`` construct ``OneDriveGraphAdapter(...)`` instead of
         ``LocalShareAdapter`` — nothing else changes (service/bridge/UI are
         adapter-agnostic).

    NOTE: until then every method raises ``NotImplementedError`` so accidental
    wiring fails loudly instead of silently no-op'ing.
    """

    def __init__(
        self,
        client_id: str,
        tenant_id: str,
        token_provider=None,  # callable returning a bearer token; injected later
    ) -> None:
        self._client_id = client_id
        self._tenant_id = tenant_id
        self._token_provider = token_provider

    def ensure_folder(self, folder_path: str) -> bool:
        # GET  /me/drive/root:/{folder_path}                 → 200 exists / 404 missing
        # POST /me/drive/root:/{parent}:/children            → create each missing segment
        #   body: {"name": <segment>, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
        raise NotImplementedError(
            "OneDriveGraphAdapter is a deferred stub — provide Azure AD "
            "credentials and implement Graph calls before wiring it."
        )

    def create_share_link(self, folder_path: str) -> str:
        # POST /me/drive/root:/{folder_path}:/createLink
        #   body: {"type": "view", "scope": "organization"}  → resp.link.webUrl
        raise NotImplementedError(
            "OneDriveGraphAdapter is a deferred stub — see ensure_folder()."
        )

    def web_url(self, folder_path: str) -> str:
        # GET /me/drive/root:/{folder_path}                  → resp.webUrl
        raise NotImplementedError(
            "OneDriveGraphAdapter is a deferred stub — see ensure_folder()."
        )
