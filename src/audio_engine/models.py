"""Data models for Voice Synthesis, BGM Licensing, and Audio Mixing."""

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, field_validator


class BoundaryType(str, Enum):
    """Granularity of speech timestamps."""

    SENTENCE = "sentence"
    WORD = "word"


class TimestampBoundary(BaseModel):
    """Actual speech boundary timestamp event extracted from voice synthesis."""

    text: str = Field(..., min_length=1, description="Spoken word or sentence text")
    offset_ms: float = Field(ge=0.0, description="Start offset in milliseconds")
    duration_ms: float = Field(ge=0.0, description="Duration in milliseconds")
    boundary_type: BoundaryType = Field(default=BoundaryType.SENTENCE)

    @property
    def start_seconds(self) -> float:
        """Start time in seconds."""
        return round(self.offset_ms / 1000.0, 3)

    @property
    def end_seconds(self) -> float:
        """End time in seconds."""
        return round((self.offset_ms + self.duration_ms) / 1000.0, 3)


class VoiceSynthesisResult(BaseModel):
    """Result of generating speech audio from script narration."""

    audio_path: Union[str, Path] = Field(..., description="Path to generated audio file")
    duration_seconds: float = Field(ge=0.0)
    voice_id: str
    provider: str
    file_size_bytes: int = Field(default=0, ge=0)
    boundaries: List[TimestampBoundary] = Field(default_factory=list)
    cost_usd: float = Field(default=0.0, le=0.0, description="Strictly ₹0.00 ceiling")
    is_mock_asset: bool = Field(
        default=False,
        description="True for Mock/Placeholder audio. Mock audio is permanently forbidden in video production.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("audio_path", mode="before")
    @classmethod
    def coerce_audio_path_to_str(cls, v: Any) -> str:
        """Coerce Path / WindowsPath / PosixPath inputs to a valid string representation."""
        if isinstance(v, Path):
            return str(v)
        if isinstance(v, str):
            if not v.strip():
                raise ValueError("audio_path must not be an empty string.")
            return v
        return str(v)


class BGMTrackMetadata(BaseModel):
    """Metadata tracking individually verified licensing for background music.

    CRITICAL RULE:
    FreePD.com is closed and must NOT be used.
    YouTube Audio Library tracks with attribution-not-required status are the preferred source.
    """

    track_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    artist: str = Field(..., min_length=1)
    source: str = Field(default="YouTube Audio Library")
    license: str = Field(default="YouTube Audio Library License - Attribution Not Required")
    license_url: Optional[str] = "https://support.google.com/youtube/answer/3376882"
    attribution_required: bool = Field(default=False)
    attribution_text: Optional[str] = None
    file_path: str = Field(...)
    file_checksum: Optional[str] = Field(default=None, description="SHA-256 checksum of physical audio file")
    duration_seconds: float = Field(default=0.0, ge=0.0)
    mood: str = "Cinematic"
    tempo: str = "Medium"
    status: str = Field(default="ACTIVE", description="ACTIVE, DISABLED, or UNVERIFIED")
    is_verified: bool = Field(default=True, description="Whether track identity and license are verified on disk")

    @property
    def is_file_on_disk(self) -> bool:
        """Check whether the physical audio file is actually present on disk."""
        return Path(self.file_path).is_file()


class SFXTrackMetadata(BaseModel):
    """Metadata for verified sound effects."""

    sfx_id: str = Field(...)
    name: str = Field(...)
    source: str = Field(default="Verified Creative Commons / Public Domain")
    license: str = Field(default="CC0 / Public Domain")
    file_path: str = Field(...)
    file_checksum: Optional[str] = Field(default=None, description="SHA-256 checksum of physical audio file")
    duration_seconds: float = Field(default=0.0, ge=0.0)

    @property
    def is_file_on_disk(self) -> bool:
        """Check whether the physical sound effect file is actually present on disk."""
        return Path(self.file_path).is_file()


class SFXCue(BaseModel):
    """Cue directing where to inject an SFX in the audio timeline."""

    cue_name: str
    start_time_seconds: float = Field(ge=0.0)
    volume: float = Field(default=0.8, ge=0.0, le=1.0)


class AudioMixResult(BaseModel):
    """Result of compositing voiceover, ducked BGM, and sound effects."""

    mixed_audio_path: str
    duration_seconds: float
    voiceover_duration: float
    bgm_track_id: Optional[str] = None
    sfx_count: int = 0
    file_size_bytes: int = 0
    cost_usd: float = 0.0
    is_mock_asset: bool = Field(default=False)
    is_synthetic_mix: bool = Field(
        default=False,
        description="True if synthetic fallback tone was used instead of real on-disk BGM.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
