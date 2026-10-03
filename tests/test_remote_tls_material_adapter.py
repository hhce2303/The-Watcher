"""RemoteTlsMaterialAdapter: CSR-based issuance against the-watcher-certs
(ADR-0023 phase 3).

No live network calls: the HTTP transport is a constructor-injected fake,
matching this repo's existing DI style (``tls_factory``/``live_view_factory``
in ``app/daemon_root.py``). All certificate/key material used here is
ephemeral, generated at test runtime -- nothing committed.
"""
from __future__ import annotations

import datetime
import json
import stat
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

from app.adapters.browser_local.identity import DeviceIdentity
from app.adapters.tls_provisioning.remote_adapter import RemoteTlsMaterialAdapter
from app.core.ports.tls_material_port import TlsMaterialError, TlsMaterialPort

HOSTNAME = "op.lan"


def _identity() -> DeviceIdentity:
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return DeviceIdentity(device_id="22222222-2222-2222-2222-222222222222", public_key_pem=public_pem, _private_key=private_key)


def _test_ca():
    ca_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-issuance-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    return ca_key, cert


def _issue_leaf_for_csr(csr: x509.CertificateSigningRequest, ca_key, ca_cert, *, hostname: str = HOSTNAME, mismatched_key: bool = False):
    """Simulate the issuance service: sign the CSR's (or a different) public key with the test CA."""
    now = datetime.datetime.now(datetime.timezone.utc)
    public_key = ec.generate_private_key(ec.SECP256R1()).public_key() if mismatched_key else csr.public_key()
    builder = (
        x509.CertificateBuilder()
        .subject_name(csr.subject).issuer_name(ca_cert.subject).public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
    )
    if hostname:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
    return builder.sign(ca_key, hashes.SHA256())


def _pem(cert: x509.Certificate) -> str:
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


