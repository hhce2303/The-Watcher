from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

from loguru import logger

from app.adapters.ffmpeg.encoder_selector import get_encoder, quality_flags, tag_for_encoder
from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.core.ports.timestamp_port import TimestampPort

# Windows font paths tried in priority order.
# An explicit fontfile is required on Windows because FFmpeg builds
# for that platform are typically compiled without fontconfig support.
_FONT_CANDIDATES = [
    r"C:/Windows/Fonts/consola.ttf",   # Consolas — monospaced, very readable
    r"C:/Windows/Fonts/cour.ttf",      # Courier New — always present
    r"C:/Windows/Fonts/arial.ttf",     # Arial — always present
]


def _find_font() -> str | None:
    """Return the first available font path, or None if none are found."""
    return next((p for p in _FONT_CANDIDATES if os.path.isfile(p)), None)


class FFmpegTimestampAdapter(TimestampPort):
    """
    Burns a wall-clock datetime overlay into the final MP4 clip.

    Strategy
    --------
    The drawtext filter uses ``%{pts\\:localtime\\:EPOCH}`` which instructs
    FFmpeg to compute the wall-clock time for every frame as::

        localtime(EPOCH + PTS_in_seconds)

    where EPOCH is the Unix timestamp of the first frame of the clip.
    This produces the correct recording time for every frame rather than
    the time at which the clip was assembled.

    The adapter re-encodes the clip (required by drawtext) using the best
    available hardware encoder (NVENC → QSV → libx264).  The source clip is
    replaced atomically via a temp file.

    Appearance
    ----------
    - Font: 64 pt white, semi-transparent black background box
    - Position: top-left corner (x=16, y=16)
    - Format: ``YYYY-MM-DD HH:MM:SS``
    """

    def __init__(self, fontsize: int = 28, codec: str = "h264") -> None:
        self._fontsize = fontsize
        self._codec = codec

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def build_drawtext(self, clip_start: datetime) -> str | None:
        """Return the ``drawtext`` filter string for a wall-clock overlay.

        Returns ``None`` when no usable font is found.  Exposed so callers that
        already re-encode a clip (e.g. the combined-grid builder) can fold the
        overlay into their own ``filter_complex`` and avoid a second full
        transcode pass.
        """
        font = _find_font()
        if font is None:
            logger.warning(
                "FFmpegTimestampAdapter: no font file found in {}. "
                "Timestamp overlay skipped.",
                _FONT_CANDIDATES,
            )
            return None

        # basetime for expansion=strftime is in microseconds.
        # Using .timestamp() gives the UTC-based Unix epoch in seconds.
        basetime = int(clip_start.timestamp() * 1_000_000)

        # Escape drive-letter colon for FFmpeg filter syntax (C: → C\:)
        escaped_font = font.replace(":", r"\:")

        # Use expansion=strftime + basetime so every frame shows the correct
        # wall-clock time without the %{pts:localtime:...} expression, which
        # triggers a filter-graph parse error when the format string contains
        # plain colons (e.g. %I:%M:%S).  With strftime expansion, colons in
        # the format are safely escaped as \: for the drawtext option parser.
        return (
            f"drawtext=fontfile='{escaped_font}':"
            "expansion=strftime:"
            f"basetime={basetime}:"
            r"text='%d %b %Y %I\:%M\:%S %p':"
            f"fontsize={self._fontsize}:"
            "fontcolor=white:"
            "box=1:"
            "boxcolor=black@0.55:"
            "boxborderw=6:"
            "x=w-tw-16:y=h-th-16"
        )

    # ------------------------------------------------------------------
    # TimestampPort interface
    # ------------------------------------------------------------------

    def burn(self, clip_path: Path, clip_start: datetime) -> Path:
        """Overwrite *clip_path* with a version that has a timestamp overlay."""
        drawtext = self.build_drawtext(clip_start)
        if drawtext is None:
            return clip_path

        tmp_path = clip_path.parent / (clip_path.stem + "_tmp.mp4")
        try:
            cmd = self._build_cmd(clip_path, drawtext, tmp_path)
            logger.info(
                "FFmpegTimestampAdapter: burning overlay → {}",
                clip_path.name,
            )
            logger.debug(
                "FFmpegTimestampAdapter cmd: {}",
                " ".join(cmd),
            )
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=900,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            stderr_text = result.stderr.decode("utf-8", errors="replace")
            if result.returncode != 0:
                logger.error(
                    "FFmpegTimestampAdapter: FFmpeg failed (rc={}):\n{}",
                    result.returncode,
                    stderr_text,
                )
                tmp_path.unlink(missing_ok=True)
                return clip_path  # return original on failure

            # Log any warnings even on success so drawtext issues are visible.
            for line in stderr_text.splitlines():
                if "drawtext" in line.lower() or "font" in line.lower() or "pts" in line.lower():
                    logger.debug("FFmpegTimestampAdapter ffmpeg: {}", line.strip())

            # Guard: never replace a good clip with an empty output.
            if not tmp_path.exists() or tmp_path.stat().st_size == 0:
                logger.error(
                    "FFmpegTimestampAdapter: output is empty, keeping original clip."
                )
                tmp_path.unlink(missing_ok=True)
                return clip_path

            # Atomic replace: swap tmp → final
            tmp_path.replace(clip_path)
            logger.info(
                "FFmpegTimestampAdapter: overlay applied → {}",
                clip_path.name,
            )
        except Exception:  # noqa: BLE001
            logger.exception("FFmpegTimestampAdapter: unexpected error.")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

        return clip_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_cmd(
        self, input_path: Path, drawtext: str, output_path: Path
    ) -> list[str]:
        # Offline re-encode → quality preset for best compression.
        encoder, encoder_flags = get_encoder(self._codec, realtime=False)

        return [
            resolve_ffmpeg(),
            # Regenerate PTS from DTS — the assembled clip may have
            # timestamps starting at 0 after make_zero normalization.
            "-fflags", "+genpts",
            "-i", str(input_path),
            "-vf", drawtext,
            "-c:v", encoder, *encoder_flags, *quality_flags(encoder, 27),
            # drawtext is a software filter; tell FFmpeg the output pixel
            # format explicitly so NVENC/QSV receive a known format.
            "-pix_fmt", "yuv420p",
            *tag_for_encoder(encoder),
            "-movflags", "+faststart",
            "-y",
            str(output_path),
        ]
