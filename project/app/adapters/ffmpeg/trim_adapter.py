from __future__ import annotations

import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger

from app.adapters.ffmpeg.encoder_selector import (
    codec_tag,
    effective_codec,
    get_encoder,
    quality_flags,
    tag_for_encoder,
)
from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.core.ports.clip_port import ClipPort
from app.core.recording_service.models import MonitorInfo, Segment


def _is_hevc(encoder: str) -> bool:
    return "hevc" in encoder or encoder == "libx265"

# QSV has a hard resolution cap (~4096 px wide) which is easily exceeded when
# stacking monitors side-by-side (e.g. 3 × 1920 = 5760 px).  For composite
# builds we skip QSV and fall back to NVENC or libx264.
_QSV_MAX_WIDTH = 4096


class FFmpegTrimAdapter(ClipPort):
    """
    Assembles clips using FFmpeg.

    Single monitor  → concat demuxer with -c copy (stream copy, no re-encode).
                      Per FFmpeg Skill Guide §7: extremely fast, minimal CPU.
    Multiple monitors → per-monitor concat inputs piped through hstack/xstack
                       filter (requires re-encode; runs in background thread).

    Clip building never touches the ongoing segment files being written by the
    recorder watchdog.  Segments are read-only; no interference with recording.
    """

    def __init__(self, codec: str = "h264") -> None:
        self._codec = codec

    def build_clip(
        self,
        monitor_segments: Dict[MonitorInfo, List[Segment]],
        output_path: Path,
        clip_start: Optional[datetime] = None,
        clip_end: Optional[datetime] = None,
    ) -> Path:
        if not monitor_segments:
            raise ValueError("Cannot build clip: no segments provided.")

        monitors = list(monitor_segments.keys())

        if len(monitors) == 1:
            return self._build_single(
                monitor_segments[monitors[0]], output_path, clip_start, clip_end
            )
        return self._build_composite(
            monitor_segments, output_path, clip_start, clip_end
        )

    # ------------------------------------------------------------------
    # Single monitor: fast stream copy
    # ------------------------------------------------------------------

    def _build_single(
        self,
        segments: List[Segment],
        output_path: Path,
        clip_start: Optional[datetime] = None,
        clip_end: Optional[datetime] = None,
    ) -> Path:
        concat_path = self._write_concat_file(segments, clip_start, clip_end)
        try:
            cmd = [
                resolve_ffmpeg(),
                # +genpts: regenerate PTS from DTS when TS frames have missing/invalid PTS
                "-fflags", "+genpts",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_path),
                "-c", "copy",
                # HEVC copied from MPEG-TS into MP4 needs the hvc1 tag.
                # effective_codec() reflects any encoder fallback (HEVC→H.264).
                *codec_tag(effective_codec(self._codec)),
                # Hardware encoders (NVENC/QSV) emit negative DTS on the first
                # frame of each segment.  MPEG-TS allows this; MP4 does not.
                # make_zero shifts all timestamps so the minimum DTS is 0.
                "-avoid_negative_ts", "make_zero",
                "-movflags", "+faststart",
                "-y",
                str(output_path),
            ]
            self._run(cmd, output_path)
        finally:
            concat_path.unlink(missing_ok=True)
        self._log_clip(output_path)
        return output_path

    # ------------------------------------------------------------------
    # Multi-monitor: per-monitor concat inputs + hstack/xstack filter
    # ------------------------------------------------------------------

    def _build_composite(
        self,
        monitor_segments: Dict[MonitorInfo, List[Segment]],
        output_path: Path,
        clip_start: Optional[datetime] = None,
        clip_end: Optional[datetime] = None,
    ) -> Path:
        monitors = list(monitor_segments.keys())
        n = len(monitors)
        concat_files: List[Path] = []
        try:
            for m in monitors:
                cf = self._write_concat_file(monitor_segments[m], clip_start, clip_end)
                concat_files.append(cf)

            # Build FFmpeg inputs: one -f concat per monitor
            inputs: List[str] = []
            for cf in concat_files:
                inputs += ["-f", "concat", "-safe", "0", "-i", str(cf)]

            # Normalise SAR so hstack doesn't complain about mismatched ratios
            per_stream = ";".join(
                f"[{i}:v]scale=iw:ih,setsar=1[v{i}]" for i in range(n)
            )
            input_refs = "".join(f"[v{i}]" for i in range(n))

            encoder, encoder_flags = self._composite_encoder(monitors)
            q_flags = quality_flags(encoder, 23)

            if n == 4:
                # 2×2 grid in export order: top-left, top-right, bottom-left, bottom-right
                filter_complex = (
                    f"{per_stream};"
                    f"[v0][v1][v2][v3]xstack=inputs=4:"
                    f"layout=0_0|w0_0|0_h0|w0_h0[out]"
                )
            elif n == 3:
                # L-layout: monitor 0 full-height on the left,
                # monitors 1 and 2 stacked on the right at half height.
                filter_complex = self._l_layout_filter(monitors)
            else:
                filter_complex = f"{per_stream};{input_refs}hstack=inputs={n}[out]"

            cmd = [
                resolve_ffmpeg(),
                # Regenerate PTS — individual concat inputs may start at 0
                "-fflags", "+genpts",
                *inputs,
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-c:v", encoder, *encoder_flags, *q_flags,
                # Declare pixel format explicitly; software filters (hstack/scale)
                # output planar YUV which hardware encoders may reject without this.
                "-pix_fmt", "yuv420p",
                *tag_for_encoder(encoder),
                "-movflags", "+faststart",
                "-y",
                str(output_path),
            ]
            self._run(cmd, output_path)
        finally:
            for cf in concat_files:
                cf.unlink(missing_ok=True)

        self._log_clip(output_path)
        return output_path

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _composite_encoder(
        self, monitors: List[MonitorInfo]
    ) -> tuple[str, list[str]]:
        """Choose encoder for a composite clip.

        Computes the actual output width based on the layout so QSV is only
        skipped when the composite truly exceeds its hardware cap (~4096 px).
        For the 3-monitor L-layout the output is ~2880 px, well within QSV
        limits; for 5+ hstack it can exceed them.
        """
        n = len(monitors)
        if n == 3:
            # L-layout: left monitor + scaled right column
            h_each = monitors[0].height // 2
            right_w = max(
                max(2, (monitors[1].width * h_each // monitors[1].height) & ~1),
                max(2, (monitors[2].width * h_each // monitors[2].height) & ~1),
            )
            output_width = monitors[0].width + right_w
        elif n == 4:
            # 2×2 grid: two columns of one monitor width each
            output_width = max(m.width for m in monitors) * 2
        else:
            output_width = sum(m.width for m in monitors)

        encoder, flags = get_encoder(self._codec, realtime=False)
        if encoder.endswith("_qsv") and output_width > _QSV_MAX_WIDTH:
            # QSV can't handle this width — fall back to the matching software
            # encoder so we still honour the requested codec.
            sw = "libx265" if _is_hevc(encoder) else "libx264"
            logger.warning(
                "Composite width {}px exceeds QSV limit ({}px) — "
                "falling back to {} for clip assembly.",
                output_width,
                _QSV_MAX_WIDTH,
                sw,
            )
            return sw, ["-preset", "fast"]
        return encoder, flags

    def _l_layout_filter(self, monitors: List[MonitorInfo]) -> str:
        """Build a filter_complex string for 3-monitor L-layout.

        Layout::

            [ Monitor 0 (full height) ] [ Monitor 1 (half height) ]
                                        [ Monitor 2 (half height) ]

        All right-column monitors are scaled to the same width so they align.
        Output dimensions: (w0 + right_w) × h0.
        """
        m0, m1, m2 = monitors[0], monitors[1], monitors[2]
        h0, w0 = m0.height, m0.width
        h_each = h0 // 2
        # Preserve aspect ratio for right-side monitors; align to even pixel width.
        w1 = max(2, (m1.width * h_each // m1.height) & ~1)
        w2 = max(2, (m2.width * h_each // m2.height) & ~1)
        right_w = max(w1, w2)  # same column width so the two tiles align
        return (
            f"[0:v]scale={w0}:{h0},setsar=1[v0];"
            f"[1:v]scale={right_w}:{h_each},setsar=1[v1];"
            f"[2:v]scale={right_w}:{h_each},setsar=1[v2];"
            f"[v0][v1][v2]xstack=inputs=3:"
            f"layout=0_0|{w0}_0|{w0}_{h_each}[out]"
        )

    def _write_concat_file(
        self,
        segments: List[Segment],
        clip_start: Optional[datetime] = None,
        clip_end: Optional[datetime] = None,
    ) -> Path:
        """Write a temporary FFmpeg concat demuxer input file.

        Segments stored as MPEG-TS (.ts) are crash-safe — they have no moov
        atom requirement so even truncated files concatenate cleanly.

        When clip_start / clip_end are provided, ``inpoint`` and ``outpoint``
        directives are written for each segment so FFmpeg reads only the
        relevant slice.  This is the efficient path for large (e.g. 1-hour)
        files: no intermediate trimming, no re-encode, minimal I/O.

        Missing files are skipped defensively.
        """
        fd, path_str = tempfile.mkstemp(suffix=".txt", prefix="watcher_concat_")
        concat_path = Path(path_str)
        included = 0

        with open(fd, mode="w", encoding="utf-8") as f:
            for seg in segments:
                if not seg.path.exists():
                    logger.warning("Skipping missing segment: {}", seg.path.name)
                    continue

                # FFmpeg concat demuxer requires forward slashes on Windows too.
                safe_path = str(seg.path.resolve()).replace("\\", "/")
                # Escape single quotes inside the path (defensive).
                safe_path = safe_path.replace("'", r"'\''")
                f.write(f"file '{safe_path}'\n")

                if clip_start is not None and clip_end is not None:
                    seg_duration = seg.duration_seconds
                    inpoint  = (clip_start - seg.started_at).total_seconds()
                    outpoint = (clip_end   - seg.started_at).total_seconds()

                    # Clamp to segment bounds.
                    inpoint  = max(0.0, inpoint)
                    outpoint = min(seg_duration, outpoint)

                    # Only emit directives that actually constrain the window.
                    # A small epsilon (0.1 s) avoids writing trivial constraints.
                    if inpoint > 0.1:
                        f.write(f"inpoint {inpoint:.3f}\n")
                    if outpoint < seg_duration - 0.1:
                        f.write(f"outpoint {outpoint:.3f}\n")

                included += 1

        if included == 0:
            concat_path.unlink(missing_ok=True)
            raise ValueError("No valid segments available — all files missing.")

        logger.debug(
            "Concat file written: {} ({}/{} segments, window={} → {})",
            concat_path.name,
            included,
            len(segments),
            clip_start.isoformat() if clip_start else "start",
            clip_end.isoformat()   if clip_end   else "end",
        )
        return concat_path

    def _run(self, cmd: List[str], output_path: Path) -> None:
        logger.info("FFmpeg clip: {} → {}", cmd[-2] if len(cmd) > 1 else "?", output_path.name)
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=900,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            logger.error(
                "FFmpeg clip failed (rc={}):\n{}", result.returncode, stderr
            )
            # Delete the corrupt/empty file FFmpeg left behind so it does
            # not mislead the user or block future retries.
            if output_path.exists() and output_path.stat().st_size == 0:
                output_path.unlink(missing_ok=True)
                logger.debug("Removed empty output file: {}", output_path.name)
            raise RuntimeError(
                f"FFmpeg clip failed with return code {result.returncode}"
            )

    def _log_clip(self, output_path: Path) -> None:
        size_mb = output_path.stat().st_size / 1_000_000
        logger.info("Clip ready: {} ({:.1f} MB)", output_path.name, size_mb)
