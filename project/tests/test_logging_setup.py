"""Bus-backed log sink (C3) — Qt-free replacement for the old QML log panel sink."""
from __future__ import annotations

from loguru import logger

from app.core.api import dto
from app.core.api.events import EventBus
from app.infrastructure import logging_setup


def teardown_function(_fn) -> None:
    logging_setup.set_event_bus(None)


def test_bus_sink_noop_before_event_bus_is_set() -> None:
    logging_setup.set_event_bus(None)
    # Must not raise even though no bus is wired yet.
    logging_setup._bus_sink(_FakeMessage("hello"))


def test_bus_sink_publishes_log_message() -> None:
    bus = EventBus()
    logging_setup.set_event_bus(bus)
    seen = []
    bus.subscribe(dto.LogMessage, seen.append)

    logging_setup._bus_sink(_FakeMessage("something happened"))
    bus.drain()

    assert len(seen) == 1
    assert seen[0].message == "something happened"


def test_bus_sink_skips_ipc_module_records() -> None:
    bus = EventBus()
    logging_setup.set_event_bus(bus)
    seen = []
    bus.subscribe(dto.LogMessage, seen.append)

    logging_setup._bus_sink(_FakeMessage("pipe chatter", name="app.adapters.ipc.pipe_server"))
    bus.drain()

    assert seen == []


def test_configure_logging_wires_bus_sink_end_to_end() -> None:
    logging_setup.configure_logging()
    bus = EventBus()
    logging_setup.set_event_bus(bus)
    seen = []
    bus.subscribe(dto.LogMessage, seen.append)

    logger.info("integration message")
    bus.drain()

    assert any(e.message == "integration message" for e in seen)


class _FakeMessage:
    """Mimics loguru.Message's `.record` mapping access used by _bus_sink."""

    def __init__(self, text: str, name: str = "app.some.module") -> None:
        self.record = {"message": text, "name": name}
