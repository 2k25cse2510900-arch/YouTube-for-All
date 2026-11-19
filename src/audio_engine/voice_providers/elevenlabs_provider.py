"""Pluggable ElevenLabs voice provider adapter.

SAFETY & ZERO-COST ENFORCEMENT:
- ElevenLabs is a commercial paid API requiring billed credits or subscription.
- By project policy, automatic fallback to ElevenLabs is strictly forbidden.
- This provider operates only if explicitly selected and configured by the creator.
"""

from pathlib import Path
from typing import Any, Optional

from src.audio_engine.exceptions import VoiceSynthesisError
from src.audio_engine.models import VoiceSynthesisResult
from src.audio_engine.voice_providers.base import BaseVoiceProvider
from src.common.logger import setup_logger

logger = setup_logger("elevenlabs_provider")


class ElevenLabsVoiceProvider(BaseVoiceProvider):
    """Voice synthesis adapter for ElevenLabs API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    @property
    def provider_name(self) -> str:
        return "elevenlabs"

    @property
    def is_paid(self) -> bool:
        return True

    @property
    def is_experimental(self) -> bool:
        return False

    @property
    def is_offline(self) -> bool:
        return False

    async def synthesize_async(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        **kwargs: Any,
    ) -> VoiceSynthesisResult:
        """Synthesize voiceover via ElevenLabs API."""
        if not self.api_key:
            raise VoiceSynthesisError(
                "ElevenLabs API key is not configured. Under the strict ₹0 budget policy, "
                "free Edge TTS or MockVoiceProvider must be used instead."
            )
        raise NotImplementedError("ElevenLabs provider is available as a pluggable paid extension.")
