"""Data models for Subtitle and Caption generation."""

from enum import Enum
from pydantic import BaseModel, Field


class CaptionFormat(str, Enum):
    """Supported caption export formats."""

    SRT = "srt"
    ASS = "ass"


class CaptionStyle(BaseModel):
    """Style specifications for vertical 9:16 mobile YouTube Shorts captions."""

    font_name: str = "Arial"
    font_size: int = Field(default=58, ge=24, le=120)

    # ASS color format is &HAABBGGRR
    # Yellow primary: &H008AFEFE (BGR: FE, FE, 8A -> Yellow #FEF08A)
    primary_color: str = "&H008AFEFE"
    # White secondary: &H00FFFFFF
    secondary_color: str = "&H00FFFFFF"
    # Black outline: &H00000000
    outline_color: str = "&H00000000"
    back_color: str = "&H80000000"  # 50% transparent black

    bold: bool = True
    italic: bool = False
    outline_width: int = 4
    shadow: int = 2

    # ASS Alignment: 2 = Bottom Center, 5 = Top Center, 8 = Top Center, etc.
    alignment: int = 2  # Bottom-Center positioned safely above Shorts description
    margin_l: int = 100  # Safe margins from edge
    margin_r: int = 100
    margin_v: int = 380  # 380px safe margin above bottom title/channel overlay


class CaptionItem(BaseModel):
    """Individual subtitle event with actual time boundaries."""

    index: int = Field(ge=1)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(ge=0.0)
    text: str = Field(..., min_length=1)

    @property
    def duration_seconds(self) -> float:
        return round(self.end_seconds - self.start_seconds, 3)
