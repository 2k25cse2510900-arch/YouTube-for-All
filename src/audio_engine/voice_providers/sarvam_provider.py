"""Sarvam AI Voice Provider adapter powered by the Bulbul Hindi TTS model family.

Supports:
- Model: bulbul:v4-flash (latest, ultra-low latency, expressive persona control) and bulbul:v3
- Languages: hi-IN (Hindi), en-IN (Indian English)
- Voice personas: e.g. 'ishita_enhi_companion', 'shubh_enhi_ads', 'meera', etc.
- Free tier: Uses ₹100 universal signup credits from https://dashboard.sarvam.ai.
- Cost safety: Requires explicit SARVAM_API_KEY. Never enables unverified billing.
"""

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import aiohttp
import requests

from src.audio_engine.exceptions import VoiceSynthesisError
from src.audio_engine.models import (
    BoundaryType,
    TimestampBoundary,
    VoiceSynthesisResult,
)
from src.audio_engine.voice_providers.base import BaseVoiceProvider
from src.common.logger import setup_logger

logger = setup_logger("sarvam_voice_provider")

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"


class SarvamAIVoiceProvider(BaseVoiceProvider):
    """Voice synthesis adapter for Sarvam AI Bulbul TTS API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "bulbul:v4-flash",
        default_speaker: str = "shubh_enhi_ads",
    ):
        self.api_key = api_key or os.environ.get("SARVAM_API_KEY")
        self.model = model
        self.default_speaker = default_speaker

    @property
    def provider_name(self) -> str:
        return "sarvam_ai"

    @property
    def is_paid(self) -> bool:
        # Freemium model: ₹100 free signup credits, paid thereafter (~₹20 per 10k chars)
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
        voice_id: Optional[str] = None,
        output_path: Optional[Path] = None,
        target_language_code: str = "hi-IN",
        pace: float = 1.0,
        sample_rate: int = 24000,
        **kwargs: Any,
    ) -> VoiceSynthesisResult:
        """Synthesize Hindi speech via Sarvam AI Bulbul API."""
        if not self.api_key:
            raise VoiceSynthesisError(
                "SARVAM_API_KEY is not configured. Sarvam AI requires an API subscription key. "
                "You can obtain ₹100 worth of free credits by signing up at https://dashboard.sarvam.ai "
                "and setting SARVAM_API_KEY in your .env file."
            )

        output_path = Path(output_path) if output_path else Path("output/audio/temp_sarvam.mp3")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        speaker = voice_id or self.default_speaker

        payload = {
            "text": text,
            "target_language_code": target_language_code,
            "model": self.model,
            "speaker": speaker,
            "pace": pace,
            "speech_sample_rate": sample_rate,
            "output_audio_codec": "mp3",
        }

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json",
        }

        logger.info("Calling Sarvam AI Bulbul TTS for '%s' (model: %s, speaker: %s)...", text[:30], self.model, speaker)

        async with aiohttp.ClientSession() as session:
            async with session.post(SARVAM_TTS_URL, json=payload, headers=headers) as response:
                if response.status != 200:
                    err_text = await response.text()
                    raise VoiceSynthesisError(f"Sarvam AI TTS API failed ({response.status}): {err_text}")

                res_json = await response.json()
                audios = res_json.get("audios", [])
                if not audios:
                    raise VoiceSynthesisError("Sarvam AI TTS returned no audio data.")

                audio_bytes = base64.b64decode(audios[0])
                with open(output_path, "wb") as f:
                    f.write(audio_bytes)

        logger.info("Sarvam AI synthesis successful. Audio saved to: %s", output_path)

        # Estimate duration & boundaries
        words = text.split()
        duration_sec = round(len(words) / 2.15, 2)
        file_size = output_path.stat().st_size if output_path.exists() else len(audio_bytes)

        return VoiceSynthesisResult(
            audio_path=str(output_path),
            duration_seconds=duration_sec,
            file_size_bytes=file_size,
            boundaries=[],
            cost_usd=0.0,
            is_mock_asset=False,
            provider=self.provider_name,
            voice_id=f"{self.model}:{speaker}",
        )
