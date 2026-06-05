from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app.adapters.ui.log_handler import emitter
from app.core.event_service import EventService
from app.core.ports.monitor_port import MonitorPort
from app.core.recording_service.models import MonitorInfo
from app.core.recording_service.service import RecordingService
from app.infrastructure.autostart import is_autostart_enabled, set_autostart


class MainWindow(QMainWindow):
    """
    Milestone 5 — Minimal operator dashboard.

    Architecture rule: this class is a pure adapter.
    It only calls EventService and reads RecordingService status.
    No business logic lives here.
    """

    def __init__(
        self,
        event_service: EventService,
        recording_service: RecordingService,
        monitor_adapter: MonitorPort,
    ) -> None:
        super().__init__()
        self._event_service = event_service
        self._recording_service = recording_service
        self._monitor_adapter = monitor_adapter
        self._monitors: List[MonitorInfo] = []
        self._setup_ui()
        self._connect_log_sink()
        self._start_status_poll()
        self._load_monitors()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("Kamee Watcher")
        self.setMinimumSize(700, 520)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # Status indicator
        self._status_label = QLabel("● Recording: checking…")
        self._status_label.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        layout.addWidget(self._status_label)

        # Monitor selector row
        monitor_row = QHBoxLayout()
        monitor_label = QLabel("Monitor:")
        monitor_label.setFont(QFont("Segoe UI", 10))
        monitor_row.addWidget(monitor_label)

        self._monitor_combo = QComboBox()
        self._monitor_combo.setFont(QFont("Segoe UI", 10))
        self._monitor_combo.setMinimumWidth(300)
        self._monitor_combo.currentIndexChanged.connect(self._on_monitor_changed)
        monitor_row.addWidget(self._monitor_combo, stretch=1)

        self._refresh_btn = QPushButton("↺")
        self._refresh_btn.setFixedWidth(36)
        self._refresh_btn.setToolTip("Refresh monitor list")
        self._refresh_btn.clicked.connect(self._load_monitors)
        monitor_row.addWidget(self._refresh_btn)

        layout.addLayout(monitor_row)

        # Mark Event button
        self._event_btn = QPushButton("⚡  Mark Event")
        self._event_btn.setFixedHeight(48)
        self._event_btn.setFont(QFont("Segoe UI", 12))
        self._event_btn.clicked.connect(self._on_event_clicked)
        layout.addWidget(self._event_btn)

        # Log panel
        log_label = QLabel("Activity Log")
        log_label.setFont(QFont("Segoe UI", 9))
        layout.addWidget(log_label)

        self._log_panel = QPlainTextEdit()
        self._log_panel.setReadOnly(True)
        self._log_panel.setMaximumBlockCount(500)
        self._log_panel.setFont(QFont("Consolas", 9))
        layout.addWidget(self._log_panel)

        # Auto-start checkbox (bottom)
        self._autostart_check = QCheckBox("Launch Kamee-Watcher automatically at Windows login")
        self._autostart_check.setFont(QFont("Segoe UI", 9))
        self._autostart_check.setChecked(is_autostart_enabled())
        self._autostart_check.stateChanged.connect(self._on_autostart_changed)
        layout.addWidget(self._autostart_check)

        self.setStatusBar(QStatusBar())

    # ------------------------------------------------------------------
    # Monitor selector
    # ------------------------------------------------------------------

    def _load_monitors(self) -> None:
        """Populate the monitor combo box from the MonitorPort."""
        monitors = self._monitor_adapter.list_monitors()
        if not monitors:
            return

        # Block signals while rebuilding to avoid spurious change events
        self._monitor_combo.blockSignals(True)
        current_fp = self._current_fingerprint()
        self._monitors = monitors
        self._monitor_combo.clear()
        for m in monitors:
            self._monitor_combo.addItem(m.display_name)

        # Restore previous selection by fingerprint, else keep primary (index 0)
        restored = False
        if current_fp:
            for i, m in enumerate(monitors):
                if m.fingerprint == current_fp:
                    self._monitor_combo.setCurrentIndex(i)
                    restored = True
                    break
        if not restored:
            self._monitor_combo.setCurrentIndex(0)

        self._monitor_combo.blockSignals(False)
        self.statusBar().showMessage(
            f"{len(monitors)} monitor(s) detected.", 3000
        )

    def _current_fingerprint(self) -> Optional[str]:
        idx = self._monitor_combo.currentIndex()
        if 0 <= idx < len(self._monitors):
            return self._monitors[idx].fingerprint
        return None

    def _on_monitor_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._monitors):
            return
        monitor = self._monitors[index]
        self._recording_service.change_monitor(monitor)
        self.statusBar().showMessage(
            f"Switched to: {monitor.display_name}", 4000
        )

    # ------------------------------------------------------------------
    # Log sink — receives records from loguru via queued signal
    # ------------------------------------------------------------------

    def _connect_log_sink(self) -> None:
        emitter.log_record.connect(self._append_log)

    def _append_log(self, message: str) -> None:
        self._log_panel.appendPlainText(message.rstrip())
        scrollbar = self._log_panel.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ------------------------------------------------------------------
    # Status polling (every 2 s)
    # ------------------------------------------------------------------

    def _start_status_poll(self) -> None:
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._update_status)
        self._poll_timer.start(2000)

    def _update_status(self) -> None:
        from app.adapters.ui.tray_icon import _recording_active  # noqa: PLC0415
        if _recording_active:
            self._status_label.setText("● Recording: ACTIVE")
            self._status_label.setStyleSheet("color: #22c55e;")
        else:
            self._status_label.setText("● Recording: STOPPED")
            self._status_label.setStyleSheet("color: #ef4444;")

    # ------------------------------------------------------------------
    # Event button handler
    # ------------------------------------------------------------------

    def _on_event_clicked(self) -> None:
        accepted = self._event_service.trigger_manual_event()
        if accepted:
            self.statusBar().showMessage("Event marked — clip will be ready in ~2 min.", 5000)
            self._event_btn.setEnabled(False)
            QTimer.singleShot(
                self._event_service._cooldown_seconds * 1000,
                lambda: self._event_btn.setEnabled(True),
            )
        else:
            self.statusBar().showMessage("Cooldown active — please wait.", 3000)

            self.statusBar().showMessage("Cooldown active — please wait.", 3000)

    # ------------------------------------------------------------------
    # Auto-start toggle
    # ------------------------------------------------------------------

    def _on_autostart_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked.value
        set_autostart(enabled)
        msg = "Auto-start enabled." if enabled else "Auto-start disabled."
        self.statusBar().showMessage(msg, 3000)

    # ------------------------------------------------------------------
    # Background-on-close — minimise to tray instead of quitting
    # ------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        """Hide to system tray when the user closes the window.

        The application continues recording in the background.
        Use the tray menu \"Exit\" to fully quit.
        """
        event.ignore()
        self.hide()
        self.statusBar().showMessage("Kamee-Watcher is still running in the system tray.", 4000)
