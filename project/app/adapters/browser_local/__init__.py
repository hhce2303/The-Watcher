"""Browser-only loopback adapter for the Daily SIG Systems iframe.

This package is intentionally independent from ``adapters.ipc``.  The latter
is the user-scoped Windows named-pipe contract used by the Tauri shell; this
one is a narrow HTTPS/WSS read-only surface for a normal browser iframe.
"""

from app.adapters.browser_local.server import BrowserLocalAdapter

__all__ = ["BrowserLocalAdapter"]
