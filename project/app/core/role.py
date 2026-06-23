from __future__ import annotations

from loguru import logger

OPERATOR  = "operator"
SUPERVISOR = "supervisor"
IT        = "it"
VALID_ROLES = {OPERATOR, SUPERVISOR, IT}

# Roles whose machines build the recording stack.  Supervisor never records;
# an unconfigured machine ("") stays inert until the role wizard sets a role.
RECORDING_ROLES = {OPERATOR, IT}


def is_recording_role(role: str) -> bool:
    """True if this role's machine builds the recording stack at all.

    Operator and IT can record; Supervisor and the unconfigured "" state never
    build recorders, so a freshly deployed machine launches inert (tray + role
    wizard, zero FFmpeg) until a role is chosen.

    Delegates to the policy engine — the single source of truth for role caps.
    """
    from app.core.policy import policy_for  # noqa: PLC0415 (avoid import cycle)
    return policy_for(role).records


def default_autorecord_for_role(role: str) -> bool:
    """The autorecord value to persist when a machine is first configured.

    Operator is an always-on recorder (True).  IT records only when explicitly
    enabled (False — opt-in from Settings).  Supervisor and "" never record.
    """
    from app.core.policy import policy_for  # noqa: PLC0415 (avoid import cycle)
    return policy_for(role).records_on_launch_forced


def should_autorecord_on_launch(role: str, autorecord: bool) -> bool:
    """Whether to start recording at launch for this role + persisted toggle.

    Operator always records; IT honours its persisted ``autorecord`` toggle;
    Supervisor and the unconfigured "" state never start recording.
    """
    from app.core.policy import policy_for  # noqa: PLC0415 (avoid import cycle)
    p = policy_for(role)
    return p.records_on_launch_forced or (p.records and autorecord)


def role_label(role: str) -> str:
    return {
        OPERATOR:  "Operador",
        SUPERVISOR: "Supervisor",
        IT:        "IT",
    }.get(role, "Desconocido")


def role_description(role: str) -> str:
    return {
        OPERATOR: (
            "Monitoreo 24/7. Graba continuamente todas las pantallas "
            "asignadas. La ventana no puede cerrarse; la grabación nunca se "
            "interrumpe. Sin acceso a ajustes ni clips."
        ),
        SUPERVISOR: (
            "Auditoría y revisión. Accede al reproductor de clips desde la "
            "red o unidad local. No graba. Ideal para estaciones cliente de "
            "supervisión."
        ),
        IT: (
            "Administración completa. Ajustes, encoder, almacenamiento, "
            "editor de clips y cambio de rol con PIN. Para el personal "
            "técnico responsable del despliegue."
        ),
    }.get(role, "")


def enforce_role(
    role: str,
    user_config,            # UserConfig — avoid circular import, duck-typed
    autostart_module,       # app.infrastructure.autostart
    scheduled_task_module=None,  # app.infrastructure.scheduled_task (operator only)
) -> str | None:
    """Apply per-role constraints to user_config and the OS launcher.

    Called once in main.py immediately after user_config is loaded.
    Mutates user_config in-place; does NOT persist (avoids overwriting
    user preferences on every launch).

    Returns the operator launcher status ("task" | "runkey") so main.py can
    surface a degraded state, or None for non-operator roles.

    Capabilities come from the policy engine (single source of truth):
      - records_on_launch_forced (operator) → autorecord forced True.
      - not records (supervisor / "")       → autorecord forced False.
      - records but not forced (IT)          → autorecord left untouched.
    """
    from app.core.policy import policy_for  # noqa: PLC0415 (avoid import cycle)
    p = policy_for(role)

    if p.records_on_launch_forced:
        user_config.autorecord = True
    elif not p.records:
        user_config.autorecord = False
    # else: IT — honour the persisted autorecord toggle.

    if p.watchdog_enabled:
        return _setup_operator_launcher(autostart_module, scheduled_task_module)
    return None


def _setup_operator_launcher(autostart_module, scheduled_task_module) -> str:
    """Set up the operator's restart watchdog.

    A Windows Scheduled Task (restart-on-failure) is the SOLE launcher for the
    operator and replaces the HKCU Run key — keeping both would race two
    launchers at login on the single-instance mutex.  If the task can't be
    registered (corporate group policy / permissions), fall back to the Run key
    so at least login autostart survives; the kill-restart guarantee is then
    absent and main.py surfaces the degraded state.

      register task OK  → remove Run key, return "task"
      register fails    → keep Run key,   return "runkey" (degraded)
    """
    if scheduled_task_module is not None:
        try:
            if scheduled_task_module.ensure_registered():
                autostart_module.set_autostart(False)  # task is the sole launcher
                return "task"
        except Exception:  # noqa: BLE001 — registration must never crash startup
            logger.exception("enforce_role: scheduled task registration failed.")
    autostart_module.set_autostart(True)
    logger.warning(
        "Operator restart watchdog degraded: scheduled task unavailable — "
        "using HKCU Run-key fallback (login autostart only, no restart after a kill)."
    )
    return "runkey"
