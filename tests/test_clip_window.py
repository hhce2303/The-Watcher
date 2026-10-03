"""clip_window — shared window-flooring and filename-parsing helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.adapters.ffmpeg.clip_window import floor_to_window, parse_clip_start


class TestFloorToWindow:
    def test_floors_to_hour_boundary(self):
        dt = datetime(2026, 7, 10, 13, 47, 22, tzinfo=timezone.utc)
        assert floor_to_window(dt, 60) == datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)

    def test_exact_boundary_is_unchanged(self):
        dt = datetime(2026, 7, 10, 13, 0, 0, tzinfo=timezone.utc)
        assert floor_to_window(dt, 60) == dt

    def test_sub_hour_window(self):
        dt = datetime(2026, 7, 10, 13, 47, 22, tzinfo=timezone.utc)
        assert floor_to_window(dt, 15) == datetime(2026, 7, 10, 13, 45, 0, tzinfo=timezone.utc)

    def test_preserves_tzinfo(self):
        dt = datetime(2026, 7, 10, 13, 47, 22, tzinfo=timezone.utc)
        assert floor_to_window(dt, 60).tzinfo is timezone.utc


class TestParseClipStart:
    def test_parses_raw_per_monitor_filename(self):
        got = parse_clip_start(Path("2026-07-10_13-47-22_m0.mp4"))
        assert got == datetime(2026, 7, 10, 13, 47, 22, tzinfo=timezone.utc)

    def test_parses_combined_filename_no_suffix(self):
        got = parse_clip_start(Path("2026-07-10_13-47-22.mp4"))
        assert got == datetime(2026, 7, 10, 13, 47, 22, tzinfo=timezone.utc)

    def test_parses_event_clip_filename(self):
        got = parse_clip_start(Path("2026-07-10_13-47-22_event.mp4"))
        assert got == datetime(2026, 7, 10, 13, 47, 22, tzinfo=timezone.utc)

    def test_returns_none_on_unparseable_name(self):
        assert parse_clip_start(Path("unknown_clip.mp4")) is None
