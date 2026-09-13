"""Security and TLS spike tests for the external Daily browser channel."""
from __future__ import annotations

import json
import socket
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from cryptography.x509.oid import NameOID

from app.adapters.browser_local.auth import AuthenticationError
from app.adapters.browser_local.server import BrowserLocalAdapter
from app.core.api import dto


class _Subscription:
    def cancel(self) -> None:
        return None


class _Bus:
    def subscribe(self, _event_types, _callback) -> _Subscription:
        return _Subscription()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_tls_material(folder: Path) -> tuple[Path, Path]:
    key = generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = folder / "localhost.pem"
    key_path = folder / "localhost-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _make_adapter(tmp_path: Path) -> tuple[BrowserLocalAdapter, Ed25519PrivateKey, Path]:
    clips_root = tmp_path / "clips"
    clips_root.mkdir()
    clip = clips_root / "safe.mp4"
    clip.write_bytes(b"0123456789")
    segment_dir = tmp_path / "segments"
    (segment_dir / "m0").mkdir(parents=True)
    (segment_dir / "m0" / "preview.jpg").write_bytes(b"not-a-real-jpeg")
    cert, key = _write_tls_material(tmp_path)
    issuer_key = Ed25519PrivateKey.generate()
    issuer_public = tmp_path / "daily-issuer-public.pem"
    issuer_public.write_bytes(
        issuer_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    port = _free_port()
    settings = SimpleNamespace(
        browser_local_enabled=True,
        browser_local_port=port,
        browser_local_parent_origin="https://daily.sig.systems",
        browser_local_issuer="daily.sig.systems",
        browser_local_audience="the-watcher-local",
        browser_local_issuer_kid="watcher-ed25519-test",
        browser_local_station_id=23,
        browser_local_cert_file=str(cert),
        browser_local_key_file=str(key),
        browser_local_issuer_public_key_file=str(issuer_public),
        browser_local_data_dir=tmp_path / "identity",
        segment_dir=segment_dir,
    )
    api = SimpleNamespace(
        bus=_Bus(),
        clips=SimpleNamespace(
            list_clips=lambda: [
                dto.ClipDTO(
                    clip_name=clip.name,
                    path=str(clip),
                    size_label="1 MB",
                    date_label="Hoy",
                    is_event=False,
                )
            ]
        ),
        recording=SimpleNamespace(
            get_monitors=lambda: [SimpleNamespace(name="Monitor 0", index=0, resolution="1920x1080")]
        ),
    )
    return BrowserLocalAdapter(settings, api, clip_roots=(clips_root,)), issuer_key, clip


def _assertion(
    adapter: BrowserLocalAdapter,
    key: Ed25519PrivateKey,
    *,
    jti: str = "jti-one",
    ttl_seconds: int = 60,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": "daily.sig.systems",
            "aud": "the-watcher-local",
            "sub": "42",
            "device_id": adapter.enrollment_payload["device_id"],
            "station_id": 23,
            "scope": ["recordings:read", "preview:read"],
            "nonce": "n" * 32,
            "jti": jti,
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(seconds=ttl_seconds),
        },
        key,
        algorithm="EdDSA",
        headers={"kid": "watcher-ed25519-test"},
    )


def _open(url: str, headers: dict[str, str] | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=5)  # noqa: S501


def test_browser_local_tls_csp_loopback_and_range(tmp_path: Path) -> None:
    adapter, issuer_key, clip = _make_adapter(tmp_path)
    assert adapter.start()
    try:
        base = f"https://127.0.0.1:{adapter._settings.browser_local_port}"  # noqa: SLF001
        with _open(f"{base}/api/v1/health") as response:
            health = json.loads(response.read())
            assert health["device_id"] == adapter.enrollment_payload["device_id"]
            assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
            assert "frame-ancestors https://daily.sig.systems" in response.headers["Content-Security-Policy"]
            assert response.headers["Referrer-Policy"] == "no-referrer"
            assert "X-Frame-Options" not in response.headers

        with pytest.raises(urllib.error.HTTPError) as denied:
            _open(f"{base}/api/v1/clips")
        assert denied.value.code == 401

        request = urllib.request.Request(
            f"{base}/api/v1/bootstrap/sign",
            data=json.dumps({"nonce": "n" * 32}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
        )
        with pytest.raises(urllib.error.HTTPError) as bad_origin:
            urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=5)  # noqa: S501
        assert bad_origin.value.code == 403

        session = adapter._sessions.open_session(_assertion(adapter, issuer_key))  # noqa: SLF001
        capability = adapter._sessions.issue_capability(session, clip, "media")  # noqa: SLF001
        with _open(f"{base}/media/{capability}", {"Range": "bytes=0-3"}) as response:
            assert response.status == 206
            assert response.read() == b"0123"
            assert response.headers["Content-Range"] == "bytes 0-3/10"

        outside = tmp_path / "not-allowed.mp4"
        outside.write_bytes(b"no")
        outside_capability = adapter._sessions.issue_capability(session, outside, "media")  # noqa: SLF001
        with pytest.raises(urllib.error.HTTPError) as forbidden_path:
            _open(f"{base}/media/{outside_capability}")
        assert forbidden_path.value.code == 404
    finally:
        adapter.stop()


def test_assertion_is_single_use_and_bound_to_device_and_station(tmp_path: Path) -> None:
    adapter, issuer_key, _clip = _make_adapter(tmp_path)
    assertion = _assertion(adapter, issuer_key)
    assert adapter._sessions.open_session(assertion).subject == "42"  # noqa: SLF001
    with pytest.raises(AuthenticationError, match="replay"):
        adapter._sessions.open_session(assertion)  # noqa: SLF001

    wrong_device = jwt.decode(assertion, options={"verify_signature": False})
    wrong_device["device_id"] = "00000000-0000-4000-8000-000000000000"
    wrong_device["jti"] = "jti-two"
    invalid = jwt.encode(
        wrong_device, issuer_key, algorithm="EdDSA", headers={"kid": "watcher-ed25519-test"}
    )
    with pytest.raises(AuthenticationError, match="device mismatch"):
        adapter._sessions.open_session(invalid)  # noqa: SLF001

    wrong_key = jwt.encode(
        jwt.decode(_assertion(adapter, issuer_key, jti="jti-three"), options={"verify_signature": False}),
        issuer_key,
        algorithm="EdDSA",
        headers={"kid": "unexpected-key"},
    )
    with pytest.raises(AuthenticationError, match="key rejected"):
        adapter._sessions.open_session(wrong_key)  # noqa: SLF001

    expired = _assertion(adapter, issuer_key, jti="jti-expired", ttl_seconds=-1)
    with pytest.raises(AuthenticationError, match="assertion rejected"):
        adapter._sessions.open_session(expired)  # noqa: SLF001

    signed = _assertion(adapter, issuer_key, jti="jti-tampered")
    header, claims, signature = signed.split(".")
    altered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    tampered = ".".join((header, claims, altered_signature))
    with pytest.raises(AuthenticationError, match="assertion rejected"):
        adapter._sessions.open_session(tampered)  # noqa: SLF001
