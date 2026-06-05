from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from loguru import logger

from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg


class MonitorPreviewService:
    """
    Extracts JPEG thumbnail frames from each monitor's latest recorded segment.

    Why this approach
    -----------------
    The recording service already captures each monitor via gdigrab and writes
    MPEG-TS segments to disk.  Using those same segments as the preview source
    means:

    - No second capture process (no GPU/DXGI session contention).
    - Guaranteed to show exactly what is being recorded.
    - Works for *any* monitor regardless of virtual-desktop position, GPU, or
      DWM compositor state — because FFmpeg's gdigrab already solved that.

    The previous approach (QScreen.grabWindow / ScreenCapture) failed for
    monitors at negative virtual-desktop coordinates or on secondary GPUs.
    This approach is immune to those issues.

    Interval: every ``extract_interval_seconds`` a background thread extracts
    one JPEG frame per monitor and calls ``on_frame_ready(monitor_index, jpeg_bytes)``.
    The caller (AppBridge) pushes those bytes into the MonitorScreenshotProvider
    and increments previewRevision so QML re-fetches the image.

    Frame timing: uses ``-sseof -<seek_back_seconds>`` to get a frame near the
    end of the current segment (i.e., within ``seek_back_seconds`` of now).
    Falls back to the first frame if the seek fails.
    """

    def __init__(
        self,
        segment_dirs: dict[int, Path],
        on_frame_ready: Callable[[int, bytes], None],
        extract_interval_seconds: float = 3.0,
        seek_back_seconds: float = 5.0,
        thumbnail_width: int = 640,
    ) -> None:
        """
        Parameters
        ----------
        segment_dirs:
            {monitor_index: path_to_segment_directory}
        on_frame_ready:
            Called from the service thread with (monitor_index, jpeg_bytes).
            The caller must marshal to the UI thread if needed.
        extract_interval_seconds:
            How often to extract a new frame per monitor.
        seek_back_seconds:
            How many seconds from the end of the latest segment to seek to.
            Gives a near-real-time preview.
        thumbnail_width:
            Output thumbnail width in pixels (height auto-scaled).
        """
        self._segment_dirs    = dict(segment_dirs)
        self._on_frame_ready  = on_frame_ready
        self._interval        = extract_interval_seconds
        self._seek_back       = seek_back_seconds
        self._thumb_width     = thumbnail_width

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="monitor-preview",
        )
        self._thread.start()
        logger.info(
            "MonitorPreviewService started — {} monitor(s), interval={}s.",
            len(self._segment_dirs),
            self._interval,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("MonitorPreviewService stopped.")

    def add_monitor(self, monitor_index: int, segment_dir: Path) -> None:
        """Register a new monitor (called when MonitorDetectionService adds one)."""
        self._segment_dirs[monitor_index] = segment_dir
        logger.info("MonitorPreviewService: added monitor idx={}.", monitor_index)

    def remove_monitor(self, monitor_index: int) -> None:
        """Unregister a disconnected monitor."""
        self._segment_dirs.pop(monitor_index, None)
        logger.info("MonitorPreviewService: removed monitor idx={}.", monitor_index)

    # ── Internal loop ─────────────────────────────────────────────────

    def _loop(self) -> None:
        while not self._stop_event.wait(self._interval):
            for idx, seg_dir in list(self._segment_dirs.items()):
                if self._stop_event.is_set():
                    break
                self._extract_frame(idx, seg_dir)

    def _extract_frame(self, monitor_idx: int, segment_dir: Path) -> None:
        latest = self._latest_segment(segment_dir)
        if latest is None:
            logger.debug(
                "MonitorPreviewService: no segments yet for monitor idx={}.", monitor_idx
            )
            return

        jpeg = self._run_ffmpeg(latest, seek=True)
        if jpeg is None:
            # Seeking failed (segment too short) — grab first frame instead
            jpeg = self._run_ffmpeg(latest, seek=False)

        if jpeg:
            try:
                self._on_frame_ready(monitor_idx, jpeg)
            except Exception:
                logger.exception("MonitorPreviewService: on_frame_ready callback raised.")
        else:
            logger.warning(
                "MonitorPreviewService: failed to extract frame from {} (monitor idx={}).",
                latest.name, monitor_idx,
            )

    def _latest_segment(self, segment_dir: Path) -> Optional[Path]:
        """Return the most recently modified .ts file, or None."""
        try:
            ts_files = list(segment_dir.glob("seg_*.ts"))
            if not ts_files:
                return None
            return max(ts_files, key=lambda p: p.stat().st_mtime)
        except OSError:
            return None

    def _run_ffmpeg(self, ts_path: Path, seek: bool) -> Optional[bytes]:
        """Run FFmpeg to extract one JPEG frame from ``ts_path``.

        When ``seek=True`` uses ``-sseof`` to get a recent frame near the end.
        When ``seek=False`` grabs the first available frame (faster, older).
        """
        ffmpeg = resolve_ffmpeg()
        scale_filter = f"scale={self._thumb_width}:-2"

        # Output format: -f mjpeg pipe:1  — writes JPEG bytes to stdout.
        # "-f image2pipe -vcodec mjpeg -" is unreliable across FFmpeg versions;
        # "-f mjpeg pipe:1" is the canonical stdout JPEG output.
        output_args = ["-vf", scale_filter, "-vframes", "1", "-q:v", "2", "-f", "mjpeg", "pipe:1"]

        if seek:
            cmd = [
                ffmpeg, "-y",
                "-sseof", f"-{self._seek_back}",
                "-i", str(ts_path),
                *output_args,
            ]
        else:
            cmd = [
                ffmpeg, "-y",
                "-i", str(ts_path),
                *output_args,
            ]

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,   # capture stderr so we can log failures
                timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0 and result.stdout:
                logger.debug(
                    "MonitorPreviewService: extracted {}B JPEG from {} (seek={}).",
                    len(result.stdout), ts_path.name, seek,
                )
                return result.stdout
            # Log a compact FFmpeg error tail for diagnosis
            stderr_tail = (result.stderr or b"").decode("utf-8", errors="replace")[-300:]
            logger.debug(
                "MonitorPreviewService: ffmpeg rc={} seek={} file={}\n{}",
                result.returncode, seek, ts_path.name, stderr_tail,
            )
            return None
        except subprocess.TimeoutExpired:
            logger.warning(
                "MonitorPreviewService: ffmpeg timed out extracting frame from {}.",
                ts_path.name,
            )
            return None
        except Exception:
            logger.exception(
                "MonitorPreviewService: error extracting frame from {}.",
                ts_path.name,
            )
            return None
