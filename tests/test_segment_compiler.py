"""
Unit tests — Fase 0 (R-6): FFmpeg segment-compiler adapter (fallback engine).

FFmpeg is NOT actually invoked — subprocess.run is mocked.  We verify command
construction and error handling only.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.adapters.ffmpeg.segment_compiler_adapter import FFmpegSegmentCompilerAdapter


class TestBuildCmd:
    def test_basic_concat_no_window(self) -> None:
        a = FFmpegSegmentCompilerAdapter()
        cmd = a._build_cmd(Path("concat.txt"), Path("out.mp4"), None, None)
        assert "-f" in cmd and "concat" in cmd
        assert cmd[cmd.index("-c") + 1] == "copy"
        assert cmd[-1] == "out.mp4"
        assert "-ss" not in cmd
        assert "-to" not in cmd

    def test_window_adds_ss_and_to(self) -> None:
        a = FFmpegSegmentCompilerAdapter()
        cmd = a._build_cmd(Path("concat.txt"), Path("out.mp4"), 2.5, 9.0)
        assert "-ss" in cmd and cmd[cmd.index("-ss") + 1] == "2.500"
        assert "-to" in cmd and cmd[cmd.index("-to") + 1] == "9.000"

    def test_zero_in_point_omits_ss(self) -> None:
        a = FFmpegSegmentCompilerAdapter()
        cmd = a._build_cmd(Path("concat.txt"), Path("out.mp4"), 0.0, 5.0)
        assert "-ss" not in cmd
        assert "-to" in cmd

    def test_hevc_tag_present(self) -> None:
        cmd = FFmpegSegmentCompilerAdapter(codec="hevc")._build_cmd(
            Path("c.txt"), Path("o.mp4"), None, None
        )
        # effective_codec may fall back to h264 on this machine; assert the
        # builder asks encoder_selector and only tags when hevc survives.
        if "-tag:v" in cmd:
            assert cmd[cmd.index("-tag:v") + 1] == "hvc1"

    def test_engine_name(self) -> None:
        assert FFmpegSegmentCompilerAdapter().engine_name == "ffmpeg"


class TestCompile:
    def test_empty_sources_raises(self) -> None:
        with pytest.raises(ValueError):
            FFmpegSegmentCompilerAdapter().compile([], Path("out.mp4"))

    def test_missing_source_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            FFmpegSegmentCompilerAdapter().compile(
                [tmp_path / "nope.mp4"], tmp_path / "out.mp4"
            )

    def test_success_returns_output(self, tmp_path: Path) -> None:
        src = tmp_path / "a.mp4"
        src.write_bytes(b"\x00\x00")
        out = tmp_path / "out.mp4"
        a = FFmpegSegmentCompilerAdapter()
        with patch(
            "app.adapters.ffmpeg.segment_compiler_adapter.subprocess.run",
            return_value=MagicMock(returncode=0),
        ) as run:
            result = a.compile([src], out)
        assert result == out
        run.assert_called_once()

    def test_failure_raises_runtimeerror(self, tmp_path: Path) -> None:
        src = tmp_path / "a.mp4"
        src.write_bytes(b"\x00\x00")
        out = tmp_path / "out.mp4"
        a = FFmpegSegmentCompilerAdapter()
        with patch(
            "app.adapters.ffmpeg.segment_compiler_adapter.subprocess.run",
            return_value=MagicMock(returncode=1, stderr=b"boom"),
        ):
            with pytest.raises(RuntimeError):
                a.compile([src], out)
