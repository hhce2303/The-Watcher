"""
Tests for encoder_selector (Milestone 7 — Performance Optimization).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


class TestEncoderSelector:
    def setup_method(self):
        # Reset the per-codec probe cache and driver preference before each test
        import app.adapters.ffmpeg.encoder_selector as sel
        sel._selected_names.clear()
        sel._preferred_driver = "auto"

    def _patch_probe(self, results: dict):
        """
        Patch _probe_encoder to return values from results dict.
        Keys are encoder names; values are bool.
        """
        import app.adapters.ffmpeg.encoder_selector as sel

        def _fake_probe(ffmpeg, encoder):
            return results.get(encoder, False)

        return patch.object(sel, "_probe_encoder", side_effect=_fake_probe)

    # ── H.264 selection ───────────────────────────────────────────────

    def test_selects_nvenc_when_available(self):
        with self._patch_probe({"h264_nvenc": True}):
            from app.adapters.ffmpeg.encoder_selector import get_encoder
            name, flags = get_encoder("h264")
        assert name == "h264_nvenc"

    def test_falls_back_to_qsv_when_nvenc_unavailable(self):
        with self._patch_probe({"h264_nvenc": False, "h264_qsv": True}):
            from app.adapters.ffmpeg.encoder_selector import get_encoder
            name, flags = get_encoder("h264")
        assert name == "h264_qsv"

    def test_falls_back_to_libx264_when_hw_unavailable(self):
        with self._patch_probe({"h264_nvenc": False, "h264_qsv": False, "libx264": True}):
            from app.adapters.ffmpeg.encoder_selector import get_encoder
            name, flags = get_encoder("h264")
        assert name == "libx264"

    # ── HEVC selection + fallback ──────────────────────────────────────

    def test_selects_hevc_qsv_when_available(self):
        with self._patch_probe({"hevc_qsv": True}):
            from app.adapters.ffmpeg.encoder_selector import get_encoder
            name, flags = get_encoder("hevc")
        assert name == "hevc_qsv"

    def test_hevc_falls_back_to_h264_when_no_hevc_encoder(self):
        # No HEVC encoder works, but libx264 (H.264) does → graceful fallback.
        with self._patch_probe(
            {"hevc_nvenc": False, "hevc_qsv": False, "libx265": False, "libx264": True}
        ):
            from app.adapters.ffmpeg.encoder_selector import get_encoder
            name, flags = get_encoder("hevc")
        assert name == "libx264"

    # ── Caching ────────────────────────────────────────────────────────

    def test_result_is_cached(self):
        import app.adapters.ffmpeg.encoder_selector as sel
        probe_calls = []

        def _counting_probe(ffmpeg, encoder):
            probe_calls.append(encoder)
            return encoder == "libx264"

        with patch.object(sel, "_probe_encoder", side_effect=_counting_probe):
            sel.get_encoder("h264")
            sel.get_encoder("h264")
            sel.get_encoder("h264")
        # probe should only be called once per encoder, not on cached calls
        assert probe_calls.count("libx264") == 1

    # ── Preset selection (realtime vs offline) ─────────────────────────

    def test_realtime_libx264_uses_ultrafast(self):
        with self._patch_probe({"h264_nvenc": False, "h264_qsv": False, "libx264": True}):
            from app.adapters.ffmpeg.encoder_selector import get_encoder
            name, flags = get_encoder("h264", realtime=True)
        assert "ultrafast" in flags

    def test_offline_libx264_uses_quality_preset(self):
        with self._patch_probe({"h264_nvenc": False, "h264_qsv": False, "libx264": True}):
            from app.adapters.ffmpeg.encoder_selector import get_encoder
            name, flags = get_encoder("h264", realtime=False)
        assert "ultrafast" not in flags
        assert "medium" in flags

    def test_offline_qsv_uses_veryslow(self):
        with self._patch_probe({"h264_nvenc": False, "h264_qsv": True}):
            from app.adapters.ffmpeg.encoder_selector import get_encoder
            name, flags = get_encoder("h264", realtime=False)
        assert "veryslow" in flags

    # ── quality_flags / codec_tag helpers ──────────────────────────────

    def test_quality_flags_per_family(self):
        from app.adapters.ffmpeg.encoder_selector import quality_flags
        assert quality_flags("h264_nvenc", 28) == ["-cq", "28"]
        assert quality_flags("hevc_nvenc", 28) == ["-cq", "28"]
        assert quality_flags("h264_qsv", 28) == ["-global_quality", "28"]
        assert quality_flags("hevc_qsv", 28) == ["-global_quality", "28"]
        assert quality_flags("libx264", 28) == ["-crf", "28"]
        assert quality_flags("libx265", 28) == ["-crf", "28"]

    def test_codec_tag(self):
        from app.adapters.ffmpeg.encoder_selector import codec_tag
        assert codec_tag("hevc") == ["-tag:v", "hvc1"]
        assert codec_tag("h264") == []
        assert codec_tag("") == []

    def test_tag_for_encoder(self):
        from app.adapters.ffmpeg.encoder_selector import tag_for_encoder
        assert tag_for_encoder("hevc_qsv") == ["-tag:v", "hvc1"]
        assert tag_for_encoder("hevc_nvenc") == ["-tag:v", "hvc1"]
        assert tag_for_encoder("libx265") == ["-tag:v", "hvc1"]
        assert tag_for_encoder("h264_qsv") == []
        assert tag_for_encoder("libx264") == []

    # ── Driver preference ──────────────────────────────────────────────

    def test_force_nvidia_selects_nvenc(self):
        import app.adapters.ffmpeg.encoder_selector as sel
        sel.set_preferences(driver="nvidia")
        with self._patch_probe({"hevc_nvenc": True, "hevc_qsv": True}):
            name, _ = sel.get_encoder("hevc")
        assert name == "hevc_nvenc"

    def test_force_nvidia_falls_back_when_absent(self):
        # No NVIDIA hardware → forced nvidia still records on whatever works.
        import app.adapters.ffmpeg.encoder_selector as sel
        sel.set_preferences(driver="nvidia")
        with self._patch_probe({"hevc_qsv": True}):
            name, _ = sel.get_encoder("hevc")
        assert name == "hevc_qsv"

    def test_force_cpu_selects_software(self):
        import app.adapters.ffmpeg.encoder_selector as sel
        sel.set_preferences(driver="cpu")
        # Even though hardware would probe OK, CPU mode must pick software.
        with self._patch_probe({"hevc_qsv": True, "libx265": True, "libx264": True}):
            name, _ = sel.get_encoder("hevc")
        assert name == "libx265"

    def test_force_intel_amd_map(self):
        import app.adapters.ffmpeg.encoder_selector as sel
        sel.set_preferences(driver="intel")
        with self._patch_probe({"h264_qsv": True, "h264_amf": True}):
            assert sel.get_encoder("h264")[0] == "h264_qsv"
        sel.set_preferences(driver="amd")
        with self._patch_probe({"h264_qsv": True, "h264_amf": True}):
            assert sel.get_encoder("h264")[0] == "h264_amf"

    def test_set_preferences_resets_cache(self):
        import app.adapters.ffmpeg.encoder_selector as sel
        with self._patch_probe({"h264_nvenc": True, "h264_qsv": True}):
            assert sel.get_encoder("h264")[0] == "h264_nvenc"   # auto → nvenc
            sel.set_preferences(driver="intel")                 # clears cache
            assert sel.get_encoder("h264")[0] == "h264_qsv"     # now intel

    # ── effective_codec ────────────────────────────────────────────────

    def test_effective_codec_matches_when_hevc_available(self):
        import app.adapters.ffmpeg.encoder_selector as sel
        with self._patch_probe({"hevc_qsv": True}):
            assert sel.effective_codec("hevc") == "hevc"

    def test_effective_codec_reflects_h264_fallback(self):
        # HEVC requested but only H.264 hardware exists → auto falls to H.264.
        import app.adapters.ffmpeg.encoder_selector as sel
        with self._patch_probe({"h264_qsv": True}):
            assert sel.effective_codec("hevc") == "h264"

    # ── AMF flags ───────────────────────────────────────────────────────

    def test_amf_quality_and_preset_flags(self):
        from app.adapters.ffmpeg.encoder_selector import quality_flags, preset_flags
        assert quality_flags("h264_amf", 27) == ["-rc", "cqp", "-qp_i", "27", "-qp_p", "27"]
        assert preset_flags("hevc_amf", realtime=True) == ["-quality", "speed"]
        assert preset_flags("hevc_amf", realtime=False) == ["-quality", "quality"]
