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


def _resolve_log_dir() -> Path:
    """Where watcher.log lives — resolved before Settings exists (this runs
    first in daemon_root.main()), so it can't read config.py's WATCHER_LOG_DIR-less
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
    """Set up loguru sinks: coloured stderr + rotating file.

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

    logger.debug("Logging initialised at level={}", log_level)
