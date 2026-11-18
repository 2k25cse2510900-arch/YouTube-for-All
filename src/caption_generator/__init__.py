"""Caption & Subtitles Generator Module.

Responsibilities:
- Generate word-level or phrase-level animated subtitles for vertical Shorts.
- Align timestamps precisely with the voiceover audio track.
- Style captions with high contrast, legible typography, and safe-zone margins (avoiding YouTube Shorts UI overlay areas).
- Export subtitles in standard formats (e.g., ASS, SRT).
"""

from src.caption_generator.models import (
    CaptionFormat,
    CaptionItem,
    CaptionStyle,
)
from src.caption_generator.service import SubtitleGenerator

__all__ = [
    "SubtitleGenerator",
    "CaptionFormat",
    "CaptionStyle",
    "CaptionItem",
]
