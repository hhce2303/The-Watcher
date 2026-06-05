from __future__ import annotations

import subprocess
import threading

from loguru import logger

from app.adapters.ffmpeg.ffmpeg_path import resolve_ffmpeg

# Per-vendor encoder name for each codec.  "cpu" is the software fallback,
# always available.  Availability is independent of the preset; presets are
# chosen separately by preset_flags() (real-time vs offline), so we probe by
# name only.
#   H.264 (AVC): universally playable, the safe fallback.
#   HEVC (H.265): ~40-50% smaller at equal quality, hardware-accelerated.
_VENDORS = ("nvidia", "intel", "amd")
_VENDOR_ENCODER: dict[str, dict[str, str]] = {
    "h264": {"nvidia": "h264_nvenc", "intel": "h264_qsv", "amd": "h264_amf", "cpu": "libx264"},
    "hevc": {"nvidia": "hevc_nvenc", "intel": "hevc_qsv", "amd": "hevc_amf", "cpu": "libx265"},
}

# Module-level driver preference (set once at startup from user_config).
#   "auto"  → probe hardware in priority order (NVIDIA → Intel → AMD → CPU).
#   vendor  → try that vendor first, then fall back to the auto order so a PC is
#             never left unable to record.
#   "cpu"   → software encoder only (libx264/libx265).
_preferred_driver: str = "auto"

# codec -> selected encoder name (probe result, cached for the process lifetime)
_selected_names: dict[str, str] = {}
# Reentrant: cache resets / fallbacks re-enter while holding the lock.
_probe_lock = threading.RLock()


def set_preferences(driver: str | None = None) -> None:
    """Set the preferred hardware driver and reset the probe cache.

    Call once at startup (and whenever the user changes the encoder in the UI)
    so subsequent ``get_encoder`` calls reflect the new preference.  Live
    recording picks up the change on its next (re)start.
    """
    global _preferred_driver
    with _probe_lock:
        if driver:
            _preferred_driver = driver.lower()
        _selected_names.clear()
    logger.info("Encoder driver preference set to: {}", _preferred_driver)


def get_encoder(codec: str = "h264", realtime: bool = False) -> tuple[str, list[str]]:
    """Return ``(encoder_name, preset_flags)`` for the best encoder of ``codec``.

    Parameters
    ----------
    codec:
        ``"h264"`` (universally playable) or ``"hevc"`` (smaller files).
        Selection also honours the module driver preference (:func:`set_preferences`)
        and always falls back to a working encoder, so callers never have to
        handle the missing-encoder case.
    realtime:
        ``True`` for live screen capture (fast preset, low latency).
        ``False`` for offline clip assembly (slow preset, best compression).

    The encoder probe runs once per codec and is cached.
    """
    name = _select_name(codec)
    return name, preset_flags(name, realtime)


def effective_codec(codec: str = "h264") -> str:
    """Return the codec actually produced for ``codec`` after selection.

    May differ from the requested codec when a fallback occurs (e.g. HEVC was
    requested but only an H.264 encoder is available).  Stream-copy paths use
    this to decide whether the ``hvc1`` MP4 tag applies.
    """
    return "hevc" if _is_hevc_encoder(_select_name(codec)) else "h264"


def _is_hevc_encoder(encoder: str) -> bool:
    return encoder.startswith("hevc") or encoder == "libx265"


def _candidate_order(codec: str) -> list[str]:
    """Build the probe order for ``codec`` honouring the driver preference.

    Forcing a vendor still appends the remaining encoders as fallback so a
    machine without that vendor's hardware keeps recording (just on a different
    encoder).  In "auto" mode hardware for the *other* codec is preferred over
    software for the requested one — a fast hardware H.264 beats a frame-dropping
    software HEVC for live capture.
    """
    other = "h264" if codec == "hevc" else "hevc"
    hw_chosen = [_VENDOR_ENCODER[codec][v] for v in _VENDORS]
    hw_other  = [_VENDOR_ENCODER[other][v] for v in _VENDORS]
    sw_chosen = [_VENDOR_ENCODER[codec]["cpu"]]
    sw_other  = [_VENDOR_ENCODER[other]["cpu"]]

    if _preferred_driver == "cpu":
        return sw_chosen + sw_other

    if _preferred_driver in _VENDORS:
        first = _VENDOR_ENCODER[codec][_preferred_driver]
        first_other = _VENDOR_ENCODER[other][_preferred_driver]
        rest_chosen = [e for e in hw_chosen if e != first]
        rest_other  = [e for e in hw_other if e != first_other]
        return [first, first_other] + rest_chosen + rest_other + sw_chosen + sw_other

    # "auto"
    return hw_chosen + hw_other + sw_chosen + sw_other


