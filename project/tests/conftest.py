"""Shared pytest fixtures for the full test suite."""
from __future__ import annotations

import sys
import pytest


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
