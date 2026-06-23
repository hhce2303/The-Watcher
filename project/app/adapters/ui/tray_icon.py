from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from app.core.policy import policy_for

# Shared flag: set by main.py lifecycle, readable from anywhere.
_recording_active: bool = False


def set_recording_active(state: bool) -> None:
    global _recording_active
    _recording_active = state


class TrayIcon(QSystemTrayIcon):
    """
    System tray icon for long-running background usage.

    Menu (standard roles):
        Open Dashboard
        Exit

    Menu (Operator role — window is indestructible, process must keep running):
        Open Dashboard
        (no Exit — operators cannot terminate the recording process from the UI)
    """

    def __init__(
        self,
        show_fn: Callable[[], None],
        app: QApplication,
        role: str = "",
        watchdog_status: str | None = None,
    ) -> None:
        super().__init__(parent=app)
        self._show_fn = show_fn
        self._app = app
        self._role = role
        # "task" (registered), "runkey" (degraded fallback), or None (n/a).
        self._watchdog_status = watchdog_status
        self._setup()

    def _setup(self) -> None:
        self.setIcon(
            QIcon.fromTheme("camera-video", self._app.style().standardIcon(
                self._app.style().StandardPixmap.SP_MediaPlay  # type: ignore[attr-defined]
            ))
        )
        # Surface a degraded restart watchdog (e.g. Task Scheduler blocked by
        # group policy) where the operator can see it — they have no settings tab.
        if self._watchdog_status == "runkey":
            self.setToolTip(
                "The Watcher — Recording\n"
                "⚠ Auto-reinicio limitado: la app arranca al iniciar sesión, "
                "pero no se reiniciará automáticamente si se cierra el proceso."
            )
        else:
            self.setToolTip("The Watcher — Recording")

        menu = QMenu()
        open_action = menu.addAction("Open Dashboard")
        open_action.triggered.connect(self._show_fn)

        # Exit is gated by policy: the operator's process must stay alive, so its
        # policy has can_exit_from_tray=False (no Exit item). Other roles get it.
        if policy_for(self._role).can_exit_from_tray:
            menu.addSeparator()
            exit_action = menu.addAction("Exit")
            exit_action.triggered.connect(self._app.quit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activate)
        self.show()

    def _on_activate(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_fn()
