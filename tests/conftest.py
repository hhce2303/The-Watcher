"""Shared pytest fixtures for the full test suite."""
from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers (avoids PytestUnknownMarkWarning)."""
    config.addinivalue_line(
        "markers",
        "parity: Rust↔FFmpeg segment-compiler parity harness (F0 gate, "
        "auto-skips until the native engine is built).",
    )
