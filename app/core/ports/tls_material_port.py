"""TLS material boundary for the LAN live-view listener (ADR-0023)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class TlsMaterialError(Exception):
    """No usable TLS material; the listener must not start (fail closed)."""


@dataclass(frozen=True)
class TlsMaterial:
    """Files a TLS server needs. Producing them is the provider's concern."""

    cert_file: str
    key_file: str
    ca_files: tuple[str, ...] = ()


class TlsMaterialPort(ABC):
    @abstractmethod
    def ensure(self) -> TlsMaterial:
        """Return usable material or raise ``TlsMaterialError``. Never degrade to plaintext."""
