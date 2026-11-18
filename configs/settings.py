"""Application settings and configuration management."""

from functools import lru_cache
import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Determine Project Root (one level up from config directory)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env if present
load_dotenv(PROJECT_ROOT / ".env")


class PathSettings(BaseModel):
    """File and directory path configurations."""

    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    scripts_dir: Path = PROJECT_ROOT / "data" / "scripts"
    processed_dir: Path = PROJECT_ROOT / "data" / "processed"

    output_dir: Path = PROJECT_ROOT / "output"
    videos_output_dir: Path = PROJECT_ROOT / "output" / "videos"
    thumbnails_output_dir: Path = PROJECT_ROOT / "output" / "thumbnails"
    images_output_dir: Path = PROJECT_ROOT / "output" / "images"
    productions_output_dir: Path = PROJECT_ROOT / "output" / "productions"
    storage_manifest_dir: Path = PROJECT_ROOT / "data" / "processed" / "storage"
    audio_assets_dir: Path = PROJECT_ROOT / "assets" / "audio"
    bgm_assets_dir: Path = PROJECT_ROOT / "assets" / "audio" / "bgm"
    sfx_assets_dir: Path = PROJECT_ROOT / "assets" / "audio" / "sfx"

    logs_dir: Path = PROJECT_ROOT / "logs"
    secrets_dir: Path = PROJECT_ROOT / "secrets"

    # Credentials paths (never committed or exposed)
    client_secret_file: Path = PROJECT_ROOT / os.getenv(
        "GOOGLE_CLIENT_SECRETS_FILE", "secrets/client_secret.json"
    )
    token_file: Path = PROJECT_ROOT / os.getenv(
        "GOOGLE_TOKEN_FILE", "token.json"
    )


class PublishingSettings(BaseModel):
    """Publishing safeguards and scheduling rules."""

    require_human_approval: bool = Field(
        default_factory=lambda: os.getenv(
            "REQUIRE_HUMAN_APPROVAL", "true"
        ).lower()
        == "true"
    )
    publish_interval_hours: int = Field(
        default_factory=lambda: int(os.getenv("PUBLISH_INTERVAL_HOURS", "24"))
    )
    default_publish_time: str = Field(
        default_factory=lambda: os.getenv("DEFAULT_PUBLISH_TIME", "18:00")
    )
    default_privacy_status: str = Field(
        default_factory=lambda: os.getenv(
            "YOUTUBE_DEFAULT_PRIVACY_STATUS", "private"
        )
    )


class VideoSettings(BaseModel):
    """YouTube Shorts video rendering specifications."""

    width: int = Field(
        default_factory=lambda: int(os.getenv("VIDEO_WIDTH", "1080"))
    )
    height: int = Field(
        default_factory=lambda: int(os.getenv("VIDEO_HEIGHT", "1920"))
    )
    fps: int = Field(default_factory=lambda: int(os.getenv("VIDEO_FPS", "30")))
    max_duration_seconds: int = 60  # YouTube Shorts ceiling
    aspect_ratio: str = Field(default="9:16")
    ffmpeg_path: str = Field(
        default_factory=lambda: os.getenv("FFMPEG_PATH", "ffmpeg")
    )
    ffprobe_path: str = Field(
        default_factory=lambda: os.getenv("FFPROBE_PATH", "ffprobe")
    )
    encoding_preset: str = Field(
        default_factory=lambda: os.getenv("VIDEO_ENCODING_PRESET", "veryfast")
    )
    crf: int = Field(
        default_factory=lambda: int(os.getenv("VIDEO_CRF", "23"))
    )
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    pixel_format: str = "yuv420p"
    render_timeout_seconds: int = 300


class YouTubeSettings(BaseModel):
    """YouTube API scope definitions."""

    scopes: List[str] = [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.upload",
    ]


class GeminiSettings(BaseModel):
    """Google Gemini AI API configurations."""

    api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY")
    )
    model: str = Field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    )
    fallback_model: str = Field(
        default_factory=lambda: os.getenv(
            "GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite"
        )
    )
    timeout_seconds: int = Field(
        default_factory=lambda: int(os.getenv("GEMINI_TIMEOUT_SECONDS", "30"))
    )
    max_retries: int = Field(
        default_factory=lambda: int(os.getenv("GEMINI_MAX_RETRIES", "3"))
    )
    temperature: float = 0.2  # Low temperature to prioritize factual precision


