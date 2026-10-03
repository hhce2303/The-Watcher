"""Logging setup for the daemon: stderr + rotating file only (no event bus)."""
from __future__ import annotations

from loguru import logger

from app.infrastructure import logging_setup


def test_configure_logging_writes_the_rotating_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WATCHER_LOG_DIR", str(tmp_path))
    logging_setup.configure_logging()
    logger.info("daemon log line")
    logger.complete()
    log_file = tmp_path / "watcher.log"
    assert log_file.exists()
    assert "daemon log line" in log_file.read_text(encoding="utf-8")


def test_logging_setup_has_no_event_bus_hook() -> None:
    # The monitor's core.api EventBus does not exist in this repo: there must be
    # no sink that lazily imports it (it would break the import-purity gate).
    assert not hasattr(logging_setup, "set_event_bus")
    assert not hasattr(logging_setup, "_bus_sink")
