from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from loguru import logger
from PySide6.QtCore import QObject, Property, Signal, Slot

from app.adapters.ffmpeg import encoder_selector
from app.core.ports.user_config_port import UserConfigPort
from app.core.role import IT, VALID_ROLES
from app.infrastructure import autostart
from app.infrastructure.config import Settings

# Canonical driver order — index matches the UI dropdown model.
_DRIVERS = ["auto", "nvidia", "intel", "amd", "cpu"]

# Restart states surfaced to QML for UI feedback.
_RESTART_IDLE    = "idle"
_RESTART_RUNNING = "restarting"
_RESTART_DONE    = "done"
_RESTART_ERROR   = "error"

# Windows Firewall rule name prefix for the IT WebSocket server port.
_FW_RULE_PREFIX = "TheWatcher-IT-WS"


class SettingsBridge(QObject):
    """
    Exposes persisted per-PC user config and read-only app settings to QML.

    Writable (persisted to user_config.json immediately):
    - clipsDir            — output directory for combined clips
    - driverIndex         — encoder hardware: auto / nvidia / intel / amd / cpu
    - codec               — "h264" | "hevc"
    - autostart           — launch with Windows (Run registry key)
    - autorecord          — begin the rolling buffer on launch
    - role                — "operator" | "supervisor" | "it" | "" (not configured)

    Read-only (from Settings / .env):
    - captureFramerate, outputResolution, segmentDuration, retentionHours, …

    Role system:
    - ``role == ""`` → first-run wizard shown by QML (RoleSetupWizard.qml)
    - ``isITUnlocked`` → transient session flag; set via ``unlockIT(pin)``
    - ``setRole`` only allowed if role==IT or isITUnlocked
    - PIN is validated against ``settings.it_pin`` (from IT_PIN in .env)
    """

    clipsDirChanged      = Signal()
    encoderInfoChanged   = Signal()
    encoderChanged       = Signal()
    systemChanged        = Signal()
    restartStateChanged  = Signal()
    roleChanged          = Signal()
    itWsHostsChanged     = Signal(list)
    itWsPortStatusChanged = Signal()

    def __init__(
        self,
        user_config_port: UserConfigPort,
        settings: Settings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._port = user_config_port
        self._settings = settings
        cfg = self._port.load()
        self._clips_dir: str = cfg.clips_dir or str(settings.clips_dir)
        self._driver: str = cfg.driver if cfg.driver in _DRIVERS else "auto"
        self._codec: str = (cfg.codec or settings.video_codec or "hevc").lower()
        self._autorecord: bool = cfg.autorecord
        self._role: str = cfg.role
        self._it_ws_hosts: list = list(cfg.it_ws_hosts)
        self._it_unlocked: bool = False
        self._restart_state: str = _RESTART_IDLE
        self._restart_cb: Optional[Callable[[str, str], None]] = None
        self._it_ws_port_status: str = "unknown"  # unknown | open | closed | opening | error

    def set_restart_callback(self, callback: Callable[[str, str], None]) -> None:
        """Register the restart function from main.py.

        Signature: ``callback(codec: str, driver: str) -> None``
        Called in a background thread — must be thread-safe and not touch Qt directly.
        """
        self._restart_cb = callback

    # ── Read-only Settings (from .env) ────────────────────────────────

    @Property(str, notify=clipsDirChanged)
    def clipsDir(self) -> str:
        return self._clips_dir

    @Property(str, notify=encoderInfoChanged)
    def captureFramerate(self) -> str:
        return str(self._settings.capture_framerate)

    @Property(str, notify=encoderInfoChanged)
    def outputResolution(self) -> str:
        return f'{self._settings.output_width}×{self._settings.output_height}'

    @Property(int, notify=encoderInfoChanged)
    def segmentDuration(self) -> int:
        return self._settings.segment_duration

    @Property(int, notify=encoderInfoChanged)
    def retentionHours(self) -> int:
        return self._settings.retention_hours

    @Property(int, notify=encoderInfoChanged)
    def eventPreSeconds(self) -> int:
        return self._settings.event_pre_seconds

    @Property(int, notify=encoderInfoChanged)
    def eventPostSeconds(self) -> int:
        return self._settings.event_post_seconds

    @Property(int, notify=encoderInfoChanged)
    def eventCooldownSeconds(self) -> int:
        return self._settings.event_cooldown_seconds

    # ── Encoder / driver (persisted) ──────────────────────────────────

    @Property(int, notify=encoderChanged)
    def driverIndex(self) -> int:
        return _DRIVERS.index(self._driver)

    @Property(str, notify=encoderChanged)
    def codec(self) -> str:
        return self._codec

    @Property(str, notify=restartStateChanged)
    def restartState(self) -> str:
        return self._restart_state

    # ── Role (persisted) ──────────────────────────────────────────────

    @Property(str, notify=roleChanged)
    def role(self) -> str:
        return self._role

    @Property(bool, notify=roleChanged)
    def isITUnlocked(self) -> bool:
        return self._it_unlocked

    # ── System (persisted / registry) ─────────────────────────────────

    @Property(bool, notify=systemChanged)
    def autostart(self) -> bool:
        return autostart.is_autostart_enabled()

    @Property(bool, notify=systemChanged)
    def autorecord(self) -> bool:
        return self._autorecord

    # ── Slots ─────────────────────────────────────────────────────────

    @Slot(str)
    def setClipsDir(self, path: str) -> None:
        if path == self._clips_dir:
            return
        self._clips_dir = path
        Path(path).mkdir(parents=True, exist_ok=True)
        self._persist(lambda c: setattr(c, "clips_dir", path))
        self.clipsDirChanged.emit()

    @Slot(int)
    def setDriverIndex(self, index: int) -> None:
        if not (0 <= index < len(_DRIVERS)):
            return
        driver = _DRIVERS[index]
        if driver == self._driver:
            return
        self._driver = driver
        self._persist(lambda c: setattr(c, "driver", driver))
        encoder_selector.set_preferences(driver=driver)
        logger.info("Encoder driver set to '{}' (live recording applies on restart).", driver)
        self.encoderChanged.emit()

    @Slot(str)
    def setCodec(self, codec: str) -> None:
        codec = (codec or "").lower()
        if codec not in ("h264", "hevc") or codec == self._codec:
            return
        self._codec = codec
        self._persist(lambda c: setattr(c, "codec", codec))
        logger.info("Codec set to '{}' (applies to new recordings/clips).", codec)
        self.encoderChanged.emit()

    @Slot()
    def applyEncoderNow(self) -> None:
        """Restart the live recording with the current driver and codec."""
        if self._restart_cb is None:
            logger.warning("applyEncoderNow: no restart callback registered.")
            return
        if self._restart_state == _RESTART_RUNNING:
            return

        codec  = self._codec
        driver = self._driver

        def _run() -> None:
            self._set_restart_state(_RESTART_RUNNING)
            try:
                self._restart_cb(codec, driver)
                self._set_restart_state(_RESTART_DONE)
                threading.Timer(3.0, lambda: self._set_restart_state(_RESTART_IDLE)).start()
            except Exception:
                logger.exception("applyEncoderNow: restart callback raised.")
                self._set_restart_state(_RESTART_ERROR)
                threading.Timer(4.0, lambda: self._set_restart_state(_RESTART_IDLE)).start()

        threading.Thread(target=_run, daemon=True, name="encoder-restart").start()

    @Slot(bool)
    def setAutostart(self, enabled: bool) -> None:
        autostart.set_autostart(enabled)
        self.systemChanged.emit()

    @Slot(bool)
    def setAutorecord(self, enabled: bool) -> None:
        if enabled == self._autorecord:
            return
        self._autorecord = enabled
        self._persist(lambda c: setattr(c, "autorecord", enabled))
        self.systemChanged.emit()

    # ── Role slots ────────────────────────────────────────────────────

    @Slot(str)
    def setRole(self, role: str) -> None:
        """Persist a role change.

        Allowed when:
        - role == "" (first-run wizard — no existing role set)
        - current role == IT
        - isITUnlocked (PIN was verified this session)
        """
        role = (role or "").lower()
        if role not in VALID_ROLES:
            logger.warning("setRole: invalid role '{}' — ignored.", role)
            return
        if self._role not in ("", IT) and not self._it_unlocked:
            logger.warning("setRole: not authorised (role={}, unlocked={}).", self._role, self._it_unlocked)
            return
        if role == self._role:
            return
        self._role = role
        self._persist(lambda c: setattr(c, "role", role))
        logger.info("Role set to '{}'.", role)
        self.roleChanged.emit()

    @Slot(str, result=bool)
    def unlockIT(self, pin: str) -> bool:
        """Validate the IT PIN. Returns True and sets isITUnlocked on match."""
        correct = pin == self._settings.it_pin
        if correct and not self._it_unlocked:
            self._it_unlocked = True
            logger.info("IT access unlocked for this session.")
            self.roleChanged.emit()
        elif not correct:
            logger.warning("unlockIT: wrong PIN attempt.")
        return correct

    # ── IT WS hosts (Supervisor config) ──────────────────────────────

    @Property('QVariantList', notify=systemChanged)
    def itWsHosts(self) -> list:
        return list(self._it_ws_hosts)

    @Slot(str)
    def addItWsHost(self, host: str) -> None:
        host = host.strip()
        if not host or host in self._it_ws_hosts:
            return
        self._it_ws_hosts.append(host)
        self._persist(lambda c: setattr(c, "it_ws_hosts", list(self._it_ws_hosts)))
        self.systemChanged.emit()
        self.itWsHostsChanged.emit(list(self._it_ws_hosts))

    @Slot(str)
    def removeItWsHost(self, host: str) -> None:
        if host not in self._it_ws_hosts:
            return
        self._it_ws_hosts.remove(host)
        self._persist(lambda c: setattr(c, "it_ws_hosts", list(self._it_ws_hosts)))
        self.systemChanged.emit()
        self.itWsHostsChanged.emit(list(self._it_ws_hosts))

    @Slot()
    def lockIT(self) -> None:
        """Re-lock IT access for this session."""
        if self._it_unlocked:
            self._it_unlocked = False
            logger.info("IT access locked.")
            self.roleChanged.emit()

    # ── IT WS port / firewall ─────────────────────────────────────────

    @Property(str, notify=itWsPortStatusChanged)
    def itWsPortStatus(self) -> str:
        return self._it_ws_port_status

    @Property(int, notify=encoderInfoChanged)
    def itWsPort(self) -> int:
        return self._settings.it_ws_port

    @Slot()
    def checkItWsPortStatus(self) -> None:
        """Check whether the Windows Firewall inbound rule for the IT WS port exists."""
        def _run() -> None:
            port = self._settings.it_ws_port
            rule = f"{_FW_RULE_PREFIX}-{port}"
            try:
                result = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule}"],
                    capture_output=True, text=True, timeout=8,
                )
                open_ = result.returncode == 0 and "No rules match" not in result.stdout
                self._it_ws_port_status = "open" if open_ else "closed"
            except Exception:
                self._it_ws_port_status = "unknown"
            self.itWsPortStatusChanged.emit()

        threading.Thread(target=_run, daemon=True, name="fw-check").start()

    @Slot()
    def openItWsPort(self) -> None:
        """Add a Windows Firewall inbound TCP rule for the IT WS port.

        Requires the process to have Administrator privileges.
        Sets itWsPortStatus to 'error' and logs a warning if it fails.
        """
        self._it_ws_port_status = "opening"
        self.itWsPortStatusChanged.emit()

        def _run() -> None:
            port = self._settings.it_ws_port
            rule = f"{_FW_RULE_PREFIX}-{port}"
            try:
                # Remove stale rule first (ignore errors)
                subprocess.run(
                    ["netsh", "advfirewall", "firewall", "delete", "rule", f"name={rule}"],
                    capture_output=True, timeout=8,
                )
                result = subprocess.run(
                    [
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        f"name={rule}",
                        "dir=in", "action=allow", "protocol=TCP",
                        f"localport={port}",
                        "profile=any",
                    ],
                    capture_output=True, text=True, timeout=8,
                )
                if result.returncode == 0:
                    self._it_ws_port_status = "open"
                    logger.info("Firewall rule added for IT WS port {}.", port)
                else:
                    self._it_ws_port_status = "error"
                    logger.warning(
                        "Failed to add firewall rule for port {}: {}",
                        port, result.stderr.strip() or result.stdout.strip(),
                    )
            except Exception:
                self._it_ws_port_status = "error"
                logger.exception("openItWsPort: subprocess error.")
            self.itWsPortStatusChanged.emit()

        threading.Thread(target=_run, daemon=True, name="fw-open").start()

    # ── Helpers ───────────────────────────────────────────────────────

    def _set_restart_state(self, state: str) -> None:
        self._restart_state = state
        self.restartStateChanged.emit()

    def _persist(self, mutate) -> None:
        """Load → mutate → save the user config (single source of truth on disk)."""
        cfg = self._port.load()
        mutate(cfg)
        self._port.save(cfg)
