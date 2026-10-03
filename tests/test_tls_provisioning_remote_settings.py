"""Settings for TLS_PROVISIONING_MODE=remote (ADR-0023 phase 3).

Additive only: defaults must not change ``file``-mode behaviour (the existing
``tls_provisioning_mode``/``live_view_cert_file``/``live_view_key_file``
fields and their tests in ``tests/test_tls_material.py`` are untouched).
"""
from __future__ import annotations

import importlib
import os

import pytest

from app.infrastructure import config as config_module


@pytest.fixture()
def reloaded_config(monkeypatch):
    """Reload ``app.infrastructure.config`` so env vars set in a test take effect.

    Settings fields are evaluated at class-body (import) time, so overriding an
    env var only takes effect through a fresh module reload, then reset back to
    the unmodified module for later tests/imports elsewhere in the suite.
    """

    def _reload():
        return importlib.reload(config_module)

    yield _reload
    importlib.reload(config_module)


def test_defaults_are_safe_and_additive_with_no_env_set(monkeypatch, reloaded_config):
    for key in (
        "TLS_PROVISIONING_URL",
        "TLS_PROVISIONING_PINNED_CA_FILE",
        "TLS_PROVISIONING_TIMEOUT_SECONDS",
        "TLS_PROVISIONING_MATERIAL_DIR",
    ):
        monkeypatch.delenv(key, raising=False)
    module = reloaded_config()

    settings = module.Settings()

    assert settings.tls_provisioning_url == ""
    assert settings.tls_provisioning_pinned_ca_file == ""
    assert 0 < settings.tls_provisioning_timeout_seconds <= 60
    assert str(settings.tls_provisioning_material_dir)  # a real, non-empty default path
    # Existing file-mode default is untouched by the new remote-mode settings.
    assert settings.tls_provisioning_mode == "file"


def test_url_and_timeout_are_read_from_env(monkeypatch, reloaded_config):
    monkeypatch.setenv("TLS_PROVISIONING_URL", "https://certs.internal.lan")
    monkeypatch.setenv("TLS_PROVISIONING_TIMEOUT_SECONDS", "7.5")
    module = reloaded_config()

    settings = module.Settings()

    assert settings.tls_provisioning_url == "https://certs.internal.lan"
    assert settings.tls_provisioning_timeout_seconds == 7.5


def test_pinned_ca_file_is_resolved_like_other_file_settings(monkeypatch, reloaded_config, tmp_path):
    ca = tmp_path / "issuance-ca.pem"
    ca.write_text("not-a-real-ca-just-a-test-path-marker")
    monkeypatch.setenv("TLS_PROVISIONING_PINNED_CA_FILE", str(ca))
    module = reloaded_config()

    settings = module.Settings()

    assert settings.tls_provisioning_pinned_ca_file == str(ca)


def test_material_dir_is_resolved_like_other_dir_settings(monkeypatch, reloaded_config, tmp_path):
    target = tmp_path / "tls_material"
    monkeypatch.setenv("TLS_PROVISIONING_MATERIAL_DIR", str(target))
    module = reloaded_config()

    settings = module.Settings()

    assert settings.tls_provisioning_material_dir == target
