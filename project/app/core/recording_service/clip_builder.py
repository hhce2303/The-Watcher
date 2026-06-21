from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from loguru import logger

from app.core.ports.clip_port import ClipPort
from app.core.ports.timestamp_port import TimestampPort
from app.core.recording_service.models import EventContext, MonitorInfo, Segment

if TYPE_CHECKING:
    from app.core.recording_service.service import RecordingService


class ClipBuilder:
    """
    Domain service that selects per-monitor segments and delegates clip assembly.

    For each monitor selected at the moment the event fired (captured in an
    :class:`EventContext` snapshot), queries its dedicated BufferManager for
    segments overlapping the event window, then passes the per-monitor segment
    map to the ClipPort adapter.

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
        post_window_timeout_seconds: float = 30.0,
    ) -> None:
        self._service = recording_service
        self._adapter = clip_adapter
        self._clips_dir = clips_dir
        self._pre_seconds = pre_seconds
        self._post_seconds = post_seconds
        self._timestamp_adapter = timestamp_adapter
        self._post_window_timeout = post_window_timeout_seconds

    def snapshot_event(self, triggered_at: datetime) -> EventContext:
        """Freeze the event at *trigger time* (pipeline F5).

        Captures the monitor selection and clip window NOW so the later build
        is deterministic even if the user changes the selection during the
        post-event window.
        """
        monitors = tuple(self._service.selected_monitors)
        return EventContext(
            event_id=triggered_at.strftime("%H%M%S"),
            triggered_at=triggered_at,
            window_start=triggered_at - timedelta(seconds=self._pre_seconds),
            window_end=triggered_at + timedelta(seconds=self._post_seconds),
            monitors=monitors,
        )

    def build(self, ctx: EventContext) -> Optional[Path]:
        """
        Build a clip from a frozen event snapshot.

        Window: [triggered_at - pre_seconds, triggered_at + post_seconds]

        Queries each snapshotted monitor's buffer independently so the clip
        reflects exactly the monitors the user had chosen when the event fired.

        Returns the output path on success, None if no segments were found.
        """
        log = logger.bind(phase="BUILD-EVENT", evt=ctx.event_id, mon="-", sid="-")

        selected = list(ctx.monitors)
        if not selected:
            log.warning("No monitors selected — clip not built.")
            return None

        clip_start = ctx.window_start
        clip_end = ctx.window_end

        # Wait (bounded) for the post-event window to be fully written before
        # assembling, so the trailing footage is complete rather than estimated.
        self._await_post_window(selected, clip_end, log)

        monitor_segments: Dict[MonitorInfo, List[Segment]] = {}
        for m in selected:
            worker = self._service.get_worker(m.index)
            if worker is None:
                log.warning(
                    "No worker found for monitor {} — skipping.", m.display_name
                )
                continue
            segs = worker.buffer.get_segments_between(clip_start, clip_end)
            if segs:
                monitor_segments[m] = segs
            else:
                log.warning(
                    "No segments for monitor {} in window [{} → {}].",
                    m.display_name,
                    clip_start.isoformat(),
                    clip_end.isoformat(),
                )

        if not monitor_segments:
            log.warning(
                "No segments found for event at {}. Clip not built.",
                ctx.triggered_at.isoformat(),
            )
            return None

        log.info(
            "Building clip: event={} | {} monitor(s) | window [{} → {}]",
            ctx.triggered_at.isoformat(),
            len(monitor_segments),
            clip_start.isoformat(),
            clip_end.isoformat(),
        )

        self._clips_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_path(ctx.triggered_at)

        result = self._adapter.build_clip(
            monitor_segments, output_path, clip_start, clip_end
        )

        if result is not None and self._timestamp_adapter is not None:
            result = self._timestamp_adapter.burn(result, clip_start)

        return result

    def _await_post_window(
        self, monitors: List[MonitorInfo], clip_end: datetime, log
    ) -> None:
        """Block until every selected monitor has footage covering ``clip_end``,
        or ``post_window_timeout`` seconds elapse.

        The gate is *footage presence* (a segment overlapping the end of the
        window exists on disk), which is the real correctness need and is
        already satisfied in the common case — so this adds no latency unless
        the trailing segment genuinely hasn't appeared yet (e.g. right at a
        segment boundary or after a brief recording gap).  Whether that footage
        is finalized vs still in-progress is logged for audit but not required:
        waiting for finalization would add up to one full segment-duration of
        latency to every clip for no benefit, since the frames are on disk.
        """
        if self._post_window_timeout <= 0:
            return
        probe_start = clip_end - timedelta(seconds=1)
        deadline = time.monotonic() + self._post_window_timeout
        while time.monotonic() < deadline:
            pending = []
            for m in monitors:
                worker = self._service.get_worker(m.index)
                if worker is None:
                    continue
                if not worker.buffer.get_segments_between(probe_start, clip_end):
                    pending.append(m.display_name)
            if not pending:
                finalized = all(
                    (w := self._service.get_worker(m.index)) is None
                    or w.buffer.has_finalized_through(clip_end)
                    for m in monitors
                )
                log.debug(
                    "Post-event footage ready (finalized={}).", finalized
                )
                return
            log.debug("Awaiting post-event footage for: {}", pending)
            time.sleep(0.5)
        log.warning(
            "Post-event footage incomplete after {}s — building with what is "
            "available.",
            self._post_window_timeout,
        )

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
