from __future__ import annotations

import subprocess
import tempfile
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from collections.abc import Callable

from app.adapters.ffmpeg.encoder_selector import codec_tag, effective_codec
from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.adapters.ffmpeg.process_guard import assign_to_job
from app.core.recording_service.models import Segment


def _floor_to_window(dt: datetime, window_minutes: int) -> datetime:
    """Round ``dt`` down to the nearest ``window_minutes`` boundary."""
    total_minutes = dt.hour * 60 + dt.minute
    floor_minutes = (total_minutes // window_minutes) * window_minutes
    return dt.replace(
        hour=floor_minutes // 60,
        minute=floor_minutes % 60,
        second=0,
        microsecond=0,
    )


class RecordingClipBuilder:
    """
    Assembles one monitor's MPEG-TS segments into rolling MP4 clips.

    Clip closing conditions (whichever fires first)
    ------------------------------------------------
    TIME:  ``window_minutes`` elapsed since the clip window started.
    SIZE:  accumulated raw segment bytes exceed ``max_size_mb`` MB.

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
        on_clip_ready: "Callable[[Path], None] | None" = None,
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

        self._proc_lock: threading.Lock = threading.Lock()
        self._active_proc: "subprocess.Popen | None" = None  # tracked for fast shutdown

        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix=f"clip-m{monitor_index}",
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
            ws = _floor_to_window(segment.started_at, self._window_mins)

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

            if segment.path not in {s.path for s in self._windows[ws]}:
                self._windows[ws].append(segment)
                self._windows[ws].sort(key=lambda s: s.started_at)
                self._win_sizes[ws] += seg_size

            segs_snap = list(self._windows[ws])
            size_snap = self._win_sizes[ws]

        output = self._window_output(ws)
        logger.debug(
            "[clip m{}] Window {} — {} seg(s), {:.1f} MB raw → queuing build for {}",
            self._monitor_idx,
            ws.strftime("%H:%M"),
            len(segs_snap),
            size_snap / 1_048_576,
            output.name,
        )
        self._submit_build(segs_snap, output, size_snap)

    def recover_from_segments(self, all_segments: list[Segment]) -> None:
        """Startup recovery: group by window, ONE build per window.

        Never call ``on_segment_finalized`` in a loop for recovery — that
        queues N redundant builds for the same output and the ``output.exists()``
        guard stops all but the first.  This method is the correct entry point.
        """
        by_window: dict[datetime, list[Segment]] = defaultdict(list)
        for seg in all_segments:
            ws = _floor_to_window(seg.started_at, self._window_mins)
            by_window[ws].append(seg)

        queued = 0
        for ws in sorted(by_window):
            segs = sorted(by_window[ws], key=lambda s: s.started_at)
            output = self._window_output(ws)

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
            self._submit_build(segs, output, total_size)
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

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        with self._proc_lock:
            if self._active_proc is not None:
                try:
                    self._active_proc.kill()
                except OSError:
                    pass
                self._active_proc = None
        logger.info("[clip m{}] Executor shut down.", self._monitor_idx)

    # ── Private helpers ───────────────────────────────────────────────

    def _window_output(self, ws: datetime) -> Path:
        ts = ws.strftime("%Y-%m-%d_%H-%M-%S")
        return self._output_dir / f"{ts}_m{self._monitor_idx}.mp4"

    def _flush_window_locked(self, ws: datetime) -> None:
        """Submit a build for ``ws`` and clear its state. Must hold self._lock."""
        segs = list(self._windows[ws])
        size = self._win_sizes[ws]
        if segs:
            output = self._window_output(ws)
            self._submit_build(segs, output, size)
        self._windows.pop(ws, None)
        self._win_sizes.pop(ws, None)

    def _submit_build(
        self, segments: list[Segment], output: Path, raw_size: int
    ) -> None:
        try:
            self._executor.submit(self._build, list(segments), output, raw_size)
        except RuntimeError:
            logger.debug("[clip m{}] Executor shut down; skipping build.", self._monitor_idx)

    def _purge_stale_temps(self) -> None:
        for stale in self._output_dir.glob("*.tmp.mp4"):
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
    ) -> None:
        """Concat segments → MP4.  Runs in single-worker executor (never concurrent)."""
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

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                concat_file = Path(f.name)
                for seg in available:
                    f.write(f"file '{seg.path.as_posix()}'\n")

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

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assign_to_job(proc)
            with self._proc_lock:
                self._active_proc = proc
            try:
                _, stderr_bytes = proc.communicate(timeout=3600)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise
            finally:
                with self._proc_lock:
                    self._active_proc = None

            if proc.returncode == 0:
                tmp.replace(output)
                size_mb = output.stat().st_size / 1_048_576
                logger.info(
                    "[clip m{}] ✓ {} — {:.1f} MB final",
                    self._monitor_idx, output.name, size_mb,
                )
                # Notify CombinedClipBuilder (or any listener) that this clip is ready.
                if self._on_clip_ready is not None:
                    try:
                        self._on_clip_ready(output)
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
                err = (stderr_bytes or b"").decode("utf-8", errors="replace")[-2000:]
                logger.error(
                    "[clip m{}] ✗ {} (rc={}):\n{}",
                    self._monitor_idx, output.name, proc.returncode, err,
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
        on_clip_ready: "Callable[[Path], None] | None" = None,
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
