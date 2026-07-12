from __future__ import annotations

import subprocess
import threading
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

from app.adapters.ffmpeg.builder_process_mixin import FfmpegBuilderExecutorMixin
from app.adapters.ffmpeg.clip_window import floor_to_window, parse_clip_start
from app.adapters.ffmpeg.encoder_selector import (
    codec_tag,
    effective_codec,
    get_encoder,
    quality_flags,
    tag_for_encoder,
)
from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.adapters.ffmpeg.process_guard import run_batched_ffmpeg


def _grid2_filter(n: int, cell: str = "1280x720") -> tuple[str, str]:
    """Build a filter_complex that arranges n clips in a fixed 2-column grid.

    Layout rules
    ────────────
    n=2 → 1 row:  [m0][m1]
    n=3 → 2 rows: [m0][m1] / [m2][■black]
    n=4 → 2 rows: [m0][m1] / [m2][m3]

    Each clip is scaled to ``cell`` (WxH) before layout.  A smaller cell keeps
    the combined grid well below 4K — the dominant driver of combined-clip file
    size.  Empty slots (n=3) are filled with a black frame of the same size.
    Using a 2-column grid rather than a panoramic hstack keeps the aspect ratio
    sensible for any monitor count and matches the user's review workflow.

    IMPORTANT: in FFmpeg filter_complex, colons separate options, so WxH
    dimensions MUST use 'x' (e.g. '1280x720'), NOT ':' (e.g. '1280:720').
    The scale filter accepts both forms; the color filter requires 'x'.
    """
    _CELL = cell          # 'x' notation required inside filter_complex
    _RATE = "30"

    parts: list[str] = []
    for i in range(n):
        parts.append(f"[{i}:v]scale={_CELL},setpts=PTS-STARTPTS[v{i}]")

    rows = (n + 1) // 2
    row_labels: list[str] = []

    for r in range(rows):
        left  = r * 2
        right = left + 1
        if right < n:
            parts.append(f"[v{left}][v{right}]hstack=inputs=2[row{r}]")
        else:
            # Pad empty right slot with black frame
            parts.append(
                f"color=c=black:s={_CELL}:r={_RATE},format=yuv420p[pad{r}]"
            )
            parts.append(f"[v{left}][pad{r}]hstack=inputs=2:shortest=1[row{r}]")
        row_labels.append(f"[row{r}]")

    if rows == 1:
        return ";".join(parts), "row0"

    stacked = "".join(row_labels)
    parts.append(f"{stacked}vstack=inputs={rows}:shortest=1[v]")
    return ";".join(parts), "v"


