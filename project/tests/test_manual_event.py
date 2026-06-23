"""
Unit tests — Fase 1 (R-AI): manual EventContext → AnalyticEvent + EventService
success callback (persistence seam).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from app.core.analytics.manual_event import analytic_event_from_context
from app.core.event_service import EventService
from app.core.recording_service.models import EventContext, MonitorInfo

_T0 = datetime(2026, 6, 22, 12, 0, 0, tzinfo=timezone.utc)


def _ctx(with_monitor: bool = True) -> EventContext:
    mons = (
        (MonitorInfo(name="\\\\.\\DISPLAY1", width=1920, height=1080, x=0, y=0, index=2),)
        if with_monitor else ()
    )
    return EventContext(
        event_id="120000",
        triggered_at=_T0,
        window_start=_T0 - timedelta(seconds=120),
        window_end=_T0 + timedelta(seconds=120),
        monitors=mons,
    )


class TestMapping:
    def test_basic_fields(self) -> None:
        ev = analytic_event_from_context(_ctx(), Path("clips/x.mp4"))
        assert ev.event_id == "120000"
        assert ev.source == "manual"
        assert ev.type == "manual"
        assert ev.monitor_index == 2
        assert ev.clip_path == Path("clips/x.mp4")
        assert ev.start == _T0 - timedelta(seconds=120)
        assert ev.end == _T0 + timedelta(seconds=120)

    def test_no_monitor(self) -> None:
        ev = analytic_event_from_context(_ctx(with_monitor=False))
        assert ev.monitor_index is None
        assert ev.clip_path is None


class TestEventServiceCallback:
    def test_on_clip_built_fired_on_success(self) -> None:
        clip_builder = MagicMock()
        clip_builder.snapshot_event.side_effect = lambda t: _ctx()
        clip_builder.build.return_value = Path("clips/ok.mp4")

        done = threading.Event()
        received: list = []

        def _built(ctx: EventContext, out: Path) -> None:
            received.append((ctx, out))
            done.set()

        svc = EventService(
            clip_builder=clip_builder, post_seconds=0, cooldown_seconds=0,
            on_clip_built=_built,
        )
        svc.trigger_manual_event()
        assert done.wait(timeout=2.0)
        assert received[0][1] == Path("clips/ok.mp4")
        assert isinstance(received[0][0], EventContext)

    def test_callback_exception_does_not_break_build(self) -> None:
        clip_builder = MagicMock()
        clip_builder.snapshot_event.side_effect = lambda t: _ctx()
        clip_builder.build.return_value = Path("clips/ok.mp4")

        def _boom(ctx, out):
            raise RuntimeError("store down")

        svc = EventService(
            clip_builder=clip_builder, post_seconds=0, cooldown_seconds=0,
            on_clip_built=_boom,
        )
        # Must not raise.
        assert svc.trigger_manual_event() is True
        import time
        time.sleep(0.2)