def _select_name(codec: str) -> str:
    codec = (codec or "h264").lower()
    if codec not in _VENDOR_ENCODER:
        codec = "h264"

    with _probe_lock:
        cached = _selected_names.get(codec)
        if cached is not None:
            return cached

        ffmpeg = resolve_ffmpeg()
        for name in _candidate_order(codec):
            if _probe_encoder(ffmpeg, name):
                logger.info(
                    "Encoder selected ({}, driver={}): {}",
                    codec, _preferred_driver, name,
                )
                _selected_names[codec] = name
                return name

        # libx264 is always available — last-resort guarantee.
        logger.warning("No probed encoder worked for {} — using libx264.", codec)
        _selected_names[codec] = "libx264"
        return "libx264"


def preset_flags(encoder: str, realtime: bool) -> list[str]:
    """Return preset/tuning flags for an encoder.

    Real-time (live capture) favours speed and low latency so FFmpeg keeps up
    with the screen at 30 fps without dropping frames.  Offline (clip assembly)
    favours compression because it runs as a background batch job.
    """
    if encoder in ("h264_nvenc", "hevc_nvenc"):
        # NVENC presets: p1 (fastest) … p7 (slowest/best).
        return ["-preset", "p4", "-tune", "ll"] if realtime else ["-preset", "p6", "-tune", "hq"]
    if encoder in ("h264_qsv", "hevc_qsv"):
        # QSV is hardware-accelerated, so even "veryslow" stays fast offline.
        return ["-preset", "medium"] if realtime else ["-preset", "veryslow"]
    if encoder in ("h264_amf", "hevc_amf"):
        # AMF quality presets: speed / balanced / quality.
        return ["-quality", "speed"] if realtime else ["-quality", "quality"]
    # Software x264 / x265.
    if realtime:
        return ["-preset", "ultrafast", "-tune", "zerolatency"]
    return ["-preset", "medium"]


def quality_flags(encoder: str, quality: int) -> list[str]:
    """Return the constant-quality flag(s) for the given encoder family.

    Each encoder family uses a different option name for quality-based
    (variable-bitrate) encoding:
      - *_nvenc : -cq              (Constant Quality, 0=best, 51=worst)
      - *_qsv   : -global_quality  (ICQ, lower=better)
      - *_amf   : -qp_i/-qp_p      (constant QP, lower=better)
      - libx264/libx265 : -crf     (Constant Rate Factor, 0=lossless, 51=worst)
    """
    if encoder.endswith("_nvenc"):
        return ["-cq", str(quality)]
    if encoder.endswith("_qsv"):
        return ["-global_quality", str(quality)]
    if encoder.endswith("_amf"):
        return ["-rc", "cqp", "-qp_i", str(quality), "-qp_p", str(quality)]
    return ["-crf", str(quality)]


def codec_tag(codec: str) -> list[str]:
    """MP4 ``-tag:v`` flags needed for broad player compatibility.

    HEVC streams must be tagged ``hvc1`` (not the FFmpeg default ``hev1``) so
    that QuickTime / Windows Media Foundation / Safari recognise them.  Applies
    to both re-encodes and stream copies that land in an MP4 container.
    """
    return ["-tag:v", "hvc1"] if (codec or "").lower() == "hevc" else []


def tag_for_encoder(encoder: str) -> list[str]:
    """``-tag:v`` flags appropriate for the codec the encoder actually emits.

    Use in re-encode paths where the chosen encoder is known — this stays
    correct even when the requested codec fell back to a different one.
    """
    return ["-tag:v", "hvc1"] if _is_hevc_encoder(encoder) else []


def _probe_encoder(ffmpeg: str, encoder: str) -> bool:
    """Run a tiny 1-frame encode to test if the encoder works on this machine."""
    cmd = [
        ffmpeg,
        "-f", "lavfi",
        "-i", "nullsrc=s=64x64:r=1",
        "-t", "0.1",
        "-c:v", encoder,
        "-f", "null",
        "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        ok = result.returncode == 0
        logger.debug("Encoder probe {}: {}", encoder, "OK" if ok else "unavailable")
        return ok
    except Exception:  # noqa: BLE001
        logger.debug("Encoder probe {}: exception", encoder)
        return False
