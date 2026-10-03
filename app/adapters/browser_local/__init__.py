"""Session/identity helpers shared with the LAN live view (``auth``, ``identity``).

Deliberately empty: the monorepo's ``__init__`` re-exported ``BrowserLocalAdapter``
from ``server.py``, which imports ``core.api`` (editor/player/role).  The
browser-local HTTP server is out of scope (ADR-0023) and is not shipped here;
importing this package must stay free of it (enforced by tests/test_import_purity.py).
"""
