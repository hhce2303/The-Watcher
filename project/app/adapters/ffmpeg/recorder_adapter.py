from __future__ import annotations

import re
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Set

from loguru import logger

from app.adapters.ffmpeg.encoder_selector import get_encoder, quality_flags
from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.adapters.ffmpeg.process_guard import assign_to_job
from app.core.ports.recorder_port import RecorderPort
from app.core.recording_service.models import MonitorInfo, Segment

# Grace period added on top of segment_duration for stall detection.
# The watchdog fires on_crash if no new segment appears within
# (segment_duration + _STALL_GRACE_SECONDS).  This prevents false alarms
# with long segments (e.g. 1-hour files) while still catching a hung FFmpeg.
_STALL_GRACE_SECONDS = 60

# Matches filenames produced by the -strftime 1 pattern: seg_YYYYMMDD_HHMMSS.ts
_SEGMENT_FILENAME_RE = re.compile(
    r"seg_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.ts$"
)


class FFmpegRecorderAdapter(RecorderPort):
    """
    FFmpeg-based continuous segment recorder.

    Captures one monitor via gdigrab using explicit virtual-desktop coordinates
    (offset_x, offset_y, video_size) from MonitorInfo — no DXGI session required.

    A background watchdog thread monitors the output directory. When a new
    segment file appears, the previous one is considered complete and is
    forwarded to the on_segment_ready callback for indexing.
    """

    def __init__(
        self,
        segment_duration: int = 10,
        framerate: int = 30,
        crf: int = 28,
        width: int = 1920,
        height: int = 1080,
        capture_source: str = "desktop",
        capture_backend: str = "auto",
        codec: str = "h264",
        on_segment_ready: Optional[Callable[[Segment], None]] = None,
        on_crash: Optional[Callable[[], None]] = None,
        preview_path: Optional[Path] = None,
        preview_fps: int = 2,
        preview_width: int = 1280,
    ) -> None:
        self._segment_duration = segment_duration
        self._framerate = framerate
        self._crf = crf
        self._width = width
        self._height = height
        self._capture_source = capture_source
        # Screen-capture backend.  "ddagrab" uses the DXGI Desktop Duplication
        # API (GPU frames, no GDI BitBlt) — this eliminates the on-screen mouse
        # cursor flicker caused by gdigrab's BitBlt(SRCCOPY|CAPTUREBLT), which
        # forces the display driver to hide/redraw the hardware cursor sprite on
        # every frame (~30x/s).  "gdigrab" is the legacy GDI backend, kept as a
        # fallback.  "auto" probes for ddagrab at start() and falls back to
        # gdigrab if the DXGI path is unavailable (older Windows / no D3D11).
        self._capture_backend = (capture_backend or "auto").lower()
        self._resolved_backend: Optional[str] = None
        self._ddagrab_probe: Optional[bool] = None
        self._codec = codec
        self._on_segment_ready = on_segment_ready
        self._on_crash = on_crash
        # When preview_path is set the FFmpeg command uses filter_complex split:
        # one stream → segment recording (full fps), another → JPEG preview (low fps).
        # This eliminates the need for a separate capture process and avoids the
        # double-gdigrab screen flickering caused by concurrent BitBlt calls.
        self._preview_path  = preview_path
        self._preview_fps   = preview_fps
        self._preview_width = preview_width
        self._monitors: list[MonitorInfo] = []
        self._monitors_lock = threading.RLock()

        self._process: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._output_dir: Optional[Path] = None
        self._watchdog_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._known_files: Set[str] = set()
        self._last_segment_time: float = 0.0
        # Rolling buffer of the last N stderr lines — dumped at ERROR level on crash.
        self._stderr_tail: deque[str] = deque(maxlen=30)

        # Phase-tagged logger (F2 CAPTURE). mon is filled once set_monitor runs.
        self._mon_tag = "-"
        self._log = logger.bind(phase="CAPTURE", mon=self._mon_tag)

    # ------------------------------------------------------------------
    # RecorderPort interface
    # ------------------------------------------------------------------

    def start(self, output_dir: Path) -> None:
        if self._process is not None:
            raise RuntimeError("Recorder is already running.")

        output_dir.mkdir(parents=True, exist_ok=True)
        self._output_dir = output_dir
        self._stop_event.clear()

        # Re-index any segments left on disk from a previous run so that
        # clips can be built immediately after a crash-restart.
        self._recover_existing_segments(output_dir)

        # Decide the capture backend once per process (memoised).  Doing it here
        # rather than in __init__ keeps the (potentially slow) ddagrab probe off
        # the constructor and out of unit tests that never start the recorder.
        self._resolved_backend = self._resolve_backend()

        cmd = self._build_ffmpeg_command(output_dir)
        self._log.info("Starting FFmpeg: {}", " ".join(cmd))

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assign_to_job(self._process)
        self._last_segment_time = time.monotonic()

        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            daemon=True,
            name="recorder-stderr",
        )
        self._stderr_thread.start()

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="recorder-watchdog",
        )
        self._watchdog_thread.start()
        self._log.info("Recorder started. Output: {}", output_dir)

    def stop(self) -> None:
        self._stop_event.set()
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._log.warning("FFmpeg did not stop in time — killed.")
            self._process = None
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=3)
            self._watchdog_thread = None
        if self._stderr_thread is not None:
            self._stderr_thread.join(timeout=3)
            self._stderr_thread = None
        self._log.info("Recorder stopped.")

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def update_codec(self, codec: str) -> None:
        """Change the codec used for encoding. Takes effect on the next start().

        Safe to call while the recorder is stopped (e.g. during a controlled
        restart triggered by the user changing the encoder in Settings).
        """
        self._codec = codec.lower()
        logger.info("Recorder codec updated to '{}' (takes effect on next start).", self._codec)

    def set_monitor(self, monitor: MonitorInfo) -> None:
        """Set the monitor to capture. Takes effect on the next start()."""
        with self._monitors_lock:
            self._monitors = [monitor]
        # Now that we know which screen this recorder serves, tag all its logs.
        self._mon_tag = f"m{monitor.index}"
        self._log = logger.bind(phase="CAPTURE", mon=self._mon_tag)
        self._log.info(
            "Capture monitor: {} (gdigrab region {}x{} @ {},{} on virtual desktop)",
            monitor.display_name,
            monitor.width,
            monitor.height,
            monitor.x,
            monitor.y,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_ffmpeg_command(self, output_dir: Path) -> list[str]:
        """Build the FFmpeg capture command for the configured monitor.

        Dispatches on the resolved capture backend:

        * ``ddagrab`` — DXGI Desktop Duplication (GPU frames, no GDI BitBlt).
          The default when available.  Eliminates the on-screen hardware-cursor
          flicker that gdigrab causes via ``BitBlt(SRCCOPY | CAPTUREBLT)``.
        * ``gdigrab`` — legacy GDI BitBlt backend, kept as a fallback.

        When ``preview_path`` is set, a single capture is split into a full-fps
        recording-segment stream and a low-fps JPEG preview stream, so there is
        only ever ONE screen-capture pipeline.
        """
        with self._monitors_lock:
            monitor = self._monitors[0] if self._monitors else None
        if monitor is None:
            raise RuntimeError("No monitor configured — call set_monitor() before start().")

        output_pattern = str(output_dir / "seg_%Y%m%d_%H%M%S.ts")
        # Live capture: real-time preset so FFmpeg keeps up with the screen.
        encoder, encoder_flags = get_encoder(self._codec, realtime=True)
        backend = self._resolved_backend or "gdigrab"

        self._log.info(
            "[RECORDER] {} — backend={} region={}x{} offset=({},{}) idx={} "
            "encoder={} preview={}",
            monitor.display_name, backend,
            monitor.width, monitor.height, monitor.x, monitor.y, monitor.index,
            encoder, self._preview_path or "off",
        )

        # Recording-segment output tail (shared by both backends and both the
        # dual-output and single-output variants).
        seg_out = [
            "-c:v", encoder, *encoder_flags,
            *quality_flags(encoder, self._crf),
            "-f", "segment",
            "-segment_time", str(self._segment_duration),
            "-segment_format", "mpegts",
            "-reset_timestamps", "1",
            "-strftime", "1",
            "-y", output_pattern,
        ]
        # Preview JPEG output tail (overwritten in place at preview_fps).
        prev_out = [
            "-q:v", "2",
            "-f", "image2",
            "-update", "1",
            "-y", str(self._preview_path),
        ]

        if backend == "ddagrab":
            # ddagrab is a *source* filter (no -i input): the filtergraph starts
            # with it, downloads GPU→system memory, then splits like gdigrab.
            src = self._ddagrab_source(monitor)
            if self._preview_path is not None:
                filt = (
                    f"{src},split=2[rec][prev];"
                    f"[rec]scale={self._width}:{self._height},format=yuv420p[recout];"
                    f"[prev]fps={self._preview_fps},scale={self._preview_width}:-2,"
                    f"format=yuv420p[prevout]"
                )
                return [
                    resolve_ffmpeg(), "-hide_banner",
                    "-filter_complex", filt,
                    "-map", "[recout]", *seg_out,
                    "-map", "[prevout]", *prev_out,
                ]
            filt = f"{src},scale={self._width}:{self._height},format=yuv420p[recout]"
            return [
                resolve_ffmpeg(), "-hide_banner",
                "-filter_complex", filt,
                "-map", "[recout]", *seg_out,
            ]

        # ── gdigrab (fallback) ──────────────────────────────────────────────
        gdi_input = [
            resolve_ffmpeg(),
            "-f", "gdigrab",
            "-framerate", str(self._framerate),
            "-offset_x", str(monitor.x),
            "-offset_y", str(monitor.y),
            "-video_size", f"{monitor.width}x{monitor.height}",
            "-draw_mouse", "0",
            "-i", "desktop",
        ]
        if self._preview_path is not None:
            filt = (
                f"[0:v]split=2[rec][prev];"
                f"[rec]scale={self._width}:{self._height},format=yuv420p[recout];"
                f"[prev]fps={self._preview_fps},scale={self._preview_width}:-2,"
                f"format=yuv420p[prevout]"
            )
            return [
                *gdi_input,
                "-filter_complex", filt,
                "-map", "[recout]", *seg_out,
                "-map", "[prevout]", *prev_out,
            ]
        vf_filter = f"scale={self._width}:{self._height},format=yuv420p"
        return [*gdi_input, "-vf", vf_filter, *seg_out]

    def _ddagrab_source(self, monitor: MonitorInfo) -> str:
        """Return the ddagrab source filterchain (up to the split point).

        ddagrab selects a monitor by DXGI ``output_idx`` (NOT virtual-desktop
        coordinates) and emits D3D11 GPU frames, so we immediately ``hwdownload``
        to system memory and pick ``bgra`` (ddagrab's native 8-bit format) before
        any software scaling/encoding.  ``draw_mouse=0`` keeps the cursor out of
        the recording exactly as the gdigrab path did — but unlike gdigrab this
        costs NO desktop-side CAPTUREBLT cursor flicker (the DDA composites the
        cursor GPU-side).  Whole-monitor capture needs only ``output_idx``; the
        existing ``scale`` filter downstream absorbs the physical-pixel size, so
        no offset/video_size (which would be physical-pixel intra-monitor crops).
        """
        output_idx = max(0, int(getattr(monitor, "index", 0) or 0))
        return (
            f"ddagrab=output_idx={output_idx}:framerate={self._framerate}:draw_mouse=0,"
            f"hwdownload,format=bgra"
        )

    def _resolve_backend(self) -> str:
        """Resolve the capture backend, honouring an explicit override.

        ``auto`` (default) prefers ddagrab (DXGI, no cursor flicker) and falls
        back to gdigrab if the DXGI path is unavailable on this machine.
        """
        if self._capture_backend in ("ddagrab", "gdigrab"):
            return self._capture_backend
        if self._ddagrab_available():
            self._log.info("Capture backend: ddagrab (DXGI Desktop Duplication).")
            return "ddagrab"
        self._log.warning(
            "ddagrab (DXGI) unavailable — falling back to gdigrab. "
            "The on-screen mouse cursor may flicker during capture."
        )
        return "gdigrab"

    def _ddagrab_available(self) -> bool:
        """Probe whether FFmpeg can capture via ddagrab here (memoised per instance).

        Captures two frames to the null muxer.  ``-frames:v`` is count-based, so
        it terminates cleanly even though ddagrab's ``dup_frames`` default keeps a
        static desktop emitting frames (a time-based ``-t`` would NOT stop it).
        """
        if self._ddagrab_probe is not None:
            return self._ddagrab_probe
        ok = False
        try:
            probe = [
                resolve_ffmpeg(), "-hide_banner", "-loglevel", "error",
                "-filter_complex",
                "ddagrab=output_idx=0:framerate=5,hwdownload,format=bgra",
                "-frames:v", "2", "-f", "null", "-",
            ]
            result = subprocess.run(
                probe,
                capture_output=True,
                timeout=12,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            ok = result.returncode == 0
            if not ok:
                tail = result.stderr.decode("utf-8", errors="replace").strip()[-400:]
                self._log.debug("ddagrab probe failed (rc={}): {}", result.returncode, tail)
        except Exception as exc:  # noqa: BLE001
            self._log.debug("ddagrab probe raised: {}", exc)
            ok = False
        self._ddagrab_probe = ok
        return ok

    def _recover_existing_segments(self, output_dir: Path) -> None:
        """Re-index .ts files left on disk from a previous run."""
        existing = sorted(output_dir.glob("seg_*.ts"), key=lambda f: f.name)
        if not existing:
            return

        self._log.info("Recovering {} segment(s) from previous run.", len(existing))
        for i, path in enumerate(existing):
            started_at = _parse_start_time(path.name)
            if started_at is None:
                self._known_files.add(path.name)
                continue

            if i < len(existing) - 1:
                next_started = _parse_start_time(existing[i + 1].name)
                ended_at = next_started or datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )
            else:
                ended_at = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )

            if ended_at > started_at:
                # Recovered files come from a dead process: they are complete.
                self._emit_segment(path, started_at, ended_at, finalized=True)
            self._known_files.add(path.name)

        self._log.info("Crash recovery complete — {} file(s) re-indexed.", len(existing))

    def _watchdog_loop(self) -> None:
        """
        Poll the output directory once per second.

        When a *new* segment file appears:
          1. Emit it immediately with an estimated end-time so clips can be
             assembled from the in-progress file without waiting a full hour.
          2. When the *next* segment arrives, re-emit the previous one with the
             accurate end-time (BufferManager.register_segment uses upsert).

        Also detects:
        - FFmpeg process exit (crash) — calls on_crash callback
        - Stalled output (no new segment for >segment_duration+grace) — calls on_crash
        """
        pending: Optional[tuple[Path, datetime]] = None

        while not self._stop_event.is_set():
            if self._output_dir is None:
                break

            # --- Crash detection: FFmpeg process exited unexpectedly ---
            if self._process is not None and self._process.poll() is not None:
                rc = self._process.returncode
                self._process = None
                if self._stop_event.is_set():
                    break  # intentional stop — do not trigger supervisor restart
                self._log.error("FFmpeg process exited unexpectedly (rc={}).", rc)
                self._fire_crash()
                break

            new_files = sorted(
                f for f in self._output_dir.glob("seg_*.ts")
                if f.name not in self._known_files
            )

            for path in new_files:
                started_at = _parse_start_time(path.name)
                if started_at is None:
                    logger.warning("Cannot parse timestamp from: {}", path.name)
                    self._known_files.add(path.name)
                    continue

                if pending is not None:
                    prev_path, prev_started = pending
                    # The previous segment's real end-time is now known (this
                    # new segment's start) — re-emit it as finalized.
                    self._emit_segment(
                        prev_path, prev_started, started_at, finalized=True
                    )

                estimated_end = started_at + timedelta(seconds=self._segment_duration)
                # In-progress: ended_at is only an estimate until the next segment.
                self._emit_segment(path, started_at, estimated_end, finalized=False)

                pending = (path, started_at)
                self._known_files.add(path.name)
                self._last_segment_time = time.monotonic()

            # --- Stall detection ---
            stall_threshold = self._segment_duration + _STALL_GRACE_SECONDS
            if (
                self._last_segment_time > 0
                and (time.monotonic() - self._last_segment_time) > stall_threshold
            ):
                if self._stop_event.is_set():
                    break  # intentional stop — do not trigger supervisor restart
                self._log.error(
                    "Recorder stalled — no new segment for {}s.", stall_threshold
                )
                self._last_segment_time = time.monotonic()
                self._fire_crash()
                break

            time.sleep(1.0)

        if pending is not None:
            prev_path, prev_started = pending
            # Recorder is stopping: the last open segment is now closed.
            self._emit_segment(
                prev_path, prev_started, datetime.now(tz=timezone.utc), finalized=True
            )

    def _emit_segment(
        self,
        path: Path,
        started_at: datetime,
        ended_at: datetime,
        finalized: bool = False,
    ) -> None:
        segment = Segment(
            path=path, started_at=started_at, ended_at=ended_at, finalized=finalized
        )
        self._log.debug("Segment ready: {}", path.name)
        if self._on_segment_ready is not None:
            self._on_segment_ready(segment)

    def _fire_crash(self) -> None:
        """Log the last FFmpeg stderr lines and invoke the on_crash callback."""
        tail = list(self._stderr_tail)
        if tail:
            self._log.error(
                "FFmpeg last output ({} lines):\n{}",
                len(tail),
                "\n".join(f"  [ffmpeg] {l}" for l in tail),
            )
        if self._on_crash is not None:
            try:
                self._on_crash()
            except Exception:  # noqa: BLE001
                logger.exception("on_crash callback raised an exception.")

    def _drain_stderr(self) -> None:
        """Read FFmpeg stderr, forward lines to the logger and keep a rolling tail."""
        proc = self._process
        if proc is None or proc.stderr is None:
            return
        try:
            for raw_line in proc.stderr:
                if self._stop_event.is_set():
                    break
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if line:
                    self._stderr_tail.append(line)
                    logger.debug("[ffmpeg] {}", line)
        except Exception as exc:  # noqa: BLE001
            logger.debug("stderr drain ended unexpectedly: {}", exc)


def _parse_start_time(filename: str) -> Optional[datetime]:
    match = _SEGMENT_FILENAME_RE.search(filename)
    if not match:
        return None
    year, month, day, hour, minute, second = (int(g) for g in match.groups())
    local_naive = datetime(year, month, day, hour, minute, second)
    return local_naive.astimezone(timezone.utc)
