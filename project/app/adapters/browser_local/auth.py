"""Assertion, in-memory session, and media-capability validation for browser-local."""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from jwt.algorithms import OKPAlgorithm
from loguru import logger

from app.adapters.browser_local.identity import DeviceIdentity


class AuthenticationError(ValueError):
    """Authentication failed without exposing token-validation details to clients."""


@dataclass(frozen=True)
class BrowserSession:
    token: str
    subject: str
    device_id: str
    station_id: int
    expires_at: float


@dataclass(frozen=True)
class MediaCapability:
    token: str
    session_token: str
    target: Path
    kind: str
    expires_at: float


class BrowserSessionManager:
    """Fails-closed verifier for short Daily assertions and local capabilities."""

    def __init__(
        self,
        *,
        identity: DeviceIdentity,
        issuer: str,
        audience: str,
        issuer_kid: str,
        station_id: int,
        issuer_public_key_file: str,
        session_ttl_seconds: int = 300,
        capability_ttl_seconds: int = 30,
        required_scope: str = "preview:read",
    ) -> None:
        if station_id <= 0:
            raise ValueError("BROWSER_LOCAL_STATION_ID must be a positive enrolled station id")
        if not issuer_kid:
            raise ValueError("BROWSER_LOCAL_ISSUER_KID is required")
        key_path = Path(issuer_public_key_file)
        if not key_path.is_file():
            raise ValueError("BROWSER_LOCAL_ISSUER_PUBLIC_KEY_FILE is required")
        self._identity = identity
        self._issuer = issuer
        self._audience = audience
        self._issuer_kid = issuer_kid
        self._station_id = station_id
        raw_public_key = key_path.read_text(encoding="utf-8")
        try:
            public_jwk = json.loads(raw_public_key)
        except json.JSONDecodeError:
            self._public_key = raw_public_key
        else:
            if not isinstance(public_jwk, dict) or public_jwk.get("kty") != "OKP":
                raise ValueError("issuer verification key must be PEM or an Ed25519 public JWK")
            self._public_key = OKPAlgorithm.from_jwk(json.dumps(public_jwk))
        self._session_ttl = session_ttl_seconds
        self._capability_ttl = capability_ttl_seconds
        self._required_scope = required_scope
        self._lock = threading.Lock()
        self._used_jti: dict[str, float] = {}
        self._sessions: dict[str, BrowserSession] = {}
        self._capabilities: dict[str, MediaCapability] = {}

    @property
    def device_id(self) -> str:
        return self._identity.device_id

    @property
    def public_key_pem(self) -> str:
        return self._identity.public_key_pem

    def sign_bootstrap_challenge(self, nonce: str) -> str:
        return self._identity.sign_challenge(nonce)

    def open_session(self, assertion: str) -> BrowserSession:
        """Verify and consume a signed, single-use assertion from Daily."""
        if not assertion or len(assertion) > 16_384:
            raise AuthenticationError("invalid assertion")
        try:
            header = jwt.get_unverified_header(assertion)
            if header.get("alg") != "EdDSA" or header.get("kid") != self._issuer_kid:
                raise AuthenticationError("assertion key rejected")
            claims = jwt.decode(
                assertion,
                self._public_key,
                algorithms=["EdDSA"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iat", "nbf", "jti", "sub", "device_id", "station_id", "nonce"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("assertion rejected") from exc

        if claims.get("device_id") != self._identity.device_id:
            raise AuthenticationError("assertion device mismatch")
        try:
            claim_station = int(claims["station_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("assertion station invalid") from exc
        if claim_station != self._station_id:
            raise AuthenticationError("assertion station mismatch")
        scopes = claims.get("scope", [])
        scope_set = set(scopes.split()) if isinstance(scopes, str) else set(scopes)
        # The browser channel is intentionally preview-only. An assertion with
        # broader scope is rejected rather than granting future route access.
        if scope_set != {self._required_scope}:
            raise AuthenticationError("assertion scope invalid")

        now = time.monotonic()
        jti = str(claims["jti"])
        # The assertion expiration is an epoch timestamp; a monotonic five-minute
        # replay cache is sufficient because issued assertions live only 60 s.
        with self._lock:
            self._cleanup_locked(now)
            if jti in self._used_jti:
                raise AuthenticationError("assertion replay")
            self._used_jti[jti] = now + 120
            token = secrets.token_urlsafe(32)
            session = BrowserSession(
                token=token,
                subject=str(claims["sub"]),
                device_id=self._identity.device_id,
                station_id=self._station_id,
                expires_at=now + self._session_ttl,
            )
            self._sessions[token] = session
        logger.info("[browser-local] session accepted user={}", _redact_subject(session.subject))
        return session

    def require_session(self, token: str | None) -> BrowserSession:
        if not token:
            raise AuthenticationError("missing browser session")
        now = time.monotonic()
        with self._lock:
            self._cleanup_locked(now)
            session = self._sessions.get(token)
            if session is None or session.expires_at <= now:
                raise AuthenticationError("browser session expired")
            return session

    def issue_capability(self, session: BrowserSession, target: Path, kind: str) -> str:
        if kind != "preview":
            raise ValueError("unsupported capability kind")
        now = time.monotonic()
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._cleanup_locked(now)
            self._capabilities[token] = MediaCapability(
                token=token,
                session_token=session.token,
                target=Path(target),
                kind=kind,
                expires_at=now + self._capability_ttl,
            )
        return token

    def require_capability(self, token: str, kind: str) -> MediaCapability:
        now = time.monotonic()
        with self._lock:
            self._cleanup_locked(now)
            cap = self._capabilities.get(token)
            if cap is None or cap.kind != kind or cap.expires_at <= now:
                raise AuthenticationError("media capability expired")
            session = self._sessions.get(cap.session_token)
            if session is None or session.expires_at <= now:
                raise AuthenticationError("capability session expired")
            return cap

    def _cleanup_locked(self, now: float) -> None:
        for collection in (self._used_jti, self._sessions, self._capabilities):
            expired = [key for key, item in collection.items() if _expiry(item) <= now]
            for key in expired:
                collection.pop(key, None)


def _expiry(item: Any) -> float:
    return item if isinstance(item, float) else item.expires_at


def _redact_subject(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()[:12]
