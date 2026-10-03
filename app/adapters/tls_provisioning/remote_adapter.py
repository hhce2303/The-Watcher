"""`remote` mode: CSR-based issuance against `the-watcher-certs` (ADR-0023 phase 3).

Protocol (ADR-0023, Decision point 3): on first boot the daemon generates a
fresh local keypair + CSR, POSTs it to the issuance service together with the
already-enrolled Ed25519 ``DeviceIdentity`` signature, validates the response,
and persists the result once. There is no renewal: once material exists on
disk, ``ensure()`` never calls the service again (a reformat/reinstall simply
re-enrols from scratch). Any failure -- transport, malformed response, or a
validation mismatch -- fails closed: ``TlsMaterialError`` is raised and
nothing partial or unvalidated is ever persisted.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
import json
import os
import ssl
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app.adapters.browser_local.identity import DeviceIdentity
from app.core.ports.tls_material_port import TlsMaterial, TlsMaterialError, TlsMaterialPort

_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BACKOFF_BASE_SECONDS = 1.0
_CERT_FILENAME = "issued.pem"
_KEY_FILENAME = "issued-key.pem"
_CHAIN_FILENAME = "issued-chain.pem"
_IDEMPOTENCY_FILENAME = "issuance-idempotency-key"


class HttpTransport(Protocol):
    """Synchronous pinned-HTTPS POST. Tests inject a fake; production uses the default."""

    def post(
        self, url: str, body: bytes, headers: dict[str, str], timeout: float, ssl_context: ssl.SSLContext
    ) -> tuple[int, bytes]:
        ...


class UrllibHttpTransport:
    """Default transport: stdlib ``urllib``, validated against the pinned CA.

    Deliberately synchronous (not ``aiohttp``): ``TlsMaterialPort.ensure()`` is
    a synchronous interface invoked from inside ``live_view_lan``'s own asyncio
    loop (see ``LiveViewLanAdapter._serve``); driving an async HTTP client from
    there would require nesting a second event loop in the same thread, which
    ``asyncio`` forbids. A one-time, blocking stdlib call avoids that hazard
    without adding a dependency -- the one-shot, issue-once nature of this
    adapter (ADR-0023: no renewal) makes a short, bounded block acceptable.
    """

    def post(self, url, body, headers, timeout, ssl_context):
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout, context=ssl_context) as response:  # noqa: S310
                return response.status, response.read()
        except HTTPError as exc:
            return exc.code, exc.read()
        except URLError as exc:
            raise TlsMaterialError(f"TLS issuance request failed: {exc}") from exc


@dataclass(frozen=True)
class _IssuedMaterial:
    cert_pem: str
    chain_pem: str


def _split_pem_blocks(pem_text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in pem_text.splitlines():
        current.append(line)
        if line.strip() == "-----END CERTIFICATE-----":
            blocks.append("\n".join(current))
            current = []
    return blocks


class RemoteTlsMaterialAdapter(TlsMaterialPort):
    """`remote` mode (ADR-0023 phase 3): one CSR-based issuance per installation."""

    def __init__(
        self,
        *,
        issuance_url: str,
        pinned_ca_file: str,
        timeout_seconds: float,
        material_dir: Path,
        station_id: int,
        expected_hostname: str,
        identity: DeviceIdentity,
        transport: HttpTransport | None = None,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        backoff_base_seconds: float = _DEFAULT_BACKOFF_BASE_SECONDS,
        sleep=time.sleep,
    ) -> None:
        if not issuance_url:
            raise TlsMaterialError("TLS_PROVISIONING_URL is required for TLS_PROVISIONING_MODE=remote")
        if not pinned_ca_file or not Path(pinned_ca_file).is_file():
            raise TlsMaterialError(
                "TLS_PROVISIONING_PINNED_CA_FILE is required and must exist for TLS_PROVISIONING_MODE=remote"
            )
        if not expected_hostname:
            raise TlsMaterialError(
                "LIVE_VIEW_ORIGIN must have a hostname to derive the issuance SAN for TLS_PROVISIONING_MODE=remote"
            )
        if max_attempts < 1:
            raise TlsMaterialError("TLS issuance max_attempts must be at least 1")
        self._url = issuance_url.rstrip("/") + "/v1/certificates"
        self._pinned_ca_file = pinned_ca_file
        self._timeout = timeout_seconds
        self._material_dir = Path(material_dir)
        self._station_id = station_id
        self._expected_hostname = expected_hostname
        self._identity = identity
        self._transport = transport or UrllibHttpTransport()
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds
        self._sleep = sleep

    @property
    def _cert_file(self) -> Path:
        return self._material_dir / _CERT_FILENAME

    @property
    def _key_file(self) -> Path:
        return self._material_dir / _KEY_FILENAME

    @property
    def _chain_file(self) -> Path:
        return self._material_dir / _CHAIN_FILENAME

    @property
    def _idempotency_file(self) -> Path:
        return self._material_dir / _IDEMPOTENCY_FILENAME

    def ensure(self) -> TlsMaterial:
        """Return persisted material, issuing it once if this is the first boot.

        No renewal (ADR-0023): once ``issued.pem``/``issued-key.pem`` exist on
        disk, this never calls the issuance service again.
        """
        if self._cert_file.is_file() and self._key_file.is_file():
            ca_files = (str(self._chain_file),) if self._chain_file.is_file() else ()
            return TlsMaterial(str(self._cert_file), str(self._key_file), ca_files)
        return self._issue()

    # -- first-boot issuance -------------------------------------------------

    def _issue(self) -> TlsMaterial:
        private_key = ec.generate_private_key(ec.SECP256R1())
        csr = self._build_csr(private_key)
        idempotency_key = self._load_or_create_idempotency_key()
        body = self._build_request_body(csr, idempotency_key)
        ssl_context = ssl.create_default_context(cafile=self._pinned_ca_file)

        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                status, raw = self._transport.post(
                    self._url, body, {"Content-Type": "application/json"}, self._timeout, ssl_context
                )
            except TlsMaterialError as exc:
                last_error = exc
            except Exception as exc:  # noqa: BLE001 -- any transport failure must fail closed, never crash the daemon
                last_error = exc
            else:
                if status == 200:
                    issued = self._parse_response(raw)
                    material = self._validate_response(private_key, csr, issued)
                    self._persist(private_key, material)
                    ca_files = (str(self._chain_file),) if material.chain_pem else ()
                    return TlsMaterial(str(self._cert_file), str(self._key_file), ca_files)
                last_error = TlsMaterialError(
                    f"TLS issuance rejected: status={status} body={raw[:256]!r}"
                )
            if attempt < self._max_attempts:
                self._sleep(self._backoff_base * (2 ** (attempt - 1)))
        raise TlsMaterialError(
            f"TLS issuance failed after {self._max_attempts} attempt(s): {last_error}"
        )

    def _build_csr(self, private_key: ec.EllipticCurvePrivateKey) -> x509.CertificateSigningRequest:
        builder = x509.CertificateSigningRequestBuilder().subject_name(
            x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, self._expected_hostname)])
        )
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(self._expected_hostname)]), critical=False
        )
        return builder.sign(private_key, hashes.SHA256())

    def _load_or_create_idempotency_key(self) -> str:
        """Durable per-attempt key: generated once, reused across every HTTP
        retry of *this* issuance attempt (and across process restarts before
        it finally succeeds), so the server can dedupe a retried request.
        """
        if self._idempotency_file.is_file():
            return self._idempotency_file.read_text(encoding="ascii").strip()
        key = uuid.uuid4().hex
        self._material_dir.mkdir(parents=True, exist_ok=True)
        self._atomic_write(self._idempotency_file, key)
        return key

    def _build_request_body(self, csr: x509.CertificateSigningRequest, idempotency_key: str) -> bytes:
        nonce = uuid.uuid4().hex
        csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode("ascii")
        csr_der = csr.public_bytes(serialization.Encoding.DER)
        csr_der_b64 = base64.urlsafe_b64encode(csr_der).decode("ascii").rstrip("=")
        payload = {
            "version": "v1",
            "audience": "the-watcher-certs",
            "method": "POST",
            "path": "/v1/certificates",
            "device_id": self._identity.device_id,
            "station_id": str(self._station_id),
            "issued_at": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
            "nonce": nonce,
            "idempotency_key": idempotency_key,
            "csr_der_b64": csr_der_b64,
            # Transitional diagnostic field: the broker ignores it; fake transports
            # and human operators can inspect the local CSR without decoding DER.
            "csr_pem": csr_pem,
        }
        canonical = b"".join(
            len(payload[field].encode("utf-8")).to_bytes(4, "big") + payload[field].encode("utf-8")
            for field in (
                "version", "audience", "method", "path", "device_id", "station_id",
                "issued_at", "nonce", "idempotency_key", "csr_der_b64",
            )
        )
        signature = self._identity.sign_tls_issuance_bytes(canonical)
        payload["signature"] = signature
        return json.dumps(payload).encode("utf-8")

    # -- response handling ----------------------------------------------------

    def _parse_response(self, raw: bytes) -> dict:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 -- any malformed body must fail closed
            raise TlsMaterialError(f"malformed TLS issuance response: {exc}") from exc
        if not isinstance(parsed, dict):
            raise TlsMaterialError("malformed TLS issuance response: expected a JSON object")
        return parsed

    def _validate_response(
        self, private_key: ec.EllipticCurvePrivateKey, csr: x509.CertificateSigningRequest, issued: dict
    ) -> _IssuedMaterial:
        cert_pem = issued.get("certificate_pem")
        if cert_pem is None:
            try:
                encoded_der = issued["certificate_der_b64"]
                cert_der = base64.urlsafe_b64decode(encoded_der + "=" * (-len(encoded_der) % 4))
                cert_pem = x509.load_der_x509_certificate(cert_der).public_bytes(
                    serialization.Encoding.PEM
                ).decode("ascii")
            except (KeyError, TypeError, ValueError) as exc:
                raise TlsMaterialError(
                    "TLS issuance response requires certificate_pem or certificate_der_b64"
                ) from exc
        chain_pem = issued.get("chain_pem", "") or ""

        try:
            cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
        except Exception as exc:  # noqa: BLE001
            raise TlsMaterialError(f"issued certificate is not valid PEM: {exc}") from exc

        if chain_pem:
            try:
                blocks = _split_pem_blocks(chain_pem)
                if not blocks:
                    raise ValueError("chain_pem contained no certificate blocks")
                for block in blocks:
                    x509.load_pem_x509_certificate(block.encode("ascii"))
            except Exception as exc:  # noqa: BLE001
                raise TlsMaterialError(f"issued chain is not valid PEM: {exc}") from exc

        if cert.public_key().public_numbers() != csr.public_key().public_numbers():
            raise TlsMaterialError("issued certificate public key does not match the CSR")

        try:
            san_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            sans = san_ext.value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            sans = []
        if self._expected_hostname not in sans:
            raise TlsMaterialError(
                f"issued certificate SAN {sans!r} does not match the expected hostname "
                f"{self._expected_hostname!r}"
            )

        return _IssuedMaterial(cert_pem=cert_pem, chain_pem=chain_pem)

    # -- persistence ----------------------------------------------------------

    def _persist(self, private_key: ec.EllipticCurvePrivateKey, material: _IssuedMaterial) -> None:
        self._material_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            try:
                os.chmod(self._material_dir, 0o700)
            except OSError:
                pass
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        # Key and chain are written before the cert file; the cert file's
        # presence is what ``ensure()`` treats as "material exists", so it
        # must be the last thing written.
        self._atomic_write(self._key_file, key_pem)
        if material.chain_pem:
            self._atomic_write(self._chain_file, material.chain_pem)
        self._atomic_write(self._cert_file, material.cert_pem)

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write via a temp file + rename so a crash never leaves a partial file."""
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="ascii")
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        tmp.replace(path)


__all__ = ["RemoteTlsMaterialAdapter", "HttpTransport", "UrllibHttpTransport"]
