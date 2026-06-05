from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Optional

from loguru import logger

from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.adapters.ffmpeg.process_guard import assign_to_job
from app.core.recording_service.models import MonitorInfo


# JPEG frame delimiters
_SOI = b'\xff\xd8'  # Start Of Image
_EOI = b'\xff\xd9'  # End Of Image


class LivePreviewService:
    """
    Real-time screen mirror for the Recording tab preview.

    Architecture
    ────────────
    One dedicated FFmpeg gdigrab process per active monitor captures at a
    low framerate (default 2 fps) and pipes raw MJPEG frames to stdout.
    A reader thread parses the byte stream, extracts complete JPEG frames
    by SOI/EOI delimiters, and fires ``on_frame_ready(monitor_idx, jpeg)``.

    Why gdigrab instead of QScreen.grabWindow / ScreenCapture
    ─────────────────────────────────────────────────────────
    gdigrab (GDI BitBlt) already proven to work for ALL monitors on this
    machine — including DISPLAY5 at a negative virtual-desktop Y coordinate
    and on a secondary GPU.  ScreenCapture (WGC) and grabWindow both failed
    for DISPLAY5 due to GPU boundary / DWM limitations.

    Independence from the recording pipeline
    ─────────────────────────────────────────
    This service has zero coupling to BufferManager, MonitorWorker, or
    segment files.  It captures live screen content at the current instant;
    it does NOT read or seek through recorded MPEG-TS data.  Segment
    extraction introduced inherent delays of several seconds; this approach
    has sub-second latency (determined only by the capture fps).

    GDI allows multiple concurrent BitBlt calls on the same monitor without
    any session-limit errors (unlike DXGI), so running this alongside the
    30-fps recorder causes no conflicts.
    """

    def __init__(
        self,
        monitors: list[MonitorInfo],
        on_frame_ready: Callable[[int, bytes], None],
        fps: int = 2,
        preview_width: int = 1280,
    ) -> None:
        self._monitors       = list(monitors)
        self._on_frame_ready = on_frame_ready
        self._fps            = fps
        self._preview_width  = preview_width

        self._stop_event = threading.Event()
        self._procs: dict[int, subprocess.Popen] = {}   # monitor_idx → process
        self._threads: list[threading.Thread]     = []

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        self._stop_event.clear()
        for m in self._monitors:
            self._launch(m)
        logger.info(
            "LivePreviewService started — {} monitor(s) at {} fps, preview width={}px.",
            len(self._monitors), self._fps, self._preview_width,
        )

    def stop(self) -> None:
        self._stop_event.set()
        for proc in self._procs.values():
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._procs.clear()
        for t in self._threads:
            t.join(timeout=3)
        self._threads.clear()
        logger.info("LivePreviewService stopped.")

    def update_monitors(self, monitors: list[MonitorInfo]) -> None:
        """Replace the active monitor list (e.g. when selection changes)."""
        old_idxs = set(self._procs.keys())
        new_idxs = {m.index for m in monitors}

        # Stop removed monitors
        for idx in old_idxs - new_idxs:
            proc = self._procs.pop(idx, None)
            if proc:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    pass
            logger.debug("LivePreview: stopped capture for monitor idx={}.", idx)

        # Start new monitors
        self._monitors = list(monitors)
        for m in monitors:
            if m.index not in self._procs:
                self._launch(m)

    # ── Internal ──────────────────────────────────────────────────────

    def _launch(self, monitor: MonitorInfo) -> None:
        """Spawn one FFmpeg MJPEG process for ``monitor`` and start reader thread."""
        cmd = [
            resolve_ffmpeg(),
            "-y",
            "-f",         "gdigrab",
            "-framerate", str(self._fps),
            "-offset_x",  str(monitor.x),
            "-offset_y",  str(monitor.y),
            "-video_size", f"{monitor.width}x{monitor.height}",
            "-draw_mouse", "0",   # exclude cursor — avoids per-frame blink artifacts
            "-i",          "desktop",
            # Scale to preview width, preserve aspect ratio (round to even)
            "-vf",         f"scale={self._preview_width}:-2",
            "-q:v",        "2",        # high-quality JPEG (1=best, 31=worst)
            "-f",          "mjpeg",
            "pipe:1",                  # output to stdout
        ]

        logger.info(
            "LivePreview: starting {}fps gdigrab for {} ({}x{} @ {},{}).",
            self._fps, monitor.display_name,
            monitor.width, monitor.height,
            monitor.x, monitor.y,
        )

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            assign_to_job(proc)
            self._procs[monitor.index] = proc

            t = threading.Thread(
                target=self._reader_loop,
                args=(monitor.index, proc),
                daemon=True,
                name=f"live-preview-m{monitor.index}",
            )
            t.start()
            self._threads.append(t)
        except Exception:
            logger.exception("LivePreview: failed to launch FFmpeg for {}.", monitor.display_name)

    def _reader_loop(self, monitor_idx: int, proc: subprocess.Popen) -> None:
        """Read MJPEG stream from FFmpeg stdout, parse JPEG frames, fire callback."""
        buf = b""
        try:
            while not self._stop_event.is_set():
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                buf += chunk

                # Extract all complete JPEG frames from the buffer
                while True:
                    soi = buf.find(_SOI)
                    if soi == -1:
                        buf = b""
                        break
                    eoi = buf.find(_EOI, soi + 2)
                    if eoi == -1:
                        buf = buf[soi:]   # keep partial frame
                        break
                    jpeg = buf[soi: eoi + 2]
                    buf  = buf[eoi + 2:]
                    try:
                        self._on_frame_ready(monitor_idx, jpeg)
                    except Exception:
                        logger.exception("LivePreview: on_frame_ready raised.")
        except Exception:
            if not self._stop_event.is_set():
                logger.exception("LivePreview: reader loop crashed for monitor idx={}.", monitor_idx)
        finally:
            logger.debug("LivePreview: reader thread exiting for monitor idx={}.", monitor_idx)
