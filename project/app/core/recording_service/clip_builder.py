from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from loguru import logger

from app.core.ports.clip_port import ClipPort
from app.core.ports.timestamp_port import TimestampPort
from app.core.recording_service.models import MonitorInfo, Segment

if TYPE_CHECKING:
    from app.core.recording_service.service import RecordingService


class ClipBuilder:
    """
    Domain service that selects per-monitor segments and delegates clip assembly.

    For each monitor currently selected in the UI, queries its dedicated
    BufferManager for segments overlapping the event window, then passes
    the per-monitor segment map to the ClipPort adapter.

    The adapter is responsible for assembling the final composite clip
    (hstack for multi-monitor, stream-copy for single monitor).

    This class contains zero FFmpeg knowledge.
    """

    def __init__(
        self,
        recording_service: "RecordingService",
        clip_adapter: ClipPort,
        clips_dir: Path,
        pre_seconds: int = 120,
        post_seconds: int = 120,
        timestamp_adapter: Optional[TimestampPort] = None,
    ) -> None:
        self._service = recording_service
        self._adapter = clip_adapter
        self._clips_dir = clips_dir
        self._pre_seconds = pre_seconds
        self._post_seconds = post_seconds
        self._timestamp_adapter = timestamp_adapter

    def build(self, event_triggered_at: datetime) -> Optional[Path]:
        """
        Build a clip centred on the event.

        Window: [event_triggered_at - pre_seconds, event_triggered_at + post_seconds]

        Queries each selected monitor's buffer independently so the clip
        reflects exactly the monitors the user chose in the UI.

        Returns the output path on success, None if no segments were found.
        """
        selected = self._service.selected_monitors
        if not selected:
            logger.warning("No monitors selected — clip not built.")
            return None

        clip_start = event_triggered_at - timedelta(seconds=self._pre_seconds)
        clip_end = event_triggered_at + timedelta(seconds=self._post_seconds)

        monitor_segments: Dict[MonitorInfo, List[Segment]] = {}
        for m in selected:
            worker = self._service.get_worker(m.index)
            if worker is None:
                logger.warning(
                    "No worker found for monitor {} — skipping.", m.display_name
                )
                continue
            segs = worker.buffer.get_segments_between(clip_start, clip_end)
            if segs:
                monitor_segments[m] = segs
            else:
                logger.warning(
                    "No segments for monitor {} in window [{} → {}].",
                    m.display_name,
                    clip_start.isoformat(),
                    clip_end.isoformat(),
                )

        if not monitor_segments:
            logger.warning(
                "No segments found for event at {}. Clip not built.",
                event_triggered_at.isoformat(),
            )
            return None

        logger.info(
            "Building clip: event={} | {} monitor(s) | window [{} → {}]",
            event_triggered_at.isoformat(),
            len(monitor_segments),
            clip_start.isoformat(),
            clip_end.isoformat(),
        )

        self._clips_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_path(event_triggered_at)

        result = self._adapter.build_clip(
            monitor_segments, output_path, clip_start, clip_end
        )

        if result is not None and self._timestamp_adapter is not None:
            result = self._timestamp_adapter.burn(result, clip_start)

        return result

    def set_clips_dir(self, path: Path) -> None:
        """Change where assembled clips are saved. Takes effect on the next build()."""
        self._clips_dir = path
        logger.info("Clips output directory updated to: {}", path)

    def _output_path(self, triggered_at: datetime) -> Path:
        """Derive clip filename from event timestamp.
        Example: clips/2026-04-27_13-22-10_event.mp4
        """
        filename = triggered_at.strftime("%Y-%m-%d_%H-%M-%S") + "_event.mp4"
        return self._clips_dir / filename
