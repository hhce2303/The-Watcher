"""DeviceIdentity signing domain for TLS issuance requests (ADR-0023 phase 3).

Mirrors the existing per-purpose-method pattern (``sign_challenge`` /
``sign_live_heartbeat``): a new, distinct version-tagged context constant and a
dedicated method, so a TLS-issuance signature can never be replayed as a
heartbeat or bootstrap-challenge signature (and vice versa).
"""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.adapters.browser_local.identity import DeviceIdentity


def _identity() -> tuple[DeviceIdentity, Ed25519PrivateKey]:
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    identity = DeviceIdentity(
        device_id="11111111-1111-1111-1111-111111111111",
        public_key_pem=public_pem,
        _private_key=private_key,
    )
    return identity, private_key


def test_sign_tls_issuance_request_returns_a_verifiable_urlsafe_b64_signature():
    identity, private_key = _identity()
    canonical = "device:1:nonce:idem:csrfingerprint"

    signature = identity.sign_tls_issuance_request(canonical)

    raw = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
    private_key.public_key().verify(raw, b"the-watcher-tls-issuance:v1:" + canonical.encode("utf-8"))


def test_tls_issuance_signature_uses_a_distinct_domain_from_live_heartbeat():
    identity, _ = _identity()
    canonical = "same-bytes-either-way"

    tls_signature = identity.sign_tls_issuance_request(canonical)
    heartbeat_signature = identity.sign_live_heartbeat(canonical)

    assert tls_signature != heartbeat_signature


def test_tls_issuance_signature_uses_a_distinct_domain_from_bootstrap_challenge():
    identity, _ = _identity()
    canonical = "same-bytes-either-way"

    tls_signature = identity.sign_tls_issuance_request(canonical)
    challenge_signature = identity.sign_challenge(canonical)

    assert tls_signature != challenge_signature
