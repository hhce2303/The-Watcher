from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# In a frozen build, also try loading .env from next to the executable
if getattr(sys, "frozen", False):
    _exe_env = Path(sys.executable).parent / ".env"
    if _exe_env.exists():
        load_dotenv(_exe_env, override=False)


def _base_dir() -> Path:
    """Return the base directory for relative data paths.

    - Frozen (PyInstaller): directory that contains the .exe
    - Development: current working directory
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


_BASE = _base_dir()


def _resolve_dir(env_key: str, default: str) -> Path:
    """Return an absolute Path.  Absolute env values are used as-is;
    relative values are resolved against the base data directory."""
    raw = os.getenv(env_key, default)
    p = Path(raw)
    return p if p.is_absolute() else _BASE / raw


class Settings:
    """
    Application configuration loaded from environment variables / .env file.

    All fields have safe defaults so the app runs without a .env file present.
    Copy .env.example to .env and override values as needed.
    """

    # Directories — defaults use a local (non-OneDrive) path so that Windows
    # Defender / OneDrive sync never holds locks on segment files.
    # Override via SEGMENT_DIR / CLIPS_DIR in .env (absolute or relative paths).
    segment_dir:    Path = _resolve_dir("SEGMENT_DIR",     r"C:\WatcherData\segments")
    clips_dir:      Path = _resolve_dir("CLIPS_DIR",       r"C:\WatcherData\clips")
    raw_clips_dir:  Path = _resolve_dir("RAW_CLIPS_DIR",   r"C:\WatcherData\clips_raw")

    # Continuous recording: hours of recordings to retain on disk.
    # Default: 8 hours.  Override via RETENTION_HOURS env var.
    retention_hours: int = int(os.getenv("RETENTION_HOURS", "8"))

    # Segment length in seconds.  Default: 300 (5-minute files) — short enough
    # that archived recordings appear in clips/ within minutes of recording.
    # Override via SEGMENT_DURATION env var.
    segment_duration: int = int(os.getenv("SEGMENT_DURATION", "300"))

    # FFmpeg capture settings
    capture_source: str = os.getenv("CAPTURE_SOURCE", "desktop")
    capture_framerate: int = int(os.getenv("CAPTURE_FRAMERATE", "30"))
    output_width: int = int(os.getenv("OUTPUT_WIDTH", "1920"))
    output_height: int = int(os.getenv("OUTPUT_HEIGHT", "1080"))

    # H.264 quality (0 = lossless, 51 = worst). 28 balances size and quality.
    crf: int = int(os.getenv("CRF", "28"))

    # ── Codec ────────────────────────────────────────────────────────────────
    # VIDEO_CODEC — "hevc" (H.265, ~40-50% smaller at equal quality) or "h264"
    #   (universally playable).  Applies to the live recorder AND to offline
    #   clip assembly.  If no HEVC hardware/software encoder is available the
    #   encoder selector falls back to H.264 automatically.
    #   In-app playback (Qt FFmpeg backend) supports HEVC; external players may
    #   need the Windows "HEVC Video Extensions".  Set to "h264" for fleets
    #   without HEVC support.
    video_codec: str = os.getenv("VIDEO_CODEC", "hevc").lower()

    # ── Combined multi-monitor grid ───────────────────────────────────────────
    # The combined clip lays every monitor into one grid for review.  It is
    # re-encoded (the per-monitor raw clips stay at full OUTPUT_WIDTH/HEIGHT),
    # so its resolution directly drives file size.  A 1280×720 cell keeps a
    # 2×2 grid at 2560×1440 — sharp enough to review, far smaller than 4K.
    combined_cell_width:  int = int(os.getenv("COMBINED_CELL_WIDTH",  "1280"))
    combined_cell_height: int = int(os.getenv("COMBINED_CELL_HEIGHT", "720"))
    # Constant-quality target for the combined-grid re-encode (CRF / -cq /
    # -global_quality depending on the encoder).  Higher = smaller.
    combined_quality: int = int(os.getenv("COMBINED_QUALITY", "27"))

    # Reliability — Milestone 6
    # Max consecutive FFmpeg crash-restarts before giving up
    max_recorder_restarts: int = int(os.getenv("MAX_RECORDER_RESTARTS", "10"))
    # Disk free thresholds in bytes (default: warn=2GB, stop=512MB)
    disk_warn_bytes: int = int(os.getenv("DISK_WARN_BYTES", str(2 * 1024 ** 3)))
    disk_stop_bytes: int = int(os.getenv("DISK_STOP_BYTES", str(512 * 1024 ** 2)))

    # Event / clip timing (all in seconds)
    # How long after pressing the button to wait before assembling the clip
    # (captures post-event footage).  Override via EVENT_POST_SECONDS.
    event_post_seconds: int = int(os.getenv("EVENT_POST_SECONDS", "120"))
    # How many seconds of pre-event footage to include in the clip.
    event_pre_seconds: int = int(os.getenv("EVENT_PRE_SECONDS", "120"))
    # Minimum time between two accepted events (prevents double-clicks).
    event_cooldown_seconds: int = int(os.getenv("EVENT_COOLDOWN_SECONDS", "30"))
    # Delay between retry attempts when a clip build fails.
    clip_retry_delay_seconds: int = int(os.getenv("CLIP_RETRY_DELAY_SECONDS", "30"))

    # ── Continuous-recording clip window ─────────────────────────────────────
    # CLIP_WINDOW_MINUTES — close the current rolling clip and start a new one
    #   after this many minutes, regardless of size.  Must be divisible into 60.
    #   Default: 60 (one clip per hour per monitor).
    #   For testing: set to 1 or 2 to see clips created quickly.
    clip_window_minutes: int = int(os.getenv("CLIP_WINDOW_MINUTES", "60"))

    # CLIP_MAX_SIZE_MB — also close the clip if it would exceed this size.
    #   When a segment would push the window over the limit a new window opens.
    #   Default: 3072 MB (3 GB).  Set to a small value (e.g. 50) for testing.
    clip_max_size_mb: int = int(os.getenv("CLIP_MAX_SIZE_MB", "3072"))

    # ── Network share credentials (NAS / UNC paths) ───────────────────────────
    # Used by the ClipBrowser to authenticate \\server\ paths with net use.
    # Store here — never commit a .env with real passwords.
    nas_username: str = os.getenv("NAS_USERNAME", "")
    nas_password: str = os.getenv("NAS_PASSWORD", "")

    # ── Role system ───────────────────────────────────────────────────────────
    # IT_PIN — required to unlock role-change UI on Operator/Supervisor PCs.
    # Set to a strong PIN per deployment; default "1234" is for first-time setup.
    it_pin: str = os.getenv("IT_PIN", "1234")

    # ── Supervisor / IT request system ───────────────────────────────────────
    # SLC-Storage UNC host where operator footage is stored.
    slc_storage_host: str = os.getenv("SLC_STORAGE_HOST", r"\\SIG-SLC-Storage")
    # WebSocket port the IT PC listens on for incoming clip requests.
    it_ws_port: int = int(os.getenv("IT_WS_PORT", "9090"))

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
