"""
Tests for FFmpegRecorderAdapter's zero-copy capture pipeline (PoC 1 —
ffmpeg-pipeline-optimization-research.md §8). Everything here builds command
lists / resolves flags without invoking real FFmpeg: the ddagrab and
zero-copy probes are patched directly.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.adapters.ffmpeg.recorder_adapter import FFmpegRecorderAdapter, _encoder_family
from app.core.recording_service.models import MonitorInfo


def _monitor(index: int = 0) -> MonitorInfo:
    return MonitorInfo(name="\\\\.\\DISPLAY1", width=1920, height=1080, x=0, y=0, index=index)


def _adapter(**kwargs) -> FFmpegRecorderAdapter:
    return FFmpegRecorderAdapter(**kwargs)


@pytest.fixture(autouse=True)
def _fake_ffmpeg_path():
    with patch("app.adapters.ffmpeg.recorder_adapter.resolve_ffmpeg", return_value="ffmpeg.exe"):
        yield


class TestEncoderFamily:
    def test_qsv_family(self):
        assert _encoder_family("hevc_qsv") == "qsv"
        assert _encoder_family("h264_qsv") == "qsv"

    def test_nvenc_family(self):
        assert _encoder_family("hevc_nvenc") == "cuda"
        assert _encoder_family("h264_nvenc") == "cuda"

    def test_amf_and_cpu_have_no_family(self):
        assert _encoder_family("hevc_amf") is None
        assert _encoder_family("libx264") is None
        assert _encoder_family("libx265") is None


class TestPipelineResolution:
    def test_gdigrab_backend_is_always_legacy(self):
        adapter = _adapter(capture_backend="gdigrab", capture_pipeline="auto", codec="hevc")
        adapter.set_monitor(_monitor())
        adapter._resolved_backend = "gdigrab"
        with patch(
            "app.adapters.ffmpeg.recorder_adapter.get_encoder",
            return_value=("hevc_qsv", []),
        ):
            cmd = adapter._build_ffmpeg_command(output_dir=_dummy_dir())
        assert adapter._resolved_pipeline == "legacy"
        assert "hwmap" not in " ".join(cmd)

    def test_auto_uses_zerocopy_when_qsv_probe_succeeds(self):
        adapter = _adapter(capture_backend="ddagrab", capture_pipeline="auto", codec="hevc")
        adapter.set_monitor(_monitor())
        adapter._resolved_backend = "ddagrab"
        with patch(
            "app.adapters.ffmpeg.recorder_adapter.get_encoder",
            return_value=("hevc_qsv", ["-preset", "medium"]),
        ), patch.object(adapter, "_zerocopy_available", return_value=True):
            cmd = adapter._build_ffmpeg_command(output_dir=_dummy_dir())
        assert adapter._resolved_pipeline == "zerocopy"
        joined = " ".join(cmd)
        assert "hwmap=derive_device=qsv" in joined
        assert "vpp_qsv" in joined
        assert "-async_depth 1" in joined
        assert "hwdownload,format=bgra" not in joined.split("[recout]")[0]
        # Regression: vpp_qsv defaults to full-range ("pc") output, which
        # produced yuvj420p segments — a color-range mismatch against the
        # legacy pipeline's yuv420p (limited/tv). Verified on real QSV
        # hardware that out_range=tv restores parity.
        assert "out_range=tv" in joined

    def test_auto_falls_back_to_legacy_when_probe_fails(self):
        adapter = _adapter(capture_backend="ddagrab", capture_pipeline="auto", codec="hevc")
        adapter.set_monitor(_monitor())
        adapter._resolved_backend = "ddagrab"
        with patch(
            "app.adapters.ffmpeg.recorder_adapter.get_encoder",
            return_value=("hevc_qsv", ["-preset", "medium"]),
        ), patch.object(adapter, "_zerocopy_available", return_value=False):
            cmd = adapter._build_ffmpeg_command(output_dir=_dummy_dir())
        assert adapter._resolved_pipeline == "legacy"
        assert "hwmap" not in " ".join(cmd)

    def test_auto_skips_probe_for_amf_and_cpu_encoders(self):
        adapter = _adapter(capture_backend="ddagrab", capture_pipeline="auto", codec="hevc")
        adapter.set_monitor(_monitor())
        adapter._resolved_backend = "ddagrab"
        with patch(
            "app.adapters.ffmpeg.recorder_adapter.get_encoder",
            return_value=("hevc_amf", []),
        ), patch.object(adapter, "_zerocopy_available") as probe:
            cmd = adapter._build_ffmpeg_command(output_dir=_dummy_dir())
        probe.assert_not_called()
        assert adapter._resolved_pipeline == "legacy"

    def test_legacy_forces_legacy_even_with_qsv(self):
        adapter = _adapter(capture_backend="ddagrab", capture_pipeline="legacy", codec="hevc")
        adapter.set_monitor(_monitor())
        adapter._resolved_backend = "ddagrab"
        with patch(
            "app.adapters.ffmpeg.recorder_adapter.get_encoder",
            return_value=("hevc_qsv", []),
        ), patch.object(adapter, "_zerocopy_available") as probe:
            cmd = adapter._build_ffmpeg_command(output_dir=_dummy_dir())
        probe.assert_not_called()
        assert adapter._resolved_pipeline == "legacy"

    def test_forced_zerocopy_falls_back_cleanly_when_probe_fails(self):
        adapter = _adapter(capture_backend="ddagrab", capture_pipeline="zerocopy", codec="hevc")
        adapter.set_monitor(_monitor())
        adapter._resolved_backend = "ddagrab"
        with patch(
            "app.adapters.ffmpeg.recorder_adapter.get_encoder",
            return_value=("hevc_nvenc", []),
        ), patch.object(adapter, "_zerocopy_available", return_value=False):
            cmd = adapter._build_ffmpeg_command(output_dir=_dummy_dir())
        assert adapter._resolved_pipeline == "legacy"
        assert "hwmap" not in " ".join(cmd)

    def test_forced_zerocopy_falls_back_when_encoder_has_no_gpu_path(self):
        adapter = _adapter(capture_backend="ddagrab", capture_pipeline="zerocopy", codec="h264")
        adapter.set_monitor(_monitor())
        adapter._resolved_backend = "ddagrab"
        with patch(
            "app.adapters.ffmpeg.recorder_adapter.get_encoder",
            return_value=("libx264", []),
        ), patch.object(adapter, "_zerocopy_available") as probe:
            cmd = adapter._build_ffmpeg_command(output_dir=_dummy_dir())
        probe.assert_not_called()
        assert adapter._resolved_pipeline == "legacy"

    def test_nvenc_zerocopy_uses_cuda_scale(self):
        adapter = _adapter(capture_backend="ddagrab", capture_pipeline="auto", codec="hevc")
        adapter.set_monitor(_monitor())
        adapter._resolved_backend = "ddagrab"
        with patch(
            "app.adapters.ffmpeg.recorder_adapter.get_encoder",
            return_value=("hevc_nvenc", ["-preset", "p4"]),
        ), patch.object(adapter, "_zerocopy_available", return_value=True):
            cmd = adapter._build_ffmpeg_command(output_dir=_dummy_dir())
        joined = " ".join(cmd)
        assert "hwmap=derive_device=cuda" in joined
        assert "scale_cuda" in joined
        # async_depth tweak is QSV-only.
        assert "-async_depth 1" not in joined


class TestZeroCopyProbeCaching:
    def test_probe_result_is_cached_per_monitor_and_family(self):
        adapter = _adapter(capture_backend="ddagrab", capture_pipeline="auto", codec="hevc")
        adapter.set_monitor(_monitor())
        calls = []

        def _fake_run(*args, **kwargs):
            calls.append(args)
            raise AssertionError("subprocess.run should only be invoked once (cached)")

        # First call succeeds, cached — patch subprocess.run to fail loudly if
        # invoked a second time.
        with patch(
            "app.adapters.ffmpeg.recorder_adapter.subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            first = adapter._zerocopy_available(_monitor(), "hevc_qsv", "qsv")
            second = adapter._zerocopy_available(_monitor(), "hevc_qsv", "qsv")
        assert first is True
        assert second is True
        assert mock_run.call_count == 1


def _dummy_dir():
    from pathlib import Path
    import tempfile

    return Path(tempfile.gettempdir())
