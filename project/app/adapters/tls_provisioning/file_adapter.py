"""``file`` mode: TLS material already provisioned on disk (the pre-ADR-0023 behaviour)."""
from __future__ import annotations

from pathlib import Path

from app.core.ports.tls_material_port import TlsMaterial, TlsMaterialError, TlsMaterialPort


class FileTlsMaterialAdapter(TlsMaterialPort):
    def __init__(self, cert_file: str, key_file: str, ca_files: tuple[str, ...] = ()) -> None:
        self._material = TlsMaterial(cert_file, key_file, ca_files)

    def ensure(self) -> TlsMaterial:
        m = self._material
        if not m.cert_file or not m.key_file or not Path(m.cert_file).is_file() or not Path(m.key_file).is_file():
            raise TlsMaterialError("LIVE_VIEW_CERT_FILE and LIVE_VIEW_KEY_FILE are required")
        return m
