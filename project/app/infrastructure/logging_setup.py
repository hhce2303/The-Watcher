from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def _qt_sink(message: "loguru.Message") -> None:  # type: ignore[name-defined]
    """Forward log records to the Qt UI log panel (if the UI is running)."""
    try:
        from app.adapters.ui.log_handler import emitter  # noqa: PLC0415
        emitter.log_record.emit(str(message))
    except Exception:  # noqa: BLE001 — UI may not be initialised yet
        pass


def configure_logging(log_level: str = "INFO") -> None:
    """Set up loguru sinks: coloured stderr + rotating file + Qt panel."""
    logger.remove()

    # sys.stderr is None in windowed (console=False) frozen builds.
    if sys.stderr is not None:
        logger.add(
            sys.stderr,
            level=log_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{line}</cyan> - "
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
    )

    # Qt UI panel sink — no-ops silently until the UI is launched.
    logger.add(_qt_sink, level="DEBUG", format="{time:HH:mm:ss} | {level} | {message}")

    logger.debug("Logging initialised at level={}", log_level)
