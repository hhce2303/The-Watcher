"""Per-role capability policy — the single source of truth for what each role can do.

Historically the operator's rules were scattered across QML conditionals
(``role === "operator"``), ``enforce_role()`` and the tray menu.  This module
centralises them: every "can the X role do Y?" question is answered here, once.

Consumers:
  - Python: ``role.py`` (enforce_role / recording gates), ``tray_icon.py``
    (Exit item), ``settings_bridge.setRole`` (role-change authorisation).
  - QML:    ``main.py`` exposes ``policy_for(role).as_dict()`` once as the
    ``Policy`` context property (the role is constant for the life of the
    process — it only changes via a relaunch — so a constant map is enough).
    The one thing that DOES change at runtime, the transient IT-unlock, stays
    in ``SettingsBridge.isITUnlocked`` (which already emits ``roleChanged``).

Pure domain: no Qt, no I/O, no infrastructure imports.

                          operator  supervisor   it    "" (unconfigured)
  can_close_window           F          T         T          T
  can_minimize_window        F          T         T          T
  can_exit_from_tray         F          T         T          T
  records                    T          F         T          F
  records_on_launch_forced   T          F         F          F
  can_stop_recording         F          T         T          T
  can_open_settings          F          T         T          T
  visible_tabs             (0,)       (1,)       ()         ()      ()==all
  can_change_role            F          F         T          T
  recording_indicator_locked T          F         F          F
  watchdog_enabled           T          F         F          F
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.role import IT, OPERATOR, SUPERVISOR


@dataclass(frozen=True)
class RolePolicy:
    """Immutable set of capabilities for one role.

    ``records`` vs ``records_on_launch_forced`` are split on purpose so a single
    bool never has to lie about IT: IT *can* record (``records=True``) but is
    not *forced* to at launch (``records_on_launch_forced=False`` — it honours
    the persisted autorecord toggle).
    """

    # Window lifecycle
    can_close_window: bool
    can_minimize_window: bool
    can_exit_from_tray: bool
    # Recording
    records: bool
    records_on_launch_forced: bool
    can_stop_recording: bool
    # Navigation / settings
    can_open_settings: bool
    visible_tabs: tuple[int, ...]  # () means "all tabs visible"
    # Inter-role
    can_change_role: bool  # standing capability WITHOUT a PIN unlock (IT + "")
    # New rules
    recording_indicator_locked: bool  # persistent, undismissable REC overlay
    watchdog_enabled: bool             # register the process restart watchdog

    def as_dict(self) -> dict:
        """camelCase map for the QML ``Policy`` context property.

        QML reads e.g. ``Policy.canMinimizeWindow`` / ``Policy.visibleTabs``.
        Keys are camelCase to match QML idiom; ``visible_tabs`` becomes a list.
        """
        return {
            "canCloseWindow": self.can_close_window,
            "canMinimizeWindow": self.can_minimize_window,
            "canExitFromTray": self.can_exit_from_tray,
            "records": self.records,
            "recordsOnLaunchForced": self.records_on_launch_forced,
            "canStopRecording": self.can_stop_recording,
            "canOpenSettings": self.can_open_settings,
            "visibleTabs": list(self.visible_tabs),
            "canChangeRole": self.can_change_role,
            "recordingIndicatorLocked": self.recording_indicator_locked,
            "watchdogEnabled": self.watchdog_enabled,
        }


_OPERATOR = RolePolicy(
    can_close_window=False,
    can_minimize_window=False,
    can_exit_from_tray=False,
    records=True,
    records_on_launch_forced=True,
    can_stop_recording=False,
    can_open_settings=False,
    visible_tabs=(0,),
    can_change_role=False,
    recording_indicator_locked=True,
    watchdog_enabled=True,
)

_SUPERVISOR = RolePolicy(
    can_close_window=True,
    can_minimize_window=True,
    can_exit_from_tray=True,
    records=False,
    records_on_launch_forced=False,
    can_stop_recording=True,
    can_open_settings=True,
    visible_tabs=(1,),
    can_change_role=False,
    recording_indicator_locked=False,
    watchdog_enabled=False,
)

_IT = RolePolicy(
    can_close_window=True,
    can_minimize_window=True,
    can_exit_from_tray=True,
    records=True,
    records_on_launch_forced=False,  # honours the persisted autorecord toggle
    can_stop_recording=True,
    can_open_settings=True,
    visible_tabs=(),  # all tabs (the full-screen IT editor is handled separately)
    can_change_role=True,
    recording_indicator_locked=False,
    watchdog_enabled=False,
)

# Unconfigured machine (role == ""): inert until the role wizard runs.  It must
# be able to change role (first-run wizard) but never record.
_UNCONFIGURED = RolePolicy(
    can_close_window=True,
    can_minimize_window=True,
    can_exit_from_tray=True,
    records=False,
    records_on_launch_forced=False,
    can_stop_recording=True,
    can_open_settings=True,
    visible_tabs=(),
    can_change_role=True,
    recording_indicator_locked=False,
    watchdog_enabled=False,
)

_BY_ROLE = {
    OPERATOR: _OPERATOR,
    SUPERVISOR: _SUPERVISOR,
    IT: _IT,
}


def policy_for(role: str) -> RolePolicy:
    """Return the capability policy for ``role`` ("" / unknown → unconfigured)."""
    return _BY_ROLE.get(role, _UNCONFIGURED)
