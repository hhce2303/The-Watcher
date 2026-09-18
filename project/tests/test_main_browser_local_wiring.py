"""Regression test for the browser-local wiring dead-code bug (f13ecec).

`_build_browser_local_adapter` must actually construct and return a
BrowserLocalAdapter when the role/flag guard passes. A prior merge inserted
`_build_live_view_adapter` in the middle of this function's body, leaving its
`try: return BrowserLocalAdapter(...)` block unreachable inside the new
function instead — so it silently returned None even with
BROWSER_LOCAL_ENABLED=true, and the channel never started in production.
"""
from __future__ import annotations

from types import SimpleNamespace

import app.main as main_module
from app.main import OPERATOR, _build_browser_local_adapter


def test_builds_browser_local_adapter_when_enabled(monkeypatch) -> None:
    created: dict[str, object] = {}

    class _StubAdapter:
        def __init__(self, settings, api) -> None:
            created["settings"] = settings
            created["api"] = api

    monkeypatch.setattr(main_module, "BrowserLocalAdapter", _StubAdapter)

    user_config = SimpleNamespace(role=OPERATOR)
    settings = SimpleNamespace(browser_local_enabled=True)
    api = object()

    result = _build_browser_local_adapter(user_config, settings, api, clips_dir=None, event_clips_dir=None)

    assert isinstance(result, _StubAdapter)
    assert created["settings"] is settings
    assert created["api"] is api


def test_skips_browser_local_adapter_when_disabled() -> None:
    user_config = SimpleNamespace(role=OPERATOR)
    settings = SimpleNamespace(browser_local_enabled=False)

    result = _build_browser_local_adapter(
        user_config, settings, api=object(), clips_dir=None, event_clips_dir=None
    )

    assert result is None


def test_skips_browser_local_adapter_for_non_operator_role() -> None:
    user_config = SimpleNamespace(role="it")
    settings = SimpleNamespace(browser_local_enabled=True)

    result = _build_browser_local_adapter(
        user_config, settings, api=object(), clips_dir=None, event_clips_dir=None
    )

    assert result is None
