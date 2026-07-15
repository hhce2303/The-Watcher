from __future__ import annotations

import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from collections.abc import Callable

from app.adapters.ffmpeg.builder_process_mixin import FfmpegBuilderExecutorMixin
from app.adapters.ffmpeg.clip_window import floor_to_window
from app.adapters.ffmpeg.encoder_selector import codec_tag, effective_codec
from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.adapters.ffmpeg.process_guard import run_batched_ffmpeg
from app.core.recording_service.models import Segment


class RecordingClipBuilder(FfmpegBuilderExecutorMixin):
    """
    Assembles one monitor's MPEG-TS segments into rolling MP4 clips.

    Clip closing conditions (whichever fires first)
    ------------------------------------------------
    TIME:  ``window_minutes`` elapsed since the clip window started.
    SIZE:  accumulated raw segment bytes exceed ``max_size_mb`` MB.

    Wall-clock boundary enforcement (mandatory requirement)
    --------------------------------------------------------
    A clip must never straddle an hour boundary. Grouping-by-start alone
    (``floor_to_window`` on ``segment.started_at``) is not enough: a segment
    that starts before ``:00:00`` but finalizes after it used to be counted
    whole into the closing window, dragging its content up to one
    ``SEGMENT_DURATION`` past the hour. Whenever a finalized segment's own
    span crosses a boundary, ``on_segment_finalized``/``recover_from_segments``
    now split its CONTENT across both windows using FFmpeg concat-demuxer
    ``inpoint``/``outpoint`` directives (the same technique
    ``FFmpegTrimAdapter`` already uses for event clips, no re-encode) — the
    closing window's clip ends exactly at the boundary and the new window's
    clip begins exactly there, even though the underlying segment FILE isn't
    cut at that instant (the raw FFmpeg segmenter is untouched).

    Output naming: ``{YYYY-MM-DD_HH-MM-SS}_m{monitor_index}.mp4``

    Build pipeline
    --------------
    on_segment_finalized() called once per segment as it completes.
    Internally this accumulates segments per window and submits builds to a
    single-worker executor — meaning builds never overlap and later builds
    always supersede earlier ones for the same output file.

    Startup recovery
    ----------------
    Call ``recover_from_segments(segments)`` once with ALL existing segments
    instead of calling ``on_segment_finalized`` in a loop.  This batches
    segments by window and submits exactly ONE build per window, avoiding
    the redundant N-builds-per-window problem.
    """

    def __init__(
        self,
        output_dir: Path,
        monitor_index: int,
        window_minutes: int = 60,
        max_size_mb: int = 3072,
        on_clip_ready: "Callable[[Path, str, datetime], None] | None" = None,
        codec: str = "h264",
    ) -> None:
        self._output_dir    = output_dir
        self._monitor_idx   = monitor_index
        self._window_mins   = window_minutes
        self._max_bytes     = max_size_mb * 1024 * 1024
        self._on_clip_ready = on_clip_ready   # fired after atomic rename in _build()
        self._codec         = codec           # for hvc1 MP4 tag on HEVC stream-copy

        self._lock        = threading.Lock()
        self._windows: dict[datetime, list[Segment]]  = defaultdict(list)
        self._win_sizes: dict[datetime, int]           = defaultdict(int)
        # Real wall-clock start of each window's earliest segment — first-seen-wins,
        # used for the output FILENAME. `ws` (the floor boundary) stays the internal
        # bucket/grouping key so multi-monitor combining is unaffected.
        self._win_real_start: dict[datetime, datetime] = {}

        self._init_ffmpeg_executor(
            thread_name_prefix=f"clip-m{monitor_index}",
            log_label=f"[clip m{monitor_index}]",
        )

        output_dir.mkdir(parents=True, exist_ok=True)
        self._purge_stale_temps()

        logger.info(
            "[clip m{}] Initialized — window={}min  max_size={}MB  output={}",
            monitor_index, window_minutes, max_size_mb, output_dir,
        )

    # ── Public API ────────────────────────────────────────────────────

    def on_segment_finalized(self, segment: Segment, monitor_index: int) -> None:
        """Called each time a segment file is complete (live recording path)."""
        seg_size = segment.size_bytes

        with self._lock:
            ws = floor_to_window(segment.started_at, self._window_mins)
            boundary = ws + timedelta(minutes=self._window_mins)

            if segment.ended_at > boundary:
                # Mandatory hour-alignment: this segment's own span crosses the
                # boundary (e.g. started 16:59:33, finalized 17:04:33 with
                # SEGMENT_DURATION=300) — split it across both windows instead
                # of counting it whole into the one it started in.
                self._close_straddling_segment_locked(ws, boundary, segment, seg_size)
                return

            # Size-overflow: flush window early when adding this segment would
            # exceed the limit, then open a new window for the segment.
            if (
                self._win_sizes[ws] + seg_size > self._max_bytes
                and self._windows[ws]
            ):
                logger.info(
                    "[clip m{}] Size overflow at window {} ({:.1f} MB) — flushing early.",
                    self._monitor_idx,
                    ws.strftime("%H:%M"),
                    (self._win_sizes[ws] + seg_size) / 1_048_576,
                )
                self._flush_window_locked(ws)
                ws = ws + timedelta(minutes=self._window_mins)

            # First-seen-wins: must run AFTER the overflow reassignment above so a
            # freshly-opened post-overflow bucket seeds from the segment that
            # actually opened it, not the old bucket's real start.
            self._win_real_start.setdefault(ws, segment.started_at)

            if segment.path not in {s.path for s in self._windows[ws]}:
                self._windows[ws].append(segment)
                self._windows[ws].sort(key=lambda s: s.started_at)
                self._win_sizes[ws] += seg_size

            segs_snap = list(self._windows[ws])
            size_snap = self._win_sizes[ws]
            real_start = self._win_real_start[ws]
            # A window whose real_start was forced ahead of its earliest
            # segment's own disk-start (only happens via a prior boundary
            # split, below) needs that leading segment's front trimmed.
            clip_start = real_start if real_start > segs_snap[0].started_at else None

        window_key = ws.strftime("%Y-%m-%d_%H-%M-%S")
        output = self._window_output(real_start)
        logger.debug(
            "[clip m{}] Window {} — {} seg(s), {:.1f} MB raw → queuing build for {}",
            self._monitor_idx,
            ws.strftime("%H:%M"),
            len(segs_snap),
            size_snap / 1_048_576,
            output.name,
        )
        self._submit_build(segs_snap, output, size_snap, window_key, real_start, clip_start=clip_start)

    def _close_straddling_segment_locked(
        self, ws: datetime, boundary: datetime, segment: Segment, seg_size: int,
    ) -> None:
        """A finalized segment's own span crosses ``boundary``: append it to its
        native window ``ws`` (trimmed to end at ``boundary``) AND to the next
        window (trimmed to start at ``boundary``), then submit both builds.
        Must hold ``self._lock`` (called only from ``on_segment_finalized``).
        """
        if segment.path not in {s.path for s in self._windows[ws]}:
            self._windows[ws].append(segment)
            self._windows[ws].sort(key=lambda s: s.started_at)
            self._win_sizes[ws] += seg_size

        closing_segs = list(self._windows[ws])
        closing_real_start = self._win_real_start.get(ws, closing_segs[0].started_at)
        closing_size = self._win_sizes[ws]
        closing_key = ws.strftime("%Y-%m-%d_%H-%M-%S")
        closing_output = self._window_output(closing_real_start)

        # This window is done for good — time only moves forward, so no future
        # segment can ever floor into it again (unlike an overflow re-open,
        # which stays live for the rest of the current window).
        self._windows.pop(ws, None)
        self._win_sizes.pop(ws, None)
        self._win_real_start.pop(ws, None)

        new_ws = boundary  # floor_to_window(boundary, ...) == boundary exactly
        self._win_real_start.setdefault(new_ws, boundary)
        if segment.path not in {s.path for s in self._windows[new_ws]}:
            self._windows[new_ws].append(segment)
            self._win_sizes[new_ws] += seg_size
        new_real_start = self._win_real_start[new_ws]
        new_output = self._window_output(new_real_start)

        logger.info(
            "[clip m{}] Segment {} straddles {} — closing {} at cut, opening {} from cut.",
            self._monitor_idx, segment.path.name, boundary.strftime("%H:%M:%S"),
            closing_output.name, new_output.name,
        )
        self._submit_build(
            closing_segs, closing_output, closing_size, closing_key, closing_real_start,
            clip_end=boundary,
        )
        self._submit_build(
            list(self._windows[new_ws]), new_output, self._win_sizes[new_ws],
            new_ws.strftime("%Y-%m-%d_%H-%M-%S"), new_real_start,
            clip_start=new_real_start,
        )

    def recover_from_segments(self, all_segments: list[Segment]) -> None:
        """Startup recovery: group by window, ONE build per window.

        Never call ``on_segment_finalized`` in a loop for recovery — that
        queues N redundant builds for the same output and the ``output.exists()``
        guard stops all but the first.  This method is the correct entry point.

        Same wall-clock boundary enforcement as the live path: a segment whose
        own span crosses a window boundary is bucketed into BOTH windows (its
        tail also belongs to the next one), trimmed at build time below —
        otherwise a historical straddling segment would reproduce the same
        "clip runs past the hour" bug on recovery.
        """
        by_window: dict[datetime, list[Segment]] = defaultdict(list)
        for seg in all_segments:
            ws = floor_to_window(seg.started_at, self._window_mins)
            by_window[ws].append(seg)
            boundary = ws + timedelta(minutes=self._window_mins)
            if seg.ended_at > boundary:
                by_window[boundary].append(seg)

        queued = 0
        for ws in sorted(by_window):
            segs = sorted(by_window[ws], key=lambda s: s.started_at)
            boundary = ws + timedelta(minutes=self._window_mins)
            # max(): a window whose only content is a carried-over tail from a
            # straddling segment (segs[0].started_at < ws) starts exactly at
            # the boundary, not at that earlier segment's real disk-start.
            default_real_start = max(ws, segs[0].started_at)
            with self._lock:
                self._win_real_start.setdefault(ws, default_real_start)
                real_start = self._win_real_start[ws]
            window_key = ws.strftime("%Y-%m-%d_%H-%M-%S")
            output = self._window_output(real_start)
            clip_start = real_start if real_start > segs[0].started_at else None
            clip_end = boundary if segs[-1].ended_at > boundary else None

            if output.exists():
                logger.debug(
                    "[clip m{}] Recovery: {} already exists — skipping.",
                    self._monitor_idx, output.name,
                )
                # Seed internal state so future on_segment_finalized calls are
                # aware of these segments and can extend the window correctly.
                with self._lock:
                    for seg in segs:
                        if seg.path not in {s.path for s in self._windows[ws]}:
                            self._windows[ws].append(seg)
                            self._win_sizes[ws] += seg.size_bytes
                continue

            total_size = sum(s.size_bytes for s in segs)
            with self._lock:
                self._windows[ws] = list(segs)
                self._win_sizes[ws] = total_size

            logger.info(
                "[clip m{}] Recovery: queuing {} — {} segment(s), {:.1f} MB raw",
                self._monitor_idx, output.name, len(segs), total_size / 1_048_576,
            )
            self._submit_build(
                segs, output, total_size, window_key, real_start,
                clip_start=clip_start, clip_end=clip_end,
            )
            queued += 1

        if queued:
            logger.info(
                "[clip m{}] Recovery: {} window(s) queued for assembly.",
                self._monitor_idx, queued,
            )
        else:
            logger.info(
                "[clip m{}] Recovery: all existing clips up-to-date, nothing to rebuild.",
                self._monitor_idx,
            )

    # ── Private helpers ───────────────────────────────────────────────

    def _window_output(self, real_start: datetime) -> Path:
        ts = real_start.strftime("%Y-%m-%d_%H-%M-%S")
        return self._output_dir / f"{ts}_m{self._monitor_idx}.mp4"

    def _flush_window_locked(self, ws: datetime) -> None:
        """Submit a build for ``ws`` and clear its state. Must hold self._lock."""
        segs = list(self._windows[ws])
        size = self._win_sizes[ws]
        if segs:
            real_start = self._win_real_start.get(ws, segs[0].started_at)
            window_key = ws.strftime("%Y-%m-%d_%H-%M-%S")
            output = self._window_output(real_start)
            self._submit_build(segs, output, size, window_key, real_start)
        self._windows.pop(ws, None)
        self._win_sizes.pop(ws, None)
        self._win_real_start.pop(ws, None)

    def _submit_build(
        self,
        segments: list[Segment],
        output: Path,
        raw_size: int,
        window_key: str,
        real_start: datetime,
        clip_start: "datetime | None" = None,
        clip_end: "datetime | None" = None,
    ) -> None:
        try:
            self._executor.submit(
                self._build, list(segments), output, raw_size, window_key, real_start,
                clip_start, clip_end,
            )
        except RuntimeError:
            logger.debug("[clip m{}] Executor shut down; skipping build.", self._monitor_idx)

    def _purge_stale_temps(
        self, *, max_age_seconds: float | None = None, exclude: Path | None = None
    ) -> None:
        """Remove leftover ``*.tmp.mp4`` files belonging to THIS monitor.

        ``_output_dir`` is shared across every monitor's builder (see
        ``build_recording_backend`` in ``runtime/backend.py``), and a new
        builder is constructed live on hot-plug (``_hot_add`` in ``main.py``)
        — not only at cold startup. An unscoped glob here would delete
        another monitor's in-flight ``.tmp.mp4`` the moment a second monitor
        is plugged in mid-recording, so the glob is scoped to this monitor's
        own filename suffix (``_window_output`` always appends ``_m{idx}``).

        With ``max_age_seconds=None`` (startup/hot-plug path) every matching
        tmp is removed unconditionally — safe because no build for THIS
        monitor is running yet at construction time. Called with a threshold
        from ``_build()`` it only sweeps tmps older than that (and skips
        ``exclude``, the current build's own tmp), so a tmp orphaned by a
        mid-write crash gets cleaned on the next segment cycle instead of
        surviving until the next full app restart.
        """
        now = time.time()
        for stale in self._output_dir.glob(f"*_m{self._monitor_idx}.tmp.mp4"):
            if exclude is not None and stale == exclude:
                continue
            if max_age_seconds is not None:
                try:
                    age = now - stale.stat().st_mtime
                except OSError:
                    continue
                if age < max_age_seconds:
                    continue
            try:
                stale.unlink()
                logger.info("[clip m{}] Removed stale temp: {}", self._monitor_idx, stale.name)
            except OSError:
                pass

    def _build(
        self,
        segments: list[Segment],
        output: Path,
        raw_size_bytes: int,
        window_key: str,
        real_start: datetime,
        clip_start: "datetime | None" = None,
        clip_end: "datetime | None" = None,
    ) -> None:
        """Concat segments → MP4.  Runs in single-worker executor (never concurrent).

        ``clip_start``/``clip_end`` are only set when a segment straddles a
        wall-clock window boundary (see ``_close_straddling_segment_locked``)
        — they write FFmpeg concat-demuxer ``inpoint``/``outpoint`` directives
        (same technique as ``FFmpegTrimAdapter._write_concat_file``, no
        re-encode) so the straddling segment is cut exactly at the boundary
        instead of being included whole. ``None`` (the common case) preserves
        the existing whole-segment behaviour exactly.
        """
        available = [s for s in segments if s.path.exists()]
        if not available:
            logger.warning(
                "[clip m{}] No segment files on disk for {} — skipping.",
                self._monitor_idx, output.name,
            )
            return

        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix(".tmp.mp4")
        concat_file: Path | None = None

        # Opportunistic sweep: a tmp orphaned by a mid-write crash (whole-app
        # kill, not just ffmpeg) would otherwise survive until the next full
        # restart's __init__ purge. 2h safely exceeds the 3600s build timeout
        # below, and the single-worker executor guarantees no other build is
        # ever in flight to be mistaken for stale.
        self._purge_stale_temps(max_age_seconds=2 * 3600, exclude=tmp)

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                concat_file = Path(f.name)
                for seg in available:
                    safe_path = seg.path.as_posix().replace("'", r"'\''")
                    f.write(f"file '{safe_path}'\n")
                    if clip_start is None and clip_end is None:
                        continue
                    seg_duration = seg.duration_seconds
                    inpoint = max(
                        0.0, ((clip_start - seg.started_at).total_seconds() if clip_start else 0.0)
                    )
                    outpoint = min(
                        seg_duration,
                        (clip_end - seg.started_at).total_seconds() if clip_end else seg_duration,
                    )
                    if inpoint > 0.1:
                        f.write(f"inpoint {inpoint:.3f}\n")
                    if outpoint < seg_duration - 0.1:
                        f.write(f"outpoint {outpoint:.3f}\n")

            cmd = [
                resolve_ffmpeg(),
                "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-c", "copy",
                # HEVC streams copied from MPEG-TS into MP4 must carry the hvc1
                # tag for QuickTime / Media Foundation to recognise them.
                # effective_codec() reflects any encoder fallback (e.g. HEVC→H.264).
                *codec_tag(effective_codec(self._codec)),
                "-movflags", "+faststart",
                "-y", str(tmp),
            ]

            logger.info(
                "[clip m{}] Building {} — {} segment(s)  {:.1f} MB raw  window={}min",
                self._monitor_idx,
                output.name,
                len(available),
                raw_size_bytes / 1_048_576,
                self._window_mins,
            )

            label = f"clip-m{self._monitor_idx}"

            on_started, on_finished = self._process_tracking_callbacks()
            result = run_batched_ffmpeg(
                cmd, label=label, timeout=3600,
                on_started=on_started, on_finished=on_finished,
            )

            if result.returncode == 0:
                tmp.replace(output)
                size_mb = output.stat().st_size / 1_048_576
                logger.info(
                    "[clip m{}] ✓ {} — {:.1f} MB final",
                    self._monitor_idx, output.name, size_mb,
                )
                # Notify CombinedClipBuilder (or any listener) that this clip is ready.
                if self._on_clip_ready is not None:
                    try:
                        self._on_clip_ready(output, window_key, real_start)
                    except Exception:
                        logger.exception("[clip m{}] on_clip_ready callback raised.", self._monitor_idx)
                if output.stat().st_size > self._max_bytes:
                    logger.warning(
                        "[clip m{}] {} exceeds size limit ({:.0f} MB > {} MB). "
                        "Reduce CLIP_WINDOW_MINUTES or CLIP_MAX_SIZE_MB.",
                        self._monitor_idx,
                        output.name,
                        size_mb,
                        self._max_bytes // 1_048_576,
                    )
            else:
                tmp.unlink(missing_ok=True)
                err = (result.stderr or b"").decode("utf-8", errors="replace")[-2000:]
                logger.error(
                    "[clip m{}] ✗ {} (rc={}):\n{}",
                    self._monitor_idx, output.name, result.returncode, err,
                )

        except subprocess.TimeoutExpired:
            tmp.unlink(missing_ok=True)
            logger.error("[clip m{}] Timeout building {}", self._monitor_idx, output.name)
        except Exception:
            tmp.unlink(missing_ok=True)
            logger.exception("[clip m{}] Error building {}", self._monitor_idx, output.name)
        finally:
            if concat_file is not None:
                concat_file.unlink(missing_ok=True)


# ── Backwards-compatibility alias ─────────────────────────────────────────────

class HourlyRecordingBuilder(RecordingClipBuilder):
    """Alias kept for call-site compatibility. New code should use RecordingClipBuilder."""

    def __init__(
        self,
        output_dir: Path,
        monitor_count: int = 1,
        monitor_index: int | None = None,
        window_minutes: int = 60,
        max_size_mb: int = 3072,
        on_clip_ready: "Callable[[Path, str, datetime], None] | None" = None,
        codec: str = "h264",
    ) -> None:
        super().__init__(
            output_dir=output_dir,
            monitor_index=monitor_index if monitor_index is not None else 0,
            window_minutes=window_minutes,
            max_size_mb=max_size_mb,
            on_clip_ready=on_clip_ready,
            codec=codec,
        )

    def on_segment_finalized(self, segment: Segment, monitor_index: int) -> None:
        super().on_segment_finalized(segment, monitor_index)
