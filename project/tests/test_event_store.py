"""
Unit tests — Fase 1 (R-AI): SQLite event store.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.adapters.storage.sqlite_event_store import SqliteEventStoreAdapter
from app.core.analytics.models import AnalyticEvent

_T0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)


def _event(eid: str, offset_min: float = 0, dur_s: float = 30,
           monitor: int | None = 0, type_: str = "manual") -> AnalyticEvent:
    start = _T0 + timedelta(minutes=offset_min)
    return AnalyticEvent(
        event_id=eid, type=type_, source="manual",
        start=start, end=start + timedelta(seconds=dur_s), monitor_index=monitor,
    )


@pytest.fixture
def store(tmp_path: Path) -> SqliteEventStoreAdapter:
    return SqliteEventStoreAdapter(tmp_path / "events.db")


class TestAddGet:
    def test_add_and_get(self, store: SqliteEventStoreAdapter) -> None:
        e = _event("a")
        store.add(e)
        got = store.get("a")
        assert got == e

    def test_get_missing_returns_none(self, store: SqliteEventStoreAdapter) -> None:
        assert store.get("nope") is None

    def test_replace_same_id(self, store: SqliteEventStoreAdapter) -> None:
        store.add(_event("a", type_="manual"))
        store.add(_event("a", type_="person"))
        assert len(store.query()) == 1
        assert store.get("a").type == "person"

    def test_round_trip_preserves_payload(self, store: SqliteEventStoreAdapter) -> None:
        e = AnalyticEvent(
            event_id="x", type="person", source="auto:yolo",
            start=_T0, end=_T0 + timedelta(seconds=10),
            monitor_index=2, confidence=0.77, zone="entrada",
        )
        store.add(e)
        assert store.get("x") == e


class TestQuery:
    def test_query_all_newest_first(self, store: SqliteEventStoreAdapter) -> None:
        store.add(_event("old", offset_min=0))
        store.add(_event("new", offset_min=10))
        ids = [e.event_id for e in store.query()]
        assert ids == ["new", "old"]

    def test_query_time_window(self, store: SqliteEventStoreAdapter) -> None:
        store.add(_event("a", offset_min=0))    # 12:00–12:00:30
        store.add(_event("b", offset_min=30))   # 12:30
        hits = store.query(start=_T0 - timedelta(minutes=1), end=_T0 + timedelta(minutes=1))
        assert [e.event_id for e in hits] == ["a"]

    def test_query_overlap_inclusive(self, store: SqliteEventStoreAdapter) -> None:
        store.add(_event("a", offset_min=0, dur_s=600))  # 12:00–12:10
        # window 12:05–12:06 overlaps the long event
        hits = store.query(start=_T0 + timedelta(minutes=5), end=_T0 + timedelta(minutes=6))
        assert [e.event_id for e in hits] == ["a"]

    def test_query_by_monitor(self, store: SqliteEventStoreAdapter) -> None:
        store.add(_event("a", monitor=0))
        store.add(_event("b", monitor=1))
        assert [e.event_id for e in store.query(monitor_index=1)] == ["b"]

    def test_query_by_type(self, store: SqliteEventStoreAdapter) -> None:
        store.add(_event("a", type_="manual"))
        store.add(_event("b", type_="person"))
        assert [e.event_id for e in store.query(type="person")] == ["b"]
