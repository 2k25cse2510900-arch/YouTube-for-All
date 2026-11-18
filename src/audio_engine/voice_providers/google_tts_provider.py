"""Pluggable Google Cloud TTS voice provider adapter.

SAFETY & ZERO-COST ENFORCEMENT:
- Google Cloud TTS is a commercial paid API (Standard/WaveNet/Neural2/Journey).
- By project policy, automatic fallback to paid Google Cloud TTS is strictly forbidden.
- This provider operates only if explicitly authorized with authenticated credentials.
"""

from pathlib import Path
from typing import Any, Optional

from src.audio_engine.exceptions import VoiceSynthesisError
from src.audio_engine.models import VoiceSynthesisResult
from src.audio_engine.voice_providers.base import BaseVoiceProvider
from src.common.logger import setup_logger

logger = setup_logger("google_cloud_tts_provider")


class GoogleCloudTTSVoiceProvider(BaseVoiceProvider):
    """Voice synthesis adapter for Google Cloud Text-to-Speech API."""

    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path

    @property
    def provider_name(self) -> str:
        return "google_cloud_tts"

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
        """Synthesize voiceover via Google Cloud TTS API."""
        if not self.credentials_path:
            raise VoiceSynthesisError(
                "Google Cloud TTS credentials are not configured. Under the strict ₹0 budget policy, "
                "free Edge TTS or MockVoiceProvider must be used instead."
            )
        raise NotImplementedError("Google Cloud TTS provider is available as a pluggable paid extension.")
