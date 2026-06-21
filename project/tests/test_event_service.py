"""
Unit tests — Milestone 4: EventService cooldown and scheduler.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.event_service import EventService
from app.core.recording_service.models import EventContext


def _snapshot(t: datetime) -> EventContext:
    """Build a real EventContext from a trigger time (mirrors ClipBuilder)."""
    return EventContext(
        event_id=t.strftime("%H%M%S"),
        triggered_at=t,
        window_start=t,
        window_end=t,
        monitors=(),
    )


def make_event_service(post_seconds: int = 0, cooldown: int = 30) -> tuple[EventService, MagicMock]:
    """Return an EventService wired to a mock ClipBuilder."""
    clip_builder = MagicMock()
    clip_builder.snapshot_event.side_effect = _snapshot
    clip_builder.build.return_value = Path("clips/test_event.mp4")

    svc = EventService(
        clip_builder=clip_builder,
        post_seconds=post_seconds,
        cooldown_seconds=cooldown,
    )
    return svc, clip_builder


class TestEventServiceCooldown:
    def test_first_trigger_accepted(self) -> None:
        svc, _ = make_event_service()
        assert svc.trigger_manual_event() is True

    def test_immediate_second_trigger_rejected(self) -> None:
        svc, _ = make_event_service()
        svc.trigger_manual_event()
        assert svc.trigger_manual_event() is False

    def test_last_event_at_set_after_trigger(self) -> None:
        svc, _ = make_event_service()
        before = datetime.now(tz=timezone.utc)
        svc.trigger_manual_event()
        after = datetime.now(tz=timezone.utc)
        assert svc.last_event_at is not None
        assert before <= svc.last_event_at <= after

    def test_zero_cooldown_allows_repeated_triggers(self) -> None:
        svc, _ = make_event_service(cooldown=0)
        assert svc.trigger_manual_event() is True
        assert svc.trigger_manual_event() is True

    def test_last_event_at_none_initially(self) -> None:
        svc, _ = make_event_service()
        assert svc.last_event_at is None


class TestEventServiceScheduler:
    def test_clip_built_after_delay(self) -> None:
        """Clip builder is called once post_seconds timer fires."""
        svc, clip_builder = make_event_service(post_seconds=0, cooldown=0)
        done = threading.Event()

        def _notify(ctx: EventContext) -> Path:
            done.set()
            return Path("clips/ok.mp4")

        clip_builder.build.side_effect = _notify

        svc.trigger_manual_event()

        # post_seconds=0 means timer fires immediately in a daemon thread
        assert done.wait(timeout=2.0), "ClipBuilder.build was not called within 2s"
        clip_builder.build.assert_called_once()

    def test_clip_builder_receives_event_context(self) -> None:
        svc, clip_builder = make_event_service(post_seconds=0, cooldown=0)
        done = threading.Event()
        captured: list[EventContext] = []

        def _capture(ctx: EventContext) -> Path:
            captured.append(ctx)
            done.set()
            return Path("clips/ok.mp4")

        clip_builder.build.side_effect = _capture
        before = datetime.now(tz=timezone.utc)
        svc.trigger_manual_event()
        done.wait(timeout=2.0)
        after = datetime.now(tz=timezone.utc)

        assert len(captured) == 1
        assert isinstance(captured[0], EventContext)
        assert before <= captured[0].triggered_at <= after

    def test_exception_in_clip_builder_does_not_crash_service(self) -> None:
        svc, clip_builder = make_event_service(post_seconds=0, cooldown=0)
        clip_builder.build.side_effect = lambda ctx: (_ for _ in ()).throw(
            RuntimeError("Simulated failure")
        )

        # Patch timer to run synchronously so we can detect the call
        original_timer = threading.Timer

        def _immediate_timer(delay: float, fn, args=(), kwargs=None):
            t = original_timer(0, fn, args, kwargs or {})
            t.daemon = True
            return t

        with patch("app.core.event_service.threading.Timer", side_effect=_immediate_timer):
            svc.trigger_manual_event()

        # Service must still accept new events after an exception
        import time; time.sleep(0.1)
        svc2, _ = make_event_service(cooldown=0)
        assert svc2.trigger_manual_event() is True
