from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

# Default pipeline-phase context. Every record carries these keys so the sink
# formats below can reference {extra[phase]} etc. without a KeyError; individual
# call sites enrich them with ``logger.bind(phase=..., mon=..., sid=..., evt=...)``.
#   phase — pipeline stage: DETECT / PROVISION / CAPTURE / SEGMENT /
#           BUILD-CONT / BUILD-EVENT / RECORDING / SUPERVISE
#   mon   — monitor tag (e.g. "m0") for per-screen correlation
#   sid   — session id (changes on every (re)provision of a monitor)
#   evt   — event id (shared across an event's trim→timestamp→combine logs)
_DEFAULT_EXTRA = {"phase": "-", "mon": "-", "sid": "-", "evt": "-"}


_event_bus = None  # wired via set_event_bus() once core/api exists; None = no-op sink


def set_event_bus(bus) -> None:
    """Point the log sink at the shared EventBus (main.py, after building `api`).

    Qt-free replacement for the old QML log panel sink (ADR-0009/C3): logs
    become a ``LogMessage`` bus event, so both the IPC-connected React UI and
    (while it still exists) QML's Connections-based log panel can consume it.
    """
    global _event_bus
    _event_bus = bus


def _bus_sink(message: "loguru.Message") -> None:  # type: ignore[name-defined]
    """Publish INFO+ records as a LogMessage bus event; no-op before the bus exists."""
    if _event_bus is None:
        return
    record = message.record
    if record["name"].startswith("app.adapters.ipc"):
        return  # avoid feeding pipe-transport chatter back through the pipe
    try:
        from app.core.api import dto  # noqa: PLC0415
        _event_bus.publish(dto.LogMessage(message=record["message"]))
    except Exception:  # noqa: BLE001 — logging must never crash the app
        pass


def _resolve_log_dir() -> Path:
    """Where watcher.log lives — resolved before Settings exists (this runs
    first in main()), so it can't read config.py's WATCHER_LOG_DIR-less
    settings object; it reads the env var directly instead.

    Frozen builds keep logs next to the executable (unchanged). Dev-mode used
    to default to ``Path(".")`` — the repo checkout, which on this machine (and
    plausibly other dev boxes) is a OneDrive-synced folder. config.py already
    keeps segment_dir/clips_dir/events.db OUT of OneDrive so Defender/OneDrive
    sync can never hold a lock on them; the log file never got the same
    treatment, and every thread shares one loguru sink — a single stuck write
    would stall all of them simultaneously. Default dev-mode logs to the same
    local root the rest of the app's data already uses.
    """
    override = os.getenv("WATCHER_LOG_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "logs"
    return Path(r"C:\WatcherData") / "logs"


def configure_logging(log_level: str = "INFO") -> None:
    """Set up loguru sinks: coloured stderr + rotating file + Qt panel.

    All sinks expose the pipeline ``phase`` (and the file sink the full
    mon/evt correlation columns) so logs can be filtered per pipeline stage
    and an event traced end-to-end via ``grep "evt=<id>"``.
    """
    logger.remove()
    # Seed the default phase context so format strings always resolve.
    logger.configure(extra=dict(_DEFAULT_EXTRA))

    # sys.stderr is None in windowed (console=False) frozen builds.
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=log_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <7}</level> | "
                "<magenta>{extra[phase]: <11}</magenta> | "
                "<cyan>{extra[mon]: <4}</cyan> | "
                "<level>{message}</level>"
            ),
            colorize=True,
        )

    _log_file = _resolve_log_dir() / "watcher.log"
    _log_file.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        str(_log_file),
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        encoding="utf-8",
        # Full audit columns: phase | mon | evt for per-phase filtering and
        # end-to-end event correlation.
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | "
            "{extra[phase]: <11} | {extra[mon]: <4} | evt={extra[evt]: <8} | "
            "{name}:{line} - {message}"
        ),
    )

    # Bus sink — no-ops silently until set_event_bus() is called (core/api not
    # built yet at configure_logging() time). INFO+ only: DEBUG would flood
    # the UI's notification strip.
    logger.add(_bus_sink, level="INFO")

    logger.debug("Logging initialised at level={}", log_level)
