from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field


@dataclass
class ClipRequest:
    """A Supervisor's request for a clip to be extracted and exported by IT.

    Lifecycle:  pending → processing → done | declined
    Transport:  JSON via WebSocket (Supervisor → IT)
    Persistence: one JSON file per request in %LOCALAPPDATA%\\The Watcher\\requests\\
    """

    id: str
    created_at: str          # ISO-8601 UTC, e.g. "2026-06-04T14:32:00Z"
    supervisor_host: str     # hostname of the Supervisor PC
    operator: str            # operator folder name, e.g. "Operator-28"
    storage: str             # storage share name, e.g. "Storage1"
    start_time: str          # local datetime string "YYYY-MM-DD HH:MM"
    end_time: str            # local datetime string "YYYY-MM-DD HH:MM"
    description: str         # free-text incident description
    status: str = "pending"  # pending | processing | done | declined

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ClipRequest":
        return cls(
            id=d["id"],
            created_at=d["created_at"],
            supervisor_host=d.get("supervisor_host", ""),
            operator=d["operator"],
            storage=d.get("storage", ""),
            start_time=d["start_time"],
            end_time=d["end_time"],
            description=d.get("description", ""),
            status=d.get("status", "pending"),
        )


class RequestPort(ABC):
    """Port for persisting and retrieving ClipRequest objects."""

    @abstractmethod
    def save(self, req: ClipRequest) -> None:
        """Persist a new request (or overwrite if id already exists)."""

    @abstractmethod
    def load_all(self) -> list[ClipRequest]:
        """Return all persisted requests, newest first."""

    @abstractmethod
    def update_status(self, req_id: str, status: str) -> None:
        """Update the status field of an existing request."""