class FakeTransport:
    """Records every call; returns (or raises) according to a scripted plan."""

    def __init__(self, plan):
        self._plan = list(plan)
        self.calls: list[dict] = []

    def post(self, url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        self.calls.append({
            "url": url, "headers": dict(headers), "timeout": timeout,
            "ssl_context": ssl_context, "payload": payload,
        })
        action = self._plan.pop(0)
        if isinstance(action, Exception):
            raise action
        status, body_obj = action
        return status, json.dumps(body_obj).encode("utf-8") if not isinstance(body_obj, bytes) else body_obj


def _success_body(csr_pem: str, ca_key, ca_cert, **kw) -> dict:
    csr = x509.load_pem_x509_csr(csr_pem.encode("ascii"))
    leaf = _issue_leaf_for_csr(csr, ca_key, ca_cert, **kw)
    return {"certificate_pem": _pem(leaf), "chain_pem": _pem(ca_cert)}


def _adapter(tmp_path, transport, *, max_attempts=3, sleeps=None, **overrides):
    kwargs = dict(
        issuance_url="https://certs.internal.lan",
        pinned_ca_file=str(_write_pinned_ca(tmp_path)),
        timeout_seconds=5.0,
        material_dir=tmp_path / "material",
        station_id=7,
        expected_hostname=HOSTNAME,
        identity=_identity(),
        transport=transport,
        max_attempts=max_attempts,
        backoff_base_seconds=0.001,
        sleep=(sleeps.append if sleeps is not None else (lambda s: None)),
    )
    kwargs.update(overrides)
    return RemoteTlsMaterialAdapter(**kwargs)


def _write_pinned_ca(tmp_path: Path) -> Path:
    """A real, ephemeral, self-signed test-only certificate.

    The fake transport never performs real TLS, but production code still
    builds a genuine ``ssl.SSLContext`` from this file (``load_verify_locations``
    parses it eagerly), so it must be syntactically valid PEM -- never real CA
    material, generated fresh per test run, nothing committed.
    """
    _, ca_cert = _test_ca()
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "pinned-ca.pem"
    path.write_text(_pem(ca_cert))
    return path


def test_implements_tls_material_port():
    assert issubclass(RemoteTlsMaterialAdapter, TlsMaterialPort)


def test_requires_issuance_url(tmp_path):
    with pytest.raises(TlsMaterialError, match="TLS_PROVISIONING_URL"):
        _adapter(tmp_path, FakeTransport([]), issuance_url="")


def test_requires_pinned_ca_file_to_exist(tmp_path):
    with pytest.raises(TlsMaterialError, match="TLS_PROVISIONING_PINNED_CA_FILE"):
        _adapter(tmp_path, FakeTransport([]), pinned_ca_file=str(tmp_path / "missing.pem"))


def test_requires_expected_hostname(tmp_path):
    with pytest.raises(TlsMaterialError, match="LIVE_VIEW_ORIGIN"):
        _adapter(tmp_path, FakeTransport([]), expected_hostname="")


def test_successful_first_issuance_persists_and_returns_material(tmp_path):
    ca_key, ca_cert = _test_ca()

    def respond(call_count_holder=[]):
        pass

    transport = FakeTransport([])
    adapter = _adapter(tmp_path, transport)

    # Build the success body lazily once we see the real CSR the adapter sent.
    def post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        transport.calls.append({"url": url, "payload": payload, "timeout": timeout})
        resp = _success_body(payload["csr_pem"], ca_key, ca_cert)
        return 200, json.dumps(resp).encode("utf-8")

    transport.post = post  # type: ignore[method-assign]

    material = adapter.ensure()

    assert Path(material.cert_file).is_file()
    assert Path(material.key_file).is_file()
    assert material.ca_files and Path(material.ca_files[0]).is_file()
    # The persisted cert is a real, parseable PEM matching the CA-issued leaf.
    x509.load_pem_x509_certificate(Path(material.cert_file).read_bytes())
    assert len(transport.calls) == 1
    assert transport.calls[0]["payload"]["device_id"] == adapter._identity.device_id
    assert transport.calls[0]["payload"]["station_id"] == "7"


def test_ensure_does_not_call_the_service_again_once_material_is_persisted(tmp_path):
    ca_key, ca_cert = _test_ca()
    transport = FakeTransport([])

    def post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        transport.calls.append(payload)
        resp = _success_body(payload["csr_pem"], ca_key, ca_cert)
        return 200, json.dumps(resp).encode("utf-8")

    transport.post = post  # type: ignore[method-assign]
    adapter = _adapter(tmp_path, transport)

    first = adapter.ensure()
    second = adapter.ensure()

    assert len(transport.calls) == 1  # no renewal: second ensure() is a pure disk read
    assert first == second


def test_a_distinct_fresh_key_and_csr_are_generated_per_issuance_attempt(tmp_path):
    ca_key, ca_cert = _test_ca()
    seen_csr_public_numbers = []

    def post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        csr = x509.load_pem_x509_csr(payload["csr_pem"].encode("ascii"))
        seen_csr_public_numbers.append(csr.public_key().public_numbers())
        resp = _success_body(payload["csr_pem"], ca_key, ca_cert)
        return 200, json.dumps(resp).encode("utf-8")

    transport = FakeTransport([])
    transport.post = post  # type: ignore[method-assign]
    a1 = _adapter(tmp_path / "a1", transport)
    a2 = _adapter(tmp_path / "a2", transport)

    a1.ensure()
    a2.ensure()

    assert seen_csr_public_numbers[0] != seen_csr_public_numbers[1]


def test_retries_are_bounded_with_increasing_backoff_then_fails_closed(tmp_path):
    sleeps: list[float] = []
    transport = FakeTransport([
        ConnectionError("no route to host"),
        ConnectionError("no route to host"),
        ConnectionError("no route to host"),
    ])
    adapter = _adapter(tmp_path, transport, max_attempts=3, sleeps=sleeps)

    with pytest.raises(TlsMaterialError):
        adapter.ensure()

    assert len(transport.calls) == 3  # exactly max_attempts, never unbounded
    assert len(sleeps) == 2  # backs off between attempts, not after the last
    assert sleeps == sorted(sleeps)  # increasing (or at least non-decreasing) backoff
    assert sleeps[1] > sleeps[0]
    assert not (tmp_path / "material").exists() or not any((tmp_path / "material").glob("issued*"))


def test_retry_succeeds_within_the_bounded_attempt_count(tmp_path):
    ca_key, ca_cert = _test_ca()
    calls = {"n": 0}

    def post(url, body, headers, timeout, ssl_context):
        calls["n"] += 1
        if calls["n"] < 2:
            raise ConnectionError("transient")
        payload = json.loads(body.decode("utf-8"))
        resp = _success_body(payload["csr_pem"], ca_key, ca_cert)
        return 200, json.dumps(resp).encode("utf-8")

    transport = FakeTransport([])
    transport.post = post  # type: ignore[method-assign]
    adapter = _adapter(tmp_path, transport, max_attempts=3)

    material = adapter.ensure()

    assert Path(material.cert_file).is_file()
    assert calls["n"] == 2


def test_idempotency_key_is_durable_and_identical_across_retries_of_one_attempt(tmp_path):
    seen_keys = []

    def post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        seen_keys.append(payload["idempotency_key"])
        raise ConnectionError("always fails in this test")

    transport = FakeTransport([])
    transport.post = post  # type: ignore[method-assign]
    adapter = _adapter(tmp_path, transport, max_attempts=3)

    with pytest.raises(TlsMaterialError):
        adapter.ensure()

    assert len(seen_keys) == 3
    assert len(set(seen_keys)) == 1  # same idempotency key reused across HTTP retries


def test_idempotency_key_persists_across_adapter_instances_restart(tmp_path):
    material_dir = tmp_path / "material"
    pinned_ca = _write_pinned_ca(tmp_path)

    def failing_post(url, body, headers, timeout, ssl_context):
        raise ConnectionError("service down")

    transport1 = FakeTransport([])
    transport1.post = failing_post  # type: ignore[method-assign]
    adapter1 = RemoteTlsMaterialAdapter(
        issuance_url="https://certs.internal.lan", pinned_ca_file=str(pinned_ca),
        timeout_seconds=5.0, material_dir=material_dir, station_id=7, expected_hostname=HOSTNAME,
        identity=_identity(), transport=transport1, max_attempts=1, backoff_base_seconds=0.001,
        sleep=lambda s: None,
    )
    with pytest.raises(TlsMaterialError):
        adapter1.ensure()

    seen_keys = []

    def recording_post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        seen_keys.append(payload["idempotency_key"])
        raise ConnectionError("still down")

    transport2 = FakeTransport([])
    transport2.post = recording_post  # type: ignore[method-assign]
    adapter2 = RemoteTlsMaterialAdapter(
        issuance_url="https://certs.internal.lan", pinned_ca_file=str(_write_pinned_ca(tmp_path)),
        timeout_seconds=5.0, material_dir=material_dir, station_id=7, expected_hostname=HOSTNAME,
        identity=_identity(), transport=transport2, max_attempts=1, backoff_base_seconds=0.001,
        sleep=lambda s: None,
    )
    with pytest.raises(TlsMaterialError):
        adapter2.ensure()

    idempotency_file = material_dir / "issuance-idempotency-key"
    assert idempotency_file.is_file()
    assert seen_keys[0] == idempotency_file.read_text(encoding="ascii").strip()


def test_fails_closed_on_non_200_status_after_exhausting_retries(tmp_path):
    transport = FakeTransport([
        (403, {"error": "device not enrolled"}),
        (403, {"error": "device not enrolled"}),
    ])
    adapter = _adapter(tmp_path, transport, max_attempts=2)

    with pytest.raises(TlsMaterialError):
        adapter.ensure()

    assert not (tmp_path / "material" / "issued.pem").exists()


def test_fails_closed_on_malformed_json_response(tmp_path):
    transport = FakeTransport([(200, b"not json at all")])
    adapter = _adapter(tmp_path, transport, max_attempts=1)

    with pytest.raises(TlsMaterialError):
        adapter.ensure()

    assert not (tmp_path / "material" / "issued.pem").exists()


def test_fails_closed_when_issued_public_key_does_not_match_csr(tmp_path):
    ca_key, ca_cert = _test_ca()

    def post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        resp = _success_body(payload["csr_pem"], ca_key, ca_cert, mismatched_key=True)
        return 200, json.dumps(resp).encode("utf-8")

    transport = FakeTransport([])
    transport.post = post  # type: ignore[method-assign]
    adapter = _adapter(tmp_path, transport, max_attempts=1)

    with pytest.raises(TlsMaterialError, match="public key"):
        adapter.ensure()

    assert not (tmp_path / "material" / "issued.pem").exists()


def test_fails_closed_when_san_does_not_match_expected_hostname(tmp_path):
    ca_key, ca_cert = _test_ca()

    def post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        resp = _success_body(payload["csr_pem"], ca_key, ca_cert, hostname="attacker.example")
        return 200, json.dumps(resp).encode("utf-8")

    transport = FakeTransport([])
    transport.post = post  # type: ignore[method-assign]
    adapter = _adapter(tmp_path, transport, max_attempts=1)

    with pytest.raises(TlsMaterialError, match="SAN"):
        adapter.ensure()

    assert not (tmp_path / "material" / "issued.pem").exists()


def test_fails_closed_when_san_is_missing_entirely(tmp_path):
    ca_key, ca_cert = _test_ca()

    def post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        resp = _success_body(payload["csr_pem"], ca_key, ca_cert, hostname=None)
        return 200, json.dumps(resp).encode("utf-8")

    transport = FakeTransport([])
    transport.post = post  # type: ignore[method-assign]
    adapter = _adapter(tmp_path, transport, max_attempts=1)

    with pytest.raises(TlsMaterialError, match="SAN"):
        adapter.ensure()


def test_fails_closed_on_malformed_chain(tmp_path):
    ca_key, ca_cert = _test_ca()

    def post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        csr = x509.load_pem_x509_csr(payload["csr_pem"].encode("ascii"))
        leaf = _issue_leaf_for_csr(csr, ca_key, ca_cert)
        resp = {"certificate_pem": _pem(leaf), "chain_pem": "not a real pem chain"}
        return 200, json.dumps(resp).encode("utf-8")

    transport = FakeTransport([])
    transport.post = post  # type: ignore[method-assign]
    adapter = _adapter(tmp_path, transport, max_attempts=1)

    with pytest.raises(TlsMaterialError, match="chain"):
        adapter.ensure()

    assert not (tmp_path / "material" / "issued.pem").exists()


def test_persisted_files_are_atomically_written_with_owner_only_permissions(tmp_path):
    import os

    if os.name == "nt":
        pytest.skip("POSIX permission bits are not meaningful on Windows (see tests/conftest.py::_WINDOWS_ONLY convention)")

    ca_key, ca_cert = _test_ca()

    def post(url, body, headers, timeout, ssl_context):
        payload = json.loads(body.decode("utf-8"))
        resp = _success_body(payload["csr_pem"], ca_key, ca_cert)
        return 200, json.dumps(resp).encode("utf-8")

    transport = FakeTransport([])
    transport.post = post  # type: ignore[method-assign]
    material_dir = tmp_path / "material"
    adapter = _adapter(tmp_path, transport, material_dir=material_dir)

    material = adapter.ensure()

    for path_str in (material.cert_file, material.key_file, *material.ca_files):
        mode = stat.S_IMODE(Path(path_str).stat().st_mode)
        assert mode == 0o600, f"{path_str} has mode {oct(mode)}, expected 0600"
    dir_mode = stat.S_IMODE(material_dir.stat().st_mode)
    assert dir_mode == 0o700, f"material dir has mode {oct(dir_mode)}, expected 0700"
    # Atomic write: no leftover .tmp files after a successful issuance.
    assert not list(material_dir.glob("*.tmp"))
