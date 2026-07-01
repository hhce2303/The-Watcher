"""Shared pytest fixtures for the full test suite."""
from __future__ import annotations

import sys
import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers (avoids PytestUnknownMarkWarning)."""
    config.addinivalue_line(
        "markers",
        "parity: Rust↔FFmpeg segment-compiler parity harness (F0 gate, "
        "auto-skips until the native engine is built).",
    )


@pytest.fixture(scope="session")
def qt_app():
    """Session-scoped QCoreApplication — required for any test that touches QObject.

    Using QCoreApplication (no GUI) keeps the fixture fast in CI and avoids
    display-server requirements.  All WS / signal tests share this single instance.
    """
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv)
    yield app