class CombinedClipBuilder(FfmpegBuilderExecutorMixin):
    """
    Listens for per-monitor clips and produces ONE combined multi-monitor MP4.

    Architecture
    ------------
    ``RecordingClipBuilder`` instances fire ``on_clip_ready(path)`` when each
    per-monitor clip is finalised.  This adapter collects those notifications,
    and once *all* expected monitors have reported for a given time window it
    submits an FFmpeg job that merges them side-by-side using ``hstack``.

    The individual per-monitor clips (``raw/``) are never touched — they remain
    available as independent recordings.

    Optionally, ``timestamp_adapter`` burns a wall-clock overlay into the
    combined clip after merging.

    Thread safety
    -------------
    ``on_clip_ready`` is called from ``RecordingClipBuilder``'s executor thread.
    Multiple monitors can fire concurrently.  An internal lock ensures only one
    combine job is submitted per time window.
    """

    def __init__(
        self,
        raw_dir: Path,
        output_dir: Path,
        monitor_count: int,
        timestamp_adapter=None,
        codec: str = "h264",
        cell_width: int = 1280,
        cell_height: int = 720,
        quality: int = 27,
        window_minutes: int = 60,
    ) -> None:
        """
        Parameters
        ----------
        raw_dir:
            Directory where per-monitor clips are written
            (``clips/raw/`` by convention).
        output_dir:
            Directory for combined clips (``clips/``).
        monitor_count:
            Number of monitors expected per time window.
        timestamp_adapter:
            Optional ``FFmpegTimestampAdapter`` — burns a wall-clock overlay
            into the combined clip after merging.
        window_minutes:
            Must match the per-monitor ``RecordingClipBuilder``'s
            ``window_minutes`` — used by ``recover()`` to re-derive the shared
            window bucket from a raw clip's real start time (there is no live
            callback available during startup recovery).
        """
        self._raw_dir    = raw_dir
        self._output_dir = output_dir
        self._n          = monitor_count
        self._ts_adapter = timestamp_adapter
        self._codec      = codec
        self._cell       = f"{cell_width}x{cell_height}"
        self._quality    = quality
        self._window_minutes = window_minutes

        self._lock      = threading.Lock()
        self._submitted: set[str] = set()       # window keys already queued/built
        self._seen_windows: set[str] = set()    # every window key a clip has arrived for
        # window_key -> per-monitor raw clip paths reporting into that window.
        # Populated directly from on_clip_ready/recover() callback data — NOT by
        # globbing/re-parsing filenames, since per-monitor filenames now embed
        # each monitor's own real start time and no longer share a common prefix.
        self._window_clips: dict[str, set[Path]] = defaultdict(set)
        # window_key -> earliest real start among monitors reporting into it —
        # used as the combined clip's own filename/overlay timestamp.
        self._window_real_start: dict[str, datetime] = {}

        self._init_ffmpeg_executor(thread_name_prefix="combined-clip", log_label="[combined]")

        output_dir.mkdir(parents=True, exist_ok=True)
        self._purge_stale_temps()
        logger.info(
            "[combined] Initialized — {} monitor(s)  raw={}  output={}  timestamp={}",
            monitor_count, raw_dir, output_dir,
            "yes" if timestamp_adapter else "no",
        )

    # ── Public API ────────────────────────────────────────────────────

    def _local_output(self, real_start: datetime) -> Path:
        """Combined clip path with LOCAL time in the filename.

        ``real_start`` is the earliest real per-monitor segment start time for
        this window (UTC) — the combined clip shown to users should use local
        time so the filename matches what they see on the system clock.

        Example (UTC-5 machine):
            real_start  2026-05-30 05:00:03 UTC
            output      clips/2026-05-30_00-00-03.mp4
        """
        local_dt = real_start.astimezone()       # system local timezone
        local_key = local_dt.strftime("%Y-%m-%d_%H-%M-%S")
        return self._output_dir / f"{local_key}.mp4"

    def on_clip_ready(self, clip_path: Path, window_key: str, real_start: datetime) -> None:
        """Called by RecordingClipBuilder when a per-monitor clip is finalised.

        Runs in the individual builder's executor thread — must be thread-safe.
        ``window_key`` is the shared floor-based bucket string (identical across
        every monitor reporting into the same hour, e.g. "2026-05-31_10-00-00");
        ``real_start`` is THIS monitor's own real segment start time (per-monitor
        filenames now embed real start, not the floor, so they no longer share a
        common string prefix — the combining logic below never re-derives
        ``window_key``/paths from filenames, only from these callback args).

        A window is combined EXACTLY ONCE, and only after it is COMPLETE. The
        per-monitor builder rebuilds its clip on every new segment, so this
        callback fires repeatedly while a window grows from ~5 min toward the
        full hour. Combining the window while it is still the newest one in
        progress would freeze the combined clip at the first few minutes — the
        original "5-minute combined clip" bug. A window is therefore treated as
        complete only once a STRICTLY LATER window has produced a clip (i.e. the
        next hour has started); at that point every finished window is combined.
        Re-encoding the 4K grid once per completed window (instead of on every
        segment) also keeps CPU impact low.
        """
        to_build: list[tuple[list[Path], Path, str, datetime]] = []
        with self._lock:
            self._seen_windows.add(window_key)
            self._window_clips[window_key].add(clip_path)
            prev = self._window_real_start.get(window_key)
            if prev is None or real_start < prev:
                self._window_real_start[window_key] = real_start

            newest = max(self._seen_windows)
            for w in sorted(self._seen_windows):
                if w >= newest:
                    continue            # in-progress window — wait for the next hour
                if w in self._submitted:
                    continue
                available = sorted(
                    p for p in self._window_clips.get(w, ())
                    if p.exists() and ".tmp." not in p.name
                )
                if not available:
                    continue
                w_real_start = self._window_real_start[w]
                output = self._local_output(w_real_start)
                self._submitted.add(w)
                if output.exists():
                    continue
                to_build.append((list(available), output, w, w_real_start))

        for clips, output, w, w_real_start in to_build:
            logger.info(
                "[combined] Window {} complete ({} monitor(s)) → queuing combine.",
                w, len(clips),
            )
            self._submit(clips, output, w, w_real_start)

    def _submit(
        self, clips: list[Path], output: Path, window_key: str, real_start: datetime
    ) -> None:
        try:
            self._executor.submit(self._build, clips, output, window_key, real_start)
        except RuntimeError:
            logger.debug("[combined] Executor shut down; skipping {}.", window_key)

    def recover(self, backfill_hours: int | None = None) -> None:
        """Scan raw_dir for window clips that have no combined output yet and queue builds.

        Called once at startup after the recording service starts.  This handles:
        - Windows whose combine previously failed (e.g. filter_complex error)
        - Windows that were never triggered because recovery skipped calling on_clip_ready
        - Stale .tmp.mp4 files left by a crash mid-build

        Parameters
        ----------
        backfill_hours:
            When set, only windows whose start is within the last
            ``backfill_hours`` hours are rebuilt.  Older completed windows are
            left untouched — combining the whole history of per-monitor clips
            (which can span many days) would mean a long CPU/disk-heavy 4K
            re-encode burst on startup.  ``None`` rebuilds every missing window.
        """
        from datetime import timedelta  # noqa: PLC0415

        # Per-monitor filenames now embed each monitor's own real segment start
        # (not a shared floor prefix), so the window bucket has to be
        # RE-DERIVED by flooring each parsed real start — this reliably
        # reconstructs the same bucket across monitors because every real
        # start, by construction, floors into its own correctly-shared window.
        windows: dict[str, list[Path]] = defaultdict(list)
        window_real_start: dict[str, datetime] = {}
        for clip in self._raw_dir.glob("*_m*.mp4"):
            if ".tmp." in clip.name:
                continue
            real_start = parse_clip_start(clip)
            if real_start is None:
                logger.warning(
                    "[combined] Recovery: cannot parse start time from {} — skipping.",
                    clip.name,
                )
                continue
            window_key = floor_to_window(real_start, self._window_minutes).strftime(
                "%Y-%m-%d_%H-%M-%S"
            )
            windows[window_key].append(clip)
            prev = window_real_start.get(window_key)
            if prev is None or real_start < prev:
                window_real_start[window_key] = real_start

        if not windows:
            logger.info("[combined] Recovery: no per-monitor clips found.")
            return

        # The newest window may still be recording (its per-monitor clips will
        # keep growing). Skip it so we don't freeze a partial combine — the live
        # path combines it once the next hour starts. Seed internal state with
        # every window so that handoff works.
        newest = max(windows)
        with self._lock:
            self._seen_windows.update(windows.keys())
            for window_key, clips in windows.items():
                self._window_clips[window_key].update(clips)
            for window_key, real_start in window_real_start.items():
                prev = self._window_real_start.get(window_key)
                if prev is None or real_start < prev:
                    self._window_real_start[window_key] = real_start

        # Window keys are UTC timestamps; only backfill recent ones if asked.
        cutoff_key: str | None = None
        if backfill_hours is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=backfill_hours)
            cutoff_key = cutoff.strftime("%Y-%m-%d_%H-%M-%S")

        queued = 0
        skipped_old = 0
        for window_key in sorted(windows):
            if window_key >= newest:
                continue   # in-progress window — leave to the live path
            if cutoff_key is not None and window_key < cutoff_key:
                skipped_old += 1
                continue   # older than the backfill horizon — leave as-is
            clips = sorted(windows[window_key])
            w_real_start = self._window_real_start[window_key]
            output = self._local_output(w_real_start)
            if output.exists():
                continue
            with self._lock:
                if window_key in self._submitted:
                    continue
                self._submitted.add(window_key)
            logger.info(
                "[combined] Recovery: queuing {} ({} clip(s) available).",
                output.name, len(clips),
            )
            self._submit(clips, output, window_key, w_real_start)
            queued += 1

        if skipped_old:
            logger.info(
                "[combined] Recovery: skipped {} window(s) older than the {}h "
                "backfill horizon (left as-is).",
                skipped_old, backfill_hours,
            )
        if queued:
            logger.info("[combined] Recovery: {} combined clip(s) queued for building.", queued)
        else:
            logger.info("[combined] Recovery: all combined clips are up-to-date.")

    def _purge_stale_temps(self) -> None:
        for stale in self._output_dir.glob("*.tmp.mp4"):
            try:
                stale.unlink()
                logger.info("[combined] Removed stale temp: {}", stale.name)
            except OSError:
                logger.warning("[combined] Could not remove stale temp: {}", stale.name)

    # ── Build ─────────────────────────────────────────────────────────

    def _build(
        self,
        clips: list[Path],
        output: Path,
        window_key: str,
        real_start: datetime,
    ) -> None:
        """Merge per-monitor clips into one combined MP4. Runs in executor."""
        # Re-verify inside the job: only use final clips (no .tmp. in name)
        available = [c for c in clips if c.exists() and ".tmp." not in c.name]
        if not available:
            logger.warning("[combined] No clip files found for window {}.", window_key)
            return

        output.parent.mkdir(parents=True, exist_ok=True)
        tmp = output.with_suffix(".tmp.mp4")

        try:
            n = len(available)
            logger.info(
                "[combined] Building {} — {} clip(s): {}",
                output.name,
                n,
                [c.name for c in available],
            )

            # Wall-clock overlay is folded into THIS encode (single pass) rather
            # than burned by a second full transcode afterwards. real_start is
            # already UTC (segment timestamps are UTC) — using it directly here
            # (instead of the floor-based window_key) fixes a prior bug where the
            # burned-in timestamp could be off by up to the window length.
            drawtext: Optional[str] = None
            if self._ts_adapter is not None:
                try:
                    drawtext = self._ts_adapter.build_drawtext(real_start)
                except Exception:
                    logger.exception(
                        "[combined] drawtext build failed for {} — overlay skipped.",
                        output.name,
                    )

            cmd = [resolve_ffmpeg()]
            for clip in available:
                cmd += ["-i", str(clip)]

            if n == 1 and drawtext is None:
                # Single monitor, no overlay → lossless stream copy (full res).
                cmd += ["-c", "copy", *codec_tag(effective_codec(self._codec))]
            else:
                # Offline assembly → quality preset for best compression.
                encoder, encoder_flags = get_encoder(self._codec, realtime=False)
                if n == 1:
                    # Single monitor: keep full resolution, only overlay.
                    filter_complex = "[0:v]format=yuv420p[grid]"
                    out_label = "grid"
                else:
                    # 2-column grid: n=2 side-by-side, n=3 2×2 w/ black slot, n=4 2×2.
                    # Cells are downscaled (self._cell) — the main size lever.
                    filter_complex, out_label = _grid2_filter(n, cell=self._cell)
                if drawtext is not None:
                    filter_complex += f";[{out_label}]{drawtext}[vout]"
                    out_label = "vout"
                cmd += [
                    "-filter_complex", filter_complex,
                    "-map", f"[{out_label}]",
                    "-c:v", encoder, *encoder_flags, *quality_flags(encoder, self._quality),
                    "-pix_fmt", "yuv420p",
                    *tag_for_encoder(encoder),
                ]

            cmd += ["-movflags", "+faststart", "-y", str(tmp)]

            on_started, on_finished = self._process_tracking_callbacks()
            result = run_batched_ffmpeg(
                cmd, label="combined", timeout=3600,
                on_started=on_started, on_finished=on_finished,
            )

            if result.returncode != 0:
                tmp.unlink(missing_ok=True)
                err = (result.stderr or b"").decode("utf-8", errors="replace")[-2000:]
                logger.error(
                    "[combined] ✗ {} (rc={}):\n{}",
                    output.name, result.returncode, err,
                )
                with self._lock:
                    self._submitted.discard(window_key)   # allow retry on next on_clip_ready
                return

            tmp.replace(output)
            size_mb = output.stat().st_size / 1_048_576
            logger.info("[combined] ✓ {} — {:.1f} MB", output.name, size_mb)

        except subprocess.TimeoutExpired:
            tmp.unlink(missing_ok=True)
            logger.error("[combined] Timeout combining {}", output.name)
            with self._lock:
                self._submitted.discard(window_key)   # allow retry
        except Exception:
            tmp.unlink(missing_ok=True)
            logger.exception("[combined] Error combining {}", output.name)
            with self._lock:
                self._submitted.discard(window_key)
