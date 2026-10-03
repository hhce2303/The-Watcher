"""Local device identity used to enrol a Watcher daemon with SIGDailyReport."""
from __future__ import annotations

import base64
import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from loguru import logger

_CHALLENGE_CONTEXT = b"the-watcher-browser-local:v1:"
_LIVE_HEARTBEAT_CONTEXT = b"the-watcher-live-heartbeat:v1:"


@dataclass(frozen=True)
class DeviceIdentity:
    """Stable per-installation Ed25519 identity; the private key never leaves disk."""

    device_id: str
    public_key_pem: str
    _private_key: Ed25519PrivateKey

    def sign_challenge(self, nonce: str) -> str:
        """Return URL-safe base64 signature over the exact Daily bootstrap nonce."""
        if not nonce or len(nonce) > 512:
            raise ValueError("invalid browser-local challenge nonce")
        signature = self._private_key.sign(_CHALLENGE_CONTEXT + nonce.encode("utf-8"))
        return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")

    def sign_live_heartbeat(self, canonical_payload: str) -> str:
        """Sign the exact, server-validated Daily live-heartbeat payload."""
        signature = self._private_key.sign(_LIVE_HEARTBEAT_CONTEXT + canonical_payload.encode("utf-8"))
        return base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")

    def enrollment_payload(self) -> dict[str, str]:
        """Safe data an administrator imports into SIGDailyReport."""
        return {"device_id": self.device_id, "public_key_pem": self.public_key_pem}


class DeviceIdentityStore:
    """Load or create the device key under the user's LocalAppData directory."""

    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / "device_identity.json"

    @property
    def path(self) -> Path:
        return self._path

    def load_or_create(self) -> DeviceIdentity:
        if self._path.exists():
            return self._load()

        private_key = Ed25519PrivateKey.generate()
        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("ascii")
        identity = DeviceIdentity(
            device_id=str(uuid.uuid4()), public_key_pem=public_pem, _private_key=private_key
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "device_id": identity.device_id,
                    "public_key_pem": public_pem,
                    "private_key_pem": private_pem,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self._path)
        self._restrict_to_current_user()
        logger.info("[browser-local] created device identity {}", identity.device_id)
        return identity

    def _load(self) -> DeviceIdentity:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            device_id = str(uuid.UUID(raw["device_id"]))
            private_key = serialization.load_pem_private_key(
                raw["private_key_pem"].encode("ascii"), password=None
            )
            if not isinstance(private_key, Ed25519PrivateKey):
                raise ValueError("device key is not Ed25519")
            return DeviceIdentity(
                device_id=device_id,
                public_key_pem=str(raw["public_key_pem"]),
                _private_key=private_key,
            )
        except Exception as exc:  # noqa: BLE001 -- an invalid identity must not be replaced silently
            raise RuntimeError(f"invalid browser-local identity at {self._path}: {exc}") from exc

    def _restrict_to_current_user(self) -> None:
        """Apply best-effort private-file permissions without weakening startup.

        Windows ACLs differ between domain and local accounts.  ``icacls`` is
        deliberately best-effort here: failure leaves the file in the user
        profile and is logged for remediation instead of causing a recorder
        crash.  The deployment checklist verifies the actual ACL.
        """
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass
        if os.name != "nt":
            return
        username = os.environ.get("USERNAME")
        if not username:
            return
        try:
            subprocess.run(
                [
                    "icacls",
                    str(self._path),
                    "/inheritance:r",
                    "/grant:r",
                    f"{username}:(R,W)",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[browser-local] could not tighten identity ACL: {}", exc)
