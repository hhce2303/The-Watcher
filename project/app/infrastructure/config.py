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
    # See project/docs/migration/ffmpeg-pipeline-optimization-research.md §3.1.
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
    # Minimum seconds between two auto-detection clip BUILDS (distinct from
    # EVENT_COOLDOWN_SECONDS, which only gates how often a detection becomes an
    # AnalyticEvent for analytics/timeline purposes). Continuous detections
    # (e.g. a person lingering) fire a new AnalyticEvent every cooldown period,
    # but each one used to schedule its own full multi-monitor clip re-encode —
    # with a 4-minute window (pre+post) and a 30s cooldown that meant up to 8
    # heavily-overlapping clips got built for the same activity. Defaults to
    # the full clip window (pre+post) so builds tile back-to-back with no
    # overlap and no gaps instead of stacking redundant encodes.
    event_auto_build_min_interval_seconds: int = int(
        os.getenv(
            "EVENT_AUTO_BUILD_MIN_INTERVAL_SECONDS",
            str(event_pre_seconds + event_post_seconds),
        )
    )

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

    # ── Operator preview HTTP server ──────────────────────────────────────────
    # Local MJPEG server started only on Operator machines so that any browser
    # on the same PC can open a live screen preview without Tauri.
    # Bind host is always 127.0.0.1 (localhost-only); never reachable over LAN.
    preview_http_host: str = os.getenv("PREVIEW_HTTP_HOST", "127.0.0.1")
    preview_http_port: int = int(os.getenv("PREVIEW_HTTP_PORT", "8787"))

    # ── OneDrive delivery (folder + share link) ───────────────────────────────
    # ONEDRIVE_ROOT — local root the LocalShareAdapter operates on.  Defaults to
    #   the conventional OneDrive sync folder so the desktop client uploads the
    #   created folder to the cloud.  Override per-deployment if OneDrive lives
    #   elsewhere.  Unlike SEGMENT_DIR/CLIPS_DIR (kept OUT of OneDrive on purpose
    #   to avoid sync locks on hot files), delivery folders are cold and *should*
    #   live inside OneDrive.
    onedrive_root: Path = _resolve_dir(
        "ONEDRIVE_ROOT",
        os.path.join(os.environ.get("USERPROFILE", r"C:\Users\Default"), "OneDrive"),
    )
    # ONEDRIVE_BASE_FOLDER — logical base path under the root where per-operator
    #   delivery folders are created (e.g. "SLC/clips-supervisor/<operator>/<YYYY-MM>").
    onedrive_base_folder: str = os.getenv("ONEDRIVE_BASE_FOLDER", "SLC/clips-supervisor")

    # Deferred Microsoft Graph adapter (OneDriveGraphAdapter) — populate these
    # once IT registers an Azure AD app; empty by default so the local adapter
    # stays in use until then.
    onedrive_client_id: str = os.getenv("ONEDRIVE_CLIENT_ID", "")
    onedrive_tenant_id: str = os.getenv("ONEDRIVE_TENANT_ID", "")

    # ── Fase 3 — ONNX batch inference ────────────────────────────────────────
    # ONNX_MODEL_PATH — absolute path to a YOLOv8/v5 ONNX model file.
    #   Empty string (default) = no model → MockDetectorAdapter stays active.
    #   Set to a valid .onnx path to enable real inference on closed clips.
    onnx_model_path: str = os.getenv("ONNX_MODEL_PATH", "")

    # INFERENCE_DEVICE — execution provider for ONNX Runtime.
    #   "cpu"       → CPUExecutionProvider (always available, no GPU needed)
    #   "directml"  → DmlExecutionProvider (DirectX 12 GPU, Windows only)
    #   "cuda"      → CUDAExecutionProvider (NVIDIA GPU, requires CUDA toolkit)
    inference_device: str = os.getenv("INFERENCE_DEVICE", "cpu").lower()

    # BATCH_FRAME_INTERVAL — extract 1 frame every N seconds from each clip.
    #   Lower = more detections but more CPU/GPU work.  Default: 1 (1fps).
    batch_frame_interval: int = int(os.getenv("BATCH_FRAME_INTERVAL", "1"))

    # ── Fase 4 — Real-time inference + analytics ──────────────────────────────
    # MOTION_THRESHOLD — fraction of changed pixels (0..1) required to pass the
    #   motion gate and invoke ONNX.  0.015 = ~1.5 % of pixels changed; raise
    #   it in flickering-screen / AC-vent environments.
    motion_threshold: float = float(os.getenv("MOTION_THRESHOLD", "0.015"))

    # LIVE_POLL_INTERVAL — seconds between preview JPEG reads for live inference.
    #   0.5 matches the preview_fps=2 written by FFmpegRecorderAdapter.
    live_poll_interval: float = float(os.getenv("LIVE_POLL_INTERVAL", "0.5"))

    # TRACKER_IOU_THRESHOLD — minimum IoU to match a detection to an existing
    #   track (greedy SORT-lite).  0.3 is a good general default.
    tracker_iou_threshold: float = float(os.getenv("TRACKER_IOU_THRESHOLD", "0.3"))

    # TRACKER_MAX_AGE — frames a track may go unmatched before eviction.
    #   At 2fps, 5 frames = 2.5 s of grace.
    tracker_max_age: int = int(os.getenv("TRACKER_MAX_AGE", "5"))

    # ── Batch FFmpeg governance (PoC-2, ffmpeg-pipeline-optimization-research.md §4) ──
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
