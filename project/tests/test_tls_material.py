"""TlsMaterialPort file mode (ADR-0023 phase 1): behaviour-preserving, fails closed."""
from __future__ import annotations

import ssl
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.tls_provisioning import build_tls_material
from app.adapters.tls_provisioning.file_adapter import FileTlsMaterialAdapter
from app.core.ports.tls_material_port import TlsMaterial, TlsMaterialError, TlsMaterialPort


def _files(tmp_path: Path) -> tuple[Path, Path]:
    cert, key = tmp_path / "live-view.pem", tmp_path / "live-view-key.pem"
    cert.write_text("cert")
    key.write_text("key")
    return cert, key


def test_file_adapter_returns_configured_paths(tmp_path):
    cert, key = _files(tmp_path)
    ca = tmp_path / "ca.pem"
    ca.write_text("ca")
    port: TlsMaterialPort = FileTlsMaterialAdapter(str(cert), str(key), (str(ca),))
    assert port.ensure() == TlsMaterial(str(cert), str(key), (str(ca),))


@pytest.mark.parametrize("missing", ["cert", "key"])
def test_file_adapter_fails_closed_when_a_file_is_missing(tmp_path, missing):
    cert, key = _files(tmp_path)
    {"cert": cert, "key": key}[missing].unlink()
    with pytest.raises(TlsMaterialError, match="LIVE_VIEW_CERT_FILE and LIVE_VIEW_KEY_FILE"):
        FileTlsMaterialAdapter(str(cert), str(key)).ensure()


def test_file_adapter_fails_closed_on_empty_paths():
    with pytest.raises(TlsMaterialError):
        FileTlsMaterialAdapter("", "").ensure()


def test_factory_defaults_to_file_mode_from_live_view_settings(tmp_path):
    cert, key = _files(tmp_path)
    settings = SimpleNamespace(
        tls_provisioning_mode="file", live_view_cert_file=str(cert), live_view_key_file=str(key)
    )
    assert build_tls_material(settings).ensure().cert_file == str(cert)


def test_factory_rejects_unimplemented_remote_mode():
    settings = SimpleNamespace(tls_provisioning_mode="remote", live_view_cert_file="", live_view_key_file="")
    with pytest.raises(TlsMaterialError, match="remote"):
        build_tls_material(settings)


def test_factory_rejects_unknown_mode():
    settings = SimpleNamespace(tls_provisioning_mode="bogus", live_view_cert_file="", live_view_key_file="")
    with pytest.raises(TlsMaterialError, match="bogus"):
        build_tls_material(settings)


def test_server_validate_uses_the_port_not_settings_paths(tmp_path):
    from app.adapters.live_view_lan.server import LiveViewLanAdapter

    class _Failing(TlsMaterialPort):
        def ensure(self):
            raise TlsMaterialError("no material")

    adapter = object.__new__(LiveViewLanAdapter)
    adapter._settings = SimpleNamespace(
        live_view_origin="https://op.lan:8767",
        live_view_parent_origin="https://daily.sig.systems",
        live_view_max_viewers=3,
        live_view_cert_file="would-pass-if-read.pem",  # must be ignored
    )
    adapter._tls = _Failing()
    with pytest.raises(TlsMaterialError):
        adapter._validate()
    assert hasattr(ssl, "SSLContext")
