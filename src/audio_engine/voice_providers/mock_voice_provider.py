"""Offline mock voice provider for zero-cost and offline unit testing."""

import math
from pathlib import Path
import struct
import wave
from typing import Any, List

from src.audio_engine.models import (
    BoundaryType,
    TimestampBoundary,
    VoiceSynthesisResult,
)
from src.audio_engine.voice_providers.base import BaseVoiceProvider


class MockVoiceProvider(BaseVoiceProvider):
    """Generates synthetic WAV audio files offline for testing."""

    @property
    def provider_name(self) -> str:
        return "mock_voice"

    @property
    def is_paid(self) -> bool:
        return False

    @property
    def is_experimental(self) -> bool:
        return False

    @property
    def is_offline(self) -> bool:
        return True

    async def synthesize_async(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        **kwargs: Any,
    ) -> VoiceSynthesisResult:
        """Generate a valid offline WAV audio file with calibrated timing boundaries."""
        clean_text = text.strip()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        words = clean_text.split()
        word_count = len(words)
        # Approximate duration at ~2.2 words per second
        duration_seconds = max(round(word_count / 2.2, 2), 1.0)

        # Generate actual WAV audio frames (44.1kHz, 16-bit mono, subtle test tone)
        sample_rate = 44100
        total_samples = int(sample_rate * duration_seconds)

        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)

            # Generate low-amplitude 220Hz test tone
            frames = bytearray()
            for i in range(total_samples):
                sample = int(1000.0 * math.sin(2.0 * math.pi * 220.0 * i / sample_rate))
                frames.extend(struct.pack("<h", sample))
            wav_file.writeframes(frames)

        # Generate exact boundary timestamps for each sentence or word
        boundaries: List[TimestampBoundary] = []
        # Split into sentences by punctuation
        import re
        sentences = [s.strip() for s in re.split(r"[.!?।]", clean_text) if s.strip()]
        if not sentences:
            sentences = [clean_text]

        time_per_sentence_ms = (duration_seconds * 1000.0) / len(sentences)
        current_offset_ms = 0.0

        for sentence in sentences:
            dur_ms = round(time_per_sentence_ms, 2)
            boundaries.append(
                TimestampBoundary(
                    text=sentence,
                    offset_ms=round(current_offset_ms, 2),
                    duration_ms=dur_ms,
                    boundary_type=BoundaryType.SENTENCE,
                )
            )
            current_offset_ms += dur_ms

        file_size = output_path.stat().st_size

        return VoiceSynthesisResult(
            audio_path=str(output_path),
            duration_seconds=duration_seconds,
            voice_id=voice_id or "mock_hi_voice",
            provider=self.provider_name,
            file_size_bytes=file_size,
            boundaries=boundaries,
            cost_usd=0.0,
            is_mock_asset=True,  # Explicitly marks offline mock audio
        )
