"""TLS material providers selected by ``TLS_PROVISIONING_MODE`` (ADR-0023)."""
from __future__ import annotations

from urllib.parse import urlparse

from app.adapters.browser_local.identity import DeviceIdentityStore
from app.adapters.tls_provisioning.file_adapter import FileTlsMaterialAdapter
from app.adapters.tls_provisioning.remote_adapter import RemoteTlsMaterialAdapter
from app.core.ports.tls_material_port import TlsMaterialError, TlsMaterialPort


def build_tls_material(settings) -> TlsMaterialPort:
    mode = settings.tls_provisioning_mode
    if mode == "file":
        return FileTlsMaterialAdapter(settings.live_view_cert_file, settings.live_view_key_file)
    if mode == "remote":
        hostname = urlparse(settings.live_view_origin).hostname
        if not hostname:
            raise TlsMaterialError(
                "LIVE_VIEW_ORIGIN must have a hostname for TLS_PROVISIONING_MODE=remote"
            )
        identity = DeviceIdentityStore(settings.browser_local_data_dir).load_or_create()
        return RemoteTlsMaterialAdapter(
            issuance_url=settings.tls_provisioning_url,
            pinned_ca_file=settings.tls_provisioning_pinned_ca_file,
            timeout_seconds=settings.tls_provisioning_timeout_seconds,
            material_dir=settings.tls_provisioning_material_dir,
            station_id=settings.live_view_station_id,
            expected_hostname=hostname,
            identity=identity,
        )
    raise TlsMaterialError(f"Unknown TLS_PROVISIONING_MODE: {mode!r}")


__all__ = ["FileTlsMaterialAdapter", "build_tls_material"]