class StoryboardSettings(BaseModel):
    """Configuration for AI Script and Storyboard Generation."""

    default_speech_rate: float = Field(
        default_factory=lambda: float(os.getenv("STORYBOARD_SPEECH_RATE", "2.2"))
    )
    default_pause_budget: float = Field(
        default_factory=lambda: float(os.getenv("STORYBOARD_PAUSE_BUDGET", "2.0"))
    )
    default_target_duration: float = Field(
        default_factory=lambda: float(os.getenv("STORYBOARD_TARGET_DURATION", "45.0"))
    )
    default_language: str = Field(
        default_factory=lambda: os.getenv("STORYBOARD_DEFAULT_LANGUAGE", "Hinglish")
    )


class ImageEngineSettings(BaseModel):
    """Configuration for Image Generation Engine under strict zero-budget enforcement."""

    provider: str = Field(
        default_factory=lambda: os.getenv("IMAGE_PROVIDER", "mock_pillow")
    )
    zero_budget_mode: bool = Field(default=True)  # Hard zero-budget enforcement
    max_budget_usd: float = 0.0  # ₹0 budget ceiling: no paid APIs allowed
    width: int = Field(default=1080)
    height: int = Field(default=1920)
    aspect_ratio: str = Field(default="9:16")
    require_human_image_approval: bool = Field(default=True)
    allow_mock_in_production: bool = Field(default=False)  # Strictly reject mocks in video production


class StorageSettings(BaseModel):
    """Configuration for local storage management and automatic cleanup."""

    failed_retention_days: int = Field(
        default_factory=lambda: int(os.getenv("STORAGE_FAILED_RETENTION_DAYS", "7"))
    )
    abandoned_retention_hours: int = Field(
        default_factory=lambda: int(os.getenv("STORAGE_ABANDONED_RETENTION_HOURS", "24"))
    )
    auto_cleanup_after_upload: bool = Field(
        default_factory=lambda: os.getenv("STORAGE_AUTO_CLEANUP", "true").lower() == "true"
    )
    dry_run_default: bool = Field(
        default_factory=lambda: os.getenv("STORAGE_DRY_RUN", "true").lower() == "true"
    )
    keep_previous_masters: int = Field(
        default_factory=lambda: int(os.getenv("STORAGE_KEEP_PREVIOUS_MASTERS", "1"))
    )
    allow_master_deletion: bool = Field(
        default_factory=lambda: os.getenv("STORAGE_ALLOW_MASTER_DELETION", "false").lower() == "true"
    )
    cleanup_ffmpeg_intermediates: bool = Field(
        default_factory=lambda: os.getenv("STORAGE_CLEANUP_FFMPEG_INTERMEDIATES", "true").lower() == "true"
    )


class AudioSettings(BaseModel):
    """Configuration for Voiceover TTS, BGM, and SFX mixing."""

    voice_provider: str = Field(
        default_factory=lambda: os.getenv("AUDIO_VOICE_PROVIDER", "edge_tts")
    )
    default_voice: str = Field(
        default_factory=lambda: os.getenv("AUDIO_DEFAULT_VOICE", "hi-IN-MadhurNeural")
    )
    fallback_voice: str = Field(
        default_factory=lambda: os.getenv("AUDIO_FALLBACK_VOICE", "hi-IN-SwaraNeural")
    )
    voice_rate: str = Field(
        default_factory=lambda: os.getenv("AUDIO_VOICE_RATE", "+0%")
    )
    bgm_volume_normal: float = 0.30
    bgm_volume_ducked: float = 0.15  # BGM volume during active speech
    voice_volume: float = 1.0
    zero_budget_mode: bool = True  # Strict ₹0 enforcement; paid voice APIs permanently barred


class Settings(BaseModel):
    """Master configuration aggregating all sub-settings."""

    app_name: str = "YouTube-for-All"
    log_level: str = Field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )
    paths: PathSettings = Field(default_factory=PathSettings)
    publishing: PublishingSettings = Field(default_factory=PublishingSettings)
    video: VideoSettings = Field(default_factory=VideoSettings)
    youtube: YouTubeSettings = Field(default_factory=YouTubeSettings)
    gemini: GeminiSettings = Field(default_factory=GeminiSettings)
    storyboard: StoryboardSettings = Field(default_factory=StoryboardSettings)
    image_engine: ImageEngineSettings = Field(default_factory=ImageEngineSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)


@lru_cache()
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings."""
    return Settings()
