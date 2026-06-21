from __future__ import annotations

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


def _qt_sink(message: "loguru.Message") -> None:  # type: ignore[name-defined]
    """Forward log records to the Qt UI log panel (if the UI is running)."""
    try:
        from app.adapters.ui.log_handler import emitter  # noqa: PLC0415
        emitter.log_record.emit(str(message))
    except Exception:  # noqa: BLE001 — UI may not be initialised yet
        pass


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

    # Resolve log path relative to executable so logs land next to the app,
    # not in whatever the current working directory happens to be.
    _base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(".")
    _log_file = _base / "logs" / "watcher.log"
    _log_file.parent.mkdir(exist_ok=True)

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

    # Qt UI panel sink — no-ops silently until the UI is launched.
    logger.add(
        _qt_sink,
        level="DEBUG",
        format="{time:HH:mm:ss} | {level} | {extra[phase]} | {message}",
    )

    logger.debug("Logging initialised at level={}", log_level)
