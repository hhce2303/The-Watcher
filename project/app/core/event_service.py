from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from app.core.recording_service.clip_builder import ClipBuilder
from app.core.recording_service.models import EventContext


class EventService:
    """
    Handles manual event triggers with cooldown protection and delayed clip scheduling.

    Milestone 4 deliverable.

    Flow:
        1. trigger_manual_event() is called (from UI button or any adapter).
        2. Cooldown check — if last event was < cooldown_seconds ago, reject.
        3. Snapshot the event (monitor selection + window) at trigger time
           via ClipBuilder.snapshot_event() → EventContext.
        4. Schedule clip build to run post_seconds later (after post-recording window).
        5. At expiry: ClipBuilder.build(ctx) assembles the final MP4 from the
           frozen snapshot, so the result is deterministic even if the selection
           changed during the post-event window.

    The scheduler uses threading.Timer (daemon thread), so it never blocks
    the caller and does not prevent clean shutdown.
    """

    def __init__(
        self,
        clip_builder: ClipBuilder,
        post_seconds: int = 120,
        cooldown_seconds: int = 30,
        retry_delay_seconds: int = 30,
        on_clip_failed: Optional[Callable[[str], None]] = None,
        on_clip_built: Optional[Callable[["EventContext", Path], None]] = None,
    ) -> None:
        self._clip_builder = clip_builder
        self._post_seconds = post_seconds
        self._cooldown_seconds = cooldown_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._on_clip_failed = on_clip_failed
        # Fired after a successful build with (ctx, output_path). Used to persist
        # the event (EventStore + sidecar) so it appears as a timeline marker
        # (Fase 1). Never raises into the build path.
        self._on_clip_built = on_clip_built
        self._last_event_at: Optional[datetime] = None
        self._lock = threading.Lock()
        self._pending_timers: list[threading.Timer] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def trigger_manual_event(self) -> bool:
        """
        Trigger a manual recording event.

        Returns True if accepted, False if rejected by cooldown.
        """
        now = datetime.now(tz=timezone.utc)

        with self._lock:
            if self._last_event_at is not None:
                elapsed = (now - self._last_event_at).total_seconds()
                if elapsed < self._cooldown_seconds:
                    remaining = self._cooldown_seconds - elapsed
                    logger.warning(
                        "Event rejected — cooldown active ({:.0f}s remaining).",
                        remaining,
                    )
                    return False

            self._last_event_at = now

        # Freeze the monitor selection + window NOW (trigger time) so the clip
        # is deterministic even if the selection changes during the post-window.
        ctx = self._clip_builder.snapshot_event(now)
        logger.bind(phase="BUILD-EVENT", evt=ctx.event_id).info(
            "Event accepted at {} — {} monitor(s) snapshotted.",
            now.isoformat(),
            len(ctx.monitors),
        )
        self._schedule_clip_build(ctx)
        return True

    @property
    def last_event_at(self) -> Optional[datetime]:
        with self._lock:
            return self._last_event_at

    @property
    def cooldown_seconds(self) -> int:
        return self._cooldown_seconds

    def set_clips_dir(self, path: Path) -> None:
        """Delegate output directory change to the clip builder."""
        self._clip_builder.set_clips_dir(path)

    def stop(self) -> None:
        """Cancel all pending clip-build timers.  Call on app exit."""
        with self._lock:
            timers = list(self._pending_timers)
            self._pending_timers.clear()
        for t in timers:
            t.cancel()
        if timers:
            logger.info("EventService: {} pending timer(s) cancelled.", len(timers))

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def _schedule_clip_build(self, ctx: EventContext) -> None:
        timer = threading.Timer(
            self._post_seconds,
            self._execute_clip_build,
            args=(ctx, 1),
        )
        timer.daemon = True
        timer.start()
        with self._lock:
            self._pending_timers = [t for t in self._pending_timers if t.is_alive()]
            self._pending_timers.append(timer)
        logger.bind(phase="BUILD-EVENT", evt=ctx.event_id).info(
            "Clip build scheduled in {}s for event at {}",
            self._post_seconds,
            ctx.triggered_at.isoformat(),
        )

    def _execute_clip_build(self, ctx: EventContext, attempt: int = 1) -> None:
        log = logger.bind(phase="BUILD-EVENT", evt=ctx.event_id)
        try:
            output = self._clip_builder.build(ctx)
            if output:
                log.info("Clip created: {}", output)
                if self._on_clip_built is not None:
                    try:
                        self._on_clip_built(ctx, output)
                    except Exception:  # noqa: BLE001
                        log.exception("on_clip_built callback raised (ignored).")
            else:
                log.error(
                    "Clip build returned no output for event at {} (attempt {}).",
                    ctx.triggered_at.isoformat(),
                    attempt,
                )
                self._schedule_retry(ctx, attempt)
        except Exception:
            log.exception(
                "Unexpected error building clip for event at {} (attempt {}).",
                ctx.triggered_at.isoformat(),
                attempt,
            )
            self._schedule_retry(ctx, attempt)

    def _schedule_retry(self, ctx: EventContext, attempt: int) -> None:
        log = logger.bind(phase="BUILD-EVENT", evt=ctx.event_id)
        max_retries = 3
        if attempt >= max_retries:
            log.error(
                "Clip build permanently failed after {} attempts for event at {}. Giving up.",
                max_retries,
                ctx.triggered_at.isoformat(),
            )
            if self._on_clip_failed is not None:
                try:
                    ts = ctx.triggered_at.strftime("%H:%M:%S")
                    self._on_clip_failed(
                        f"No se pudo crear el clip del evento de las {ts} "
                        f"tras {max_retries} intentos."
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("on_clip_failed callback raised.")
            return
        next_attempt = attempt + 1
        log.info(
            "Scheduling clip build retry {}/{} in {}s for event at {}.",
            next_attempt,
            max_retries,
            self._retry_delay_seconds,
            ctx.triggered_at.isoformat(),
        )
        timer = threading.Timer(
            self._retry_delay_seconds,
            self._execute_clip_build,
            args=(ctx, next_attempt),
        )
        timer.daemon = True
        timer.start()
        with self._lock:
            self._pending_timers = [t for t in self._pending_timers if t.is_alive()]
            self._pending_timers.append(timer)
