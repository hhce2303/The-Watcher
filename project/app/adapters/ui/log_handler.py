from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class LogSignalEmitter(QObject):
    """
    Bridge between loguru and Qt's signal/slot system.

    loguru runs on background threads; Qt widgets can only be updated
    on the main thread. This QObject emits a queued signal so log records
    are safely delivered to the UI from any thread.
    """

    log_record = Signal(str)  # emits the formatted log message


# Module-level singleton — created once and shared by logging_setup and MainWindow.
emitter = LogSignalEmitter()
