"""TLS material providers selected by ``TLS_PROVISIONING_MODE`` (ADR-0023)."""
from __future__ import annotations

from app.adapters.tls_provisioning.file_adapter import FileTlsMaterialAdapter
from app.core.ports.tls_material_port import TlsMaterialError, TlsMaterialPort


def build_tls_material(settings) -> TlsMaterialPort:
    mode = settings.tls_provisioning_mode
    if mode == "file":
        return FileTlsMaterialAdapter(settings.live_view_cert_file, settings.live_view_key_file)
    if mode == "remote":
        raise TlsMaterialError("TLS_PROVISIONING_MODE=remote is not implemented yet (ADR-0023 phase 3)")
    raise TlsMaterialError(f"Unknown TLS_PROVISIONING_MODE: {mode!r}")


__all__ = ["FileTlsMaterialAdapter", "build_tls_material"]
