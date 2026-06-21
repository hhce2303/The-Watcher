from __future__ import annotations

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
    """
    return role in RECORDING_ROLES


def default_autorecord_for_role(role: str) -> bool:
    """The autorecord value to persist when a machine is first configured.

    Operator is an always-on recorder (True).  IT records only when explicitly
    enabled (False — opt-in from Settings).  Supervisor and "" never record.
    """
    return role == OPERATOR


def should_autorecord_on_launch(role: str, autorecord: bool) -> bool:
    """Whether to start recording at launch for this role + persisted toggle.

    Operator always records; IT honours its persisted ``autorecord`` toggle;
    Supervisor and the unconfigured "" state never start recording.
    """
    if role == OPERATOR:
        return True
    if role == IT:
        return autorecord
    return False


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
    user_config,       # UserConfig — avoid circular import, duck-typed
    autostart_module,  # app.infrastructure.autostart
) -> None:
    """Apply per-role constraints to user_config and OS autostart.

    Called once in main.py immediately after user_config is loaded.
    Mutates user_config in-place; does NOT persist (avoids overwriting
    user preferences on every launch).
    """
    if role == OPERATOR:
        user_config.autorecord = True
        autostart_module.set_autostart(True)
    elif role == SUPERVISOR:
        user_config.autorecord = False
    elif role == "":
        # Unconfigured machine: never record until the role wizard runs.
        user_config.autorecord = False
    # IT: no constraints — honours the persisted autorecord toggle.
