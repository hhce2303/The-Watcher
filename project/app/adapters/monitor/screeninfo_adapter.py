from __future__ import annotations

from typing import List

from loguru import logger

from app.core.ports.monitor_port import MonitorPort
from app.core.recording_service.models import MonitorInfo


class ScreeninfoMonitorAdapter(MonitorPort):
    """
    Monitor discovery adapter using the screeninfo library.

    Assigns each monitor a sequential position-based index (0 = primary,
    then left-to-right, top-to-bottom) rather than a DXGI output_idx.
    The index is used as a stable key for per-monitor segment directories
    and for ordering monitors in the combined hourly recording output.

    Using virtual-desktop coordinates (x, y) for capture means no DXGI
    session mapping is required — gdigrab targets each monitor by position.
    """

    def list_monitors(self) -> List[MonitorInfo]:
        """Return all currently connected monitors, primary first."""
        try:
            from screeninfo import get_monitors  # type: ignore[import]
        except ImportError:
            logger.error(
                "screeninfo not installed. Run: pip install screeninfo"
            )
            return []

        monitors: List[MonitorInfo] = []
        try:
            raw = list(get_monitors())
            # Sort deterministically: primary first, then left-to-right,
            # top-to-bottom.  This order becomes the sequential index that
            # drives HourlyRecordingBuilder layout.
            raw.sort(key=lambda m: (not getattr(m, "is_primary", False), m.x, m.y))
            for i, m in enumerate(raw):
                monitors.append(
                    MonitorInfo(
                        name=m.name or "Unknown",
                        width=m.width,
                        height=m.height,
                        x=m.x,
                        y=m.y,
                        is_primary=bool(getattr(m, "is_primary", False)),
                        index=i,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("Monitor enumeration failed: {}", exc)

        # Phase 1 verification: log each monitor with all properties so we can
        # confirm correct detection before wiring up recording and UI.
        logger.info("MonitorPort: {} monitor(s) detected.", len(monitors))
        for m in monitors:
            logger.info(
                "  [MONITOR] {} | {}×{} @ ({},{}) | primary={} | index={} | fp={}",
                m.display_name, m.width, m.height, m.x, m.y,
                m.is_primary, m.index, m.fingerprint,
            )
        return monitors
