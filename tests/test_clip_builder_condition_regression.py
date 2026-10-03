"""
Track R2 M5 — mandatory regression test (Test Review iron rule: this modifies
existing behavior) for BufferManager.wait_for_segment_between, the
threading.Condition that replaced ClipBuilder._await_post_window's 0.5s
sleep-poll.

Covers the three failure modes a Condition-based wait can hide if done wrong:
  (a) lost notify — a registration completing before the wait even starts,
  (b) spurious wakeup — must not return before the real predicate is true,
  (c) timeout — must not block forever if the segment never arrives.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from app.core.recording_service.buffer_manager import BufferManager
from app.core.recording_service.models import Segment

BASE = datetime(2026, 7, 11, 10, 0, 0, tzinfo=timezone.utc)


def _make_buffer() -> BufferManager:
    storage = MagicMock()
    return BufferManager(storage=storage, retention_count=8)


def _segment(offset_s: float, duration_s: float = 5.0) -> Segment:
    return Segment(
        path=Path(f"seg_{offset_s:.1f}.ts"),
        started_at=BASE + timedelta(seconds=offset_s),
        ended_at=BASE + timedelta(seconds=offset_s + duration_s),
        finalized=True,
    )


class TestLostNotify:
    """(a) A registration that completes BEFORE wait_for_segment_between is
    even called must still be seen — the predicate is checked against the
    real index before the first .wait(), not inferred from catching an
    in-flight notify signal."""

    def test_segment_already_registered_returns_immediately(self):
        bm = _make_buffer()
        bm.register_segment(_segment(0))  # completes fully — index + notify — first

        t0 = time.monotonic()
        found = bm.wait_for_segment_between(
            BASE + timedelta(seconds=1), BASE + timedelta(seconds=3), timeout=5.0
        )
        elapsed = time.monotonic() - t0

        assert found is True
        assert elapsed < 0.5, f"should return immediately, took {elapsed:.2f}s"

    def test_notify_fired_a_moment_before_wait_is_not_lost(self):
        """Registration lands on another thread microseconds before the
        waiter calls wait_for_segment_between — no waiting thread exists yet
        to catch the notify_all(), which would be a lost wakeup with a naive
        'just wait for notify' implementation. The check-before-wait design
        does not depend on catching it at all."""
        bm = _make_buffer()
        ready = threading.Event()

        def register_soon():
            ready.wait()
            bm.register_segment(_segment(0))

        t = threading.Thread(target=register_soon)
        t.start()
        ready.set()
        t.join(timeout=5)  # registration (and its notify) is fully done before we even call wait

        found = bm.wait_for_segment_between(
            BASE + timedelta(seconds=1), BASE + timedelta(seconds=3), timeout=5.0
        )
        assert found is True


class TestSpuriousWakeup:
    """(b) A wakeup (spurious, or notified for an unrelated/non-overlapping
    segment) must not cause an early return — the loop re-checks the actual
    predicate and keeps waiting if it's still false."""

    def test_unrelated_notify_does_not_return_early(self):
        bm = _make_buffer()
        target_start = BASE + timedelta(seconds=10)
        target_end = BASE + timedelta(seconds=13)

        result = {}

        def waiter():
            result["found"] = bm.wait_for_segment_between(target_start, target_end, timeout=5.0)
            result["done_at"] = time.monotonic()

        t = threading.Thread(target=waiter)
        t.start()
        time.sleep(0.2)  # let the waiter block inside cond.wait()

        # Fire a bare notify with NO matching segment registered — and a
        # notify for a segment that does not overlap the target window at all.
        with bm._new_segment_cond:
            bm._new_segment_cond.notify_all()
        bm.register_segment(_segment(100))  # far outside [10s, 13s] — real notify, wrong window

        time.sleep(0.3)
        assert t.is_alive(), "waiter must still be blocked after a spurious/unrelated notify"

        real_registered_at = time.monotonic()
        bm.register_segment(_segment(10, duration_s=5))  # NOW overlaps [10s, 13s]
        t.join(timeout=5)

        assert result["found"] is True
        assert result["done_at"] >= real_registered_at, (
            "must not have returned before the matching segment was actually registered"
        )


class TestTimeout:
    """(c) If the segment never arrives, the wait must still return (False)
    after ~timeout — not block forever."""

    def test_returns_false_after_timeout_when_segment_never_arrives(self):
        bm = _make_buffer()
        t0 = time.monotonic()
        found = bm.wait_for_segment_between(
            BASE + timedelta(seconds=1), BASE + timedelta(seconds=3), timeout=0.5
        )
        elapsed = time.monotonic() - t0

        assert found is False
        assert 0.5 <= elapsed < 2.0, f"expected ~0.5s timeout, took {elapsed:.2f}s"
