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


def _resolve_file(env_key: str, default: str = "") -> str:
    """Resolve packaged trust material independently of the process CWD."""
    raw = os.getenv(env_key, default).strip()
    if not raw:
        return ""
    path = Path(raw)
    return str(path if path.is_absolute() else _BASE / path)


def _env_flag(key: str, default: bool = False) -> bool:
    """Parse an explicit boolean environment flag without truthy-string traps."""
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """
    Application configuration loaded from environment variables / .env file.

    All fields have safe defaults so the app runs without a .env file present.
    Copy .env.example to .env and override values as needed.
    """

    # Hot recording data stays local so Windows Defender / OneDrive never holds
    # locks on active files. Only final, atomically-written combined MP4s go to
    # the operator's storage share.
    segment_dir:    Path = _resolve_dir("SEGMENT_DIR",     r"C:\WatcherData\segments")
    clips_dir:      Path = _resolve_dir("CLIPS_DIR",       r"\\SIG-SLC-Storage\Storage3\Operator 29")
    raw_clips_dir:  Path = _resolve_dir("RAW_CLIPS_DIR",   r"C:\WatcherData\clips_raw")
    # Event-triggered (auto/manual) clips — kept out of clips_dir so combined
    # recordings and event highlights don't mix in the same folder. Fixed on
    # local disk like raw_clips_dir — does NOT follow a user-relocated clips_dir.
    event_clips_dir: Path = _resolve_dir("CLIPS_EVENTS_DIR", r"C:\WatcherData\clips_events")

    # Continuous recording: hours of recordings to retain on disk.
    # Default: 8 hours.  Override via RETENTION_HOURS env var.
    retention_hours: int = int(os.getenv("RETENTION_HOURS", "8"))

    # Segment length in seconds.  Default: 300 (5-minute files) — short enough
    # that archived recordings appear in clips/ within minutes of recording.
    # Override via SEGMENT_DURATION env var.
    segment_duration: int = int(os.getenv("SEGMENT_DURATION", "300"))

    # FFmpeg capture settings
    capture_source: str = os.getenv("CAPTURE_SOURCE", "desktop")
    # Screen-capture backend: "auto" (prefer ddagrab/DXGI, fall back to gdigrab),
    # "ddagrab" (force DXGI Desktop Duplication — no GDI cursor flicker), or
    # "gdigrab" (force legacy GDI BitBlt).  Default "auto".
    capture_backend: str = os.getenv("CAPTURE_BACKEND", "auto")
    # Capture filtergraph: "auto" (zero-copy on ddagrab+QSV/NVENC, else legacy),
    # "zerocopy" (force — falls back to legacy per-monitor if the GPU filter
    # chain fails to probe), or "legacy" (always hwdownload to system memory).
    # Zero-copy keeps frames on the GPU (hwmap→vpp_qsv / hwmap→CUDA) instead of
    # downloading every frame before scaling — ~66% less CPU/monitor on QSV.
    # See docs/migration/ffmpeg-pipeline-optimization-research.md §3.1.
    capture_pipeline: str = os.getenv("CAPTURE_PIPELINE", "auto")
    # CLIP_ENGINE (Track R2 M1) — "auto"/"rust": route the single-monitor clip
    # path (FFmpegTrimAdapter._build_single, byte-identical to compile_clip)
    # through the Rust watcher_segments engine when it's the active
    # segment_compiler (ENGINE_READY-gated); "ffmpeg" forces the legacy FFmpeg
    # concat/-c copy path. Any Rust exception falls back to FFmpeg in the same
    # call regardless of this setting — this only controls the first attempt.
    clip_engine: str = os.getenv("CLIP_ENGINE", "auto").lower()
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

    # Event-clip window used by ClipBuilder (seconds before/after the trigger).
    event_post_seconds: int = int(os.getenv("EVENT_POST_SECONDS", "120"))
    event_pre_seconds: int = int(os.getenv("EVENT_PRE_SECONDS", "120"))

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

    # -- Daily SIG Systems browser-local identity/session settings --
    # Only the session/identity helpers of browser_local are shipped in this repo
    # (live_view_lan reuses them). The browser-local HTTP server is out of scope
    # (ADR-0023); these fields keep the helper modules' settings contract intact.
    browser_local_enabled: bool = _env_flag("BROWSER_LOCAL_ENABLED", False)
    # Deliberately not configurable: Daily's CSP and postMessage contract pin
    # this origin. A different port would create a second, unreviewed trust
    # boundary instead of a supported deployment variant.
    browser_local_port: int = 8765
    browser_local_parent_origin: str = os.getenv(
        "BROWSER_LOCAL_PARENT_ORIGIN", "https://daily.sig.systems"
    ).rstrip("/")
    browser_local_issuer: str = os.getenv("BROWSER_LOCAL_ISSUER", "daily.sig.systems")
    browser_local_audience: str = os.getenv("BROWSER_LOCAL_AUDIENCE", "the-watcher-local")
    # Pin the signing-key id as well as its public key so an unexpected key
    # rotation cannot silently become trusted by a local daemon.
    browser_local_issuer_kid: str = os.getenv("BROWSER_LOCAL_ISSUER_KID", "")
    # A device is enrolled against exactly one Daily workstation. Zero means unconfigured
    # and fails closed when the browser adapter is enabled.
    browser_local_station_id: int = int(os.getenv("BROWSER_LOCAL_STATION_ID", "0"))
    browser_local_cert_file: str = _resolve_file("BROWSER_LOCAL_CERT_FILE")
    browser_local_key_file: str = _resolve_file("BROWSER_LOCAL_KEY_FILE")
    browser_local_issuer_public_key_file: str = _resolve_file("BROWSER_LOCAL_ISSUER_PUBLIC_KEY_FILE")
    browser_local_data_dir: Path = _resolve_dir(
        "BROWSER_LOCAL_DATA_DIR",
        os.path.join(
            os.environ.get("LOCALAPPDATA", r"C:\\Users\\Default\\AppData\\Local"),
            "The Watcher",
            "browser_local",
        ),
    )

    # ── Supervisor live view (separate authenticated LAN channel) ───────────
    # This is intentionally NOT the browser-local server above.  It remains
    # disabled until endpoint management distributes a corporate TLS cert,
    # firewall rule and Daily issuer key to an enrolled Operator.
    live_view_enabled: bool = _env_flag("LIVE_VIEW_ENABLED", False)
    live_view_bind_host: str = os.getenv("LIVE_VIEW_BIND_HOST", "0.0.0.0")
    live_view_port: int = int(os.getenv("LIVE_VIEW_PORT", "8766"))
    live_view_origin: str = os.getenv("LIVE_VIEW_ORIGIN", "").rstrip("/")
    live_view_parent_origin: str = os.getenv(
        "LIVE_VIEW_PARENT_ORIGIN", "https://daily.sig.systems"
    ).rstrip("/")
    # ADR-0023: "file" reads the *_FILE paths below; "remote" (not yet implemented)
    # will enrol against the external TLS provisioning service.
    tls_provisioning_mode: str = os.getenv("TLS_PROVISIONING_MODE", "file").lower()
    live_view_cert_file: str = _resolve_file("LIVE_VIEW_CERT_FILE")
    live_view_key_file: str = _resolve_file("LIVE_VIEW_KEY_FILE")
    live_view_issuer: str = os.getenv("LIVE_VIEW_ISSUER", "daily.sig.systems")
    live_view_audience: str = os.getenv("LIVE_VIEW_AUDIENCE", "the-watcher-live")
    live_view_issuer_kid: str = os.getenv("LIVE_VIEW_ISSUER_KID", "")
    live_view_issuer_public_key_file: str = _resolve_file(
        "LIVE_VIEW_ISSUER_PUBLIC_KEY_FILE"
    )
    live_view_station_id: int = int(os.getenv("LIVE_VIEW_STATION_ID", "0"))
    live_view_heartbeat_url: str = os.getenv("LIVE_VIEW_HEARTBEAT_URL", "")
    live_view_heartbeat_seconds: int = int(os.getenv("LIVE_VIEW_HEARTBEAT_SECONDS", "30"))
    live_view_max_viewers: int = int(os.getenv("LIVE_VIEW_MAX_VIEWERS", "3"))
    # "h264": on-demand hardware-encoded video over the WebSocket (MJPEG stays the
    # automatic fallback); "mjpeg": force the legacy JPEG-from-recorder transport.
    live_view_transport: str = os.getenv("LIVE_VIEW_TRANSPORT", "h264").lower()
    live_view_video_fps: int = int(os.getenv("LIVE_VIEW_VIDEO_FPS", "24"))
    live_view_video_width: int = int(os.getenv("LIVE_VIEW_VIDEO_WIDTH", "1280"))
    live_view_video_kbps: int = int(os.getenv("LIVE_VIEW_VIDEO_KBPS", "3000"))

    # ──     # ── Batch FFmpeg governance (PoC-2, ffmpeg-pipeline-optimization-research.md §4) ──
    # MAX_BATCH_FFMPEG — max offline/background FFmpeg encodes running at once
    #   (hourly/combined clip builders, mp4 converter, batch analyzer). Flattens
    #   CPU/RAM spikes and keeps concurrent HW-encode sessions under vendor
    #   limits (NVENC consumer: 8 sessions/system). Default 1 = fully serialized.
    max_batch_ffmpeg: int = int(os.getenv("MAX_BATCH_FFMPEG", "1"))

    # BATCH_JOB_WEIGHT — relative CPU share (1-9) for the shared batch Job
    #   Object when the live recorder needs the CPU. WEIGHT_BASED (not a hard
    #   cap), so batch work still completes, just yields under contention.
    batch_job_weight: int = int(os.getenv("BATCH_JOB_WEIGHT", "2"))

    # BATCH_JOB_MEMORY_LIMIT_MB — hard RAM ceiling for the shared batch Job
    #   Object (0 = no limit). Caps a runaway grid/convert re-encode.
    batch_job_memory_limit_mb: int = int(os.getenv("BATCH_JOB_MEMORY_LIMIT_MB", "1536"))

    # BATCH_CPU_HARD_CAP_PERCENT — optional hard CPU ceiling for batch work
    #   (0 = off, use BATCH_JOB_WEIGHT instead). WARNING: a hard cap FREEZES
    #   threads once the interval budget is spent — never apply to the recorder.
    batch_cpu_hard_cap_percent: int = int(os.getenv("BATCH_CPU_HARD_CAP_PERCENT", "0"))

    # PROC_TELEMETRY_INTERVAL_SECONDS — psutil sampling interval (CPU%, RSS) for
    #   tracked recorder/batch FFmpeg processes. Feeds the ADR-0007 profiling gate.
    proc_telemetry_interval_seconds: float = float(
        os.getenv("PROC_TELEMETRY_INTERVAL_SECONDS", "10")
    )

    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
