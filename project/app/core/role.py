from __future__ import annotations

OPERATOR  = "operator"
SUPERVISOR = "supervisor"
IT        = "it"
VALID_ROLES = {OPERATOR, SUPERVISOR, IT}


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
    # IT: no constraints — full access
