"""Data models for Video Editor and FFmpeg Assembly Engine."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class VideoRenderSettings(BaseModel):
    """Encoding specifications and quality parameters for vertical 9:16 Shorts."""

    width: int = Field(default=1080, ge=360, le=3840)
    height: int = Field(default=1920, ge=640, le=3840)
    fps: int = Field(default=30, ge=15, le=60)
    video_codec: str = Field(default="libx264")
    audio_codec: str = Field(default="aac")
    audio_bitrate: str = Field(default="192k")
    preset: str = Field(
        default="veryfast",
        description="FFmpeg x264 preset (e.g. ultrafast, veryfast, medium). Optimized for 8GB RAM laptops.",
    )
    crf: int = Field(
        default=23,
        ge=0,
        le=51,
        description="Constant Rate Factor. 18-28 is standard; 23 provides excellent quality at low CPU cost.",
    )
    pixel_format: str = Field(default="yuv420p", description="Standard 4:2:0 chroma subsampling for broad compatibility")
    render_timeout_seconds: int = Field(default=300, ge=30, le=1800)


class SceneClipSpec(BaseModel):
    """Specification for assembling a single scene into the video timeline."""

    scene_number: int = Field(ge=1)
    image_path: str = Field(..., min_length=1)
    duration_seconds: float = Field(gt=0.0)
    camera_movement: str = Field(default="static")
    transition_to_next: str = Field(default="hard-cut")

    @property
    def frame_count(self) -> int:
        """Frame count assuming 30 fps default unless overridden."""
        return int(round(self.duration_seconds * 30))


class VideoRenderResult(BaseModel):
    """Result of rendering a complete YouTube Short."""

    video_path: str = Field(..., min_length=1)
    duration_seconds: float = Field(ge=0.0)
    resolution: str = Field(default="1080x1920")
    fps: int = Field(default=30)
    file_size_bytes: int = Field(default=0, ge=0)
    render_duration_seconds: float = Field(default=0.0, ge=0.0)
    cost_usd: float = Field(default=0.0, le=0.0, description="Strictly ₹0.00 ceiling")
    is_mock_asset: bool = Field(
        default=False,
        description="Always False for genuine production renders. Mock assets are strictly barred.",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
