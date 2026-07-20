from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def floor_to_window(dt: datetime, window_minutes: int) -> datetime:
    """Round ``dt`` down to the nearest ``window_minutes`` boundary."""
    total_minutes = dt.hour * 60 + dt.minute
    floor_minutes = (total_minutes // window_minutes) * window_minutes
    return dt.replace(
        hour=floor_minutes // 60,
        minute=floor_minutes % 60,
        second=0,
        microsecond=0,
    )


def parse_clip_start(clip_path: Path) -> "datetime | None":
    """Parse the leading ``YYYY-MM-DD_HH-MM-SS`` off a clip filename.

    Returns ``None`` on failure — callers choose their own fallback rather
    than silently guessing a timestamp (a wrong guess can misgroup a clip
    into the wrong combined window).
    """
    stem = clip_path.stem
    # Strip known suffixes so "2026-07-10_13-00-00_m0" and
    # "2026-07-10_13-00-00_event" both yield the same leading timestamp.
    prefix = stem.split("_m")[0].split("_event")[0]
    try:
        return datetime.strptime(prefix[:19], "%Y-%m-%d_%H-%M-%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
