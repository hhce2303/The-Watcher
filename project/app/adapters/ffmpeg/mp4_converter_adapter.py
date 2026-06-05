from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Optional

from loguru import logger

from app.adapters.ffmpeg.encoder_selector import get_encoder, quality_flags, tag_for_encoder
from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg
from app.core.ports.mp4_converter_port import Mp4ConverterPort


class FFmpegMp4ConverterAdapter(Mp4ConverterPort):
    """Re-encodes any media file into a clean H.264/AAC MP4.

    Encoder priority (inherited from :func:`get_encoder`):
    h264_nvenc → h264_qsv → libx264.

    The conversion runs in-process (blocking).  Callers that need a
    non-blocking conversion should call this from a QThread or ThreadPool.
    """

    def __init__(self, codec: str = "h264") -> None:
        self._codec = codec

    def convert(
        self,
        source: Path,
        output: Optional[Path] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> Path:
        if not source.exists():
            raise FileNotFoundError(f"Source not found: {source}")

        if output is None:
            output = source.with_stem(source.stem + "_converted").with_suffix(".mp4")

        output.parent.mkdir(parents=True, exist_ok=True)

        encoder, encoder_flags = get_encoder(self._codec, realtime=False)

        cmd = [
            resolve_ffmpeg(),
            "-i", str(source),
            "-c:v", encoder, *encoder_flags, *quality_flags(encoder, 23),
            "-c:a", "aac", "-b:a", "128k",
            "-pix_fmt", "yuv420p",
            *tag_for_encoder(encoder),
            "-movflags", "+faststart",
            "-progress", "pipe:2",   # write progress stats to stderr
            "-y",
            str(output),
        ]

        logger.info("Mp4Converter: {} → {} ({})", source.name, output.name, encoder)

        # Probe duration for progress calculation
        duration_s = self._probe_duration(source)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

        # Read stderr in a background thread so the pipe never blocks FFmpeg
        stderr_lines: list[str] = []

        def _read_stderr() -> None:
            assert process.stderr is not None
            for raw in process.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip()
                stderr_lines.append(line)
                if on_progress and duration_s > 0:
                    self._parse_progress(line, duration_s, on_progress)

        reader = threading.Thread(target=_read_stderr, daemon=True)
        reader.start()

        rc = process.wait(timeout=3600)
        reader.join(timeout=5)

        if rc != 0:
            stderr_tail = "\n".join(stderr_lines[-20:])
            output.unlink(missing_ok=True)
            raise RuntimeError(
                f"FFmpeg conversion failed (rc={rc}):\n{stderr_tail}"
            )

        if not output.exists() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg conversion produced an empty output file.")

        logger.info(
            "Mp4Converter: done → {} ({:.1f} MB)",
            output.name,
            output.stat().st_size / 1_048_576,
        )
        return output

    # ── private helpers ───────────────────────────────────────────────

    @staticmethod
    def _probe_duration(path: Path) -> float:
        """Quick ffprobe call to get clip duration for progress reporting."""
        from app.adapters.ffmpeg.ffmpeg_path import resolve_ffprobe  # local import avoids circular
        import json as _json

        try:
            result = subprocess.run(
                [
                    resolve_ffprobe(),
                    "-v", "quiet",
                    "-print_format", "json",
                    "-show_entries", "format=duration",
                    str(path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            data = _json.loads(result.stdout)
            return float(data.get("format", {}).get("duration", 0) or 0)
        except Exception:  # noqa: BLE001
            return 0.0

    @staticmethod
    def _parse_progress(
        line: str,
        duration_s: float,
        on_progress: Callable[[float], None],
    ) -> None:
        """Parse ``out_time_ms=NNN`` lines emitted by ``-progress pipe:2``."""
        m = re.match(r"out_time_ms=(\d+)", line)
        if m:
            elapsed_s = int(m.group(1)) / 1_000_000
            on_progress(min(elapsed_s / duration_s, 1.0))
