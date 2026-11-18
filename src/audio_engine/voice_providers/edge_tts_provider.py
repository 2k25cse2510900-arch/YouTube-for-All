"""Experimental Edge TTS voice synthesis provider with Hinglish dual-script processing and prosody control.

NOTICE & USAGE DISCLOSURE:
- Edge TTS relies on the Microsoft Edge online browser speech service.
- It is NOT an offline engine; internet connectivity is required.
- It is NOT officially supported, endorsed, or SLA-guaranteed by Microsoft as an API.
- It is NOT guaranteed to remain permanently available or free.
- If Microsoft alters or terminates endpoint access, this adapter will stop gracefully.
- Automatic fallback to paid services (ElevenLabs, Google Cloud TTS, OpenAI) is STRICTLY PROHIBITED.
"""

import asyncio
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any, List, Optional

import aiohttp
import edge_tts

from src.audio_engine.exceptions import VoiceSynthesisError
from src.audio_engine.hinglish_processor import HinglishTextProcessor
from src.audio_engine.native_hindi_processor import NativeHindiTextProcessor
from src.audio_engine.models import (
    BoundaryType,
    TimestampBoundary,
    VoiceSynthesisResult,
)
from src.audio_engine.prosody import DeliveryStyle, ProsodyController
from src.audio_engine.voice_providers.base import BaseVoiceProvider
from src.common.logger import setup_logger

logger = setup_logger("edge_tts_provider")


class EdgeTTSVoiceProvider(BaseVoiceProvider):
    """Experimental voice synthesis adapter powered by edge-tts with Hinglish dual-script and prosody control."""

    def __init__(
        self,
        processor: Optional[Any] = None,
        prosody_controller: Optional[ProsodyController] = None,
    ):
        self.processor = processor or NativeHindiTextProcessor()
        self.prosody = prosody_controller or ProsodyController()

    @property
    def provider_name(self) -> str:
        return "edge_tts"

    @property
    def is_paid(self) -> bool:
        return False

    @property
    def is_experimental(self) -> bool:
        return True

    @property
    def is_offline(self) -> bool:
        return False

    async def synthesize_async(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
        volume: Optional[str] = None,
        delivery_style: Optional[DeliveryStyle] = None,
        enable_dual_script: bool = True,
        **kwargs: Any,
    ) -> VoiceSynthesisResult:
        """Synthesize Hindi/Hinglish speech and extract fine-grained word timestamps."""
        clean_text = text.strip()
        if not clean_text:
            raise VoiceSynthesisError("Cannot synthesize voiceover from empty text.")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Determine prosody parameters
        if delivery_style:
            profile = self.prosody.get_profile(delivery_style)
        else:
            inferred_style = self.prosody.infer_style_from_text(clean_text)
            profile = self.prosody.get_profile(inferred_style)

        target_rate = rate or profile.rate
        target_pitch = pitch or profile.pitch
        target_volume = volume or profile.volume

        # 2. Text preprocessing: Hinglish Dual-Script Expansion
        if enable_dual_script:
            processed = self.processor.process_text(clean_text)
            speech_text = processed.speech_text
        else:
            speech_text = clean_text

        logger.info(
            "Synthesizing voiceover with Edge TTS (Voice: %s, Rate: %s, Pitch: %s, Length: %d chars)...",
            voice_id,
            target_rate,
            target_pitch,
            len(speech_text),
        )
        start_time = time.perf_counter()

        boundaries: List[TimestampBoundary] = []
        audio_buffer = bytearray()
        max_retries = 3
        last_error = None

        for attempt in range(1, max_retries + 1):
            boundaries.clear()
            audio_buffer.clear()
            try:
                fresh_connector = aiohttp.TCPConnector()
                communicate = edge_tts.Communicate(
                    text=speech_text,
                    voice=voice_id,
                    rate=target_rate,
                    pitch=target_pitch,
                    volume=target_volume,
                    boundary="WordBoundary",
                    connector=fresh_connector,
                    connect_timeout=15,
                    receive_timeout=60,
                )
                async for chunk in communicate.stream():
                    chunk_type = chunk.get("type")

                    if chunk_type == "audio":
                        audio_buffer.extend(chunk.get("data", b""))

                    elif chunk_type == "WordBoundary":
                        # Actual word timestamp from stream (offset and duration are in 100ns ticks)
                        offset_ms = chunk["offset"] / 10000.0
                        dur_ms = chunk["duration"] / 10000.0
                        boundaries.append(
                            TimestampBoundary(
                                text=chunk.get("text", "").strip(),
                                offset_ms=round(offset_ms, 2),
                                duration_ms=round(dur_ms, 2),
                                boundary_type=BoundaryType.WORD,
                            )
                        )

                    elif chunk_type == "SentenceBoundary":
                        # Actual sentence timestamp from stream
                        offset_ms = chunk["offset"] / 10000.0
                        dur_ms = chunk["duration"] / 10000.0
                        boundaries.append(
                            TimestampBoundary(
                                text=chunk.get("text", "").strip(),
                                offset_ms=round(offset_ms, 2),
                                duration_ms=round(dur_ms, 2),
                                boundary_type=BoundaryType.SENTENCE,
                            )
                        )

                if not audio_buffer:
                    raise VoiceSynthesisError("Edge TTS returned zero audio bytes.")

                # Strict guard: Fail if no valid timestamps were received
                if not boundaries:
                    raise VoiceSynthesisError(
                        f"Edge TTS produced audio ({len(audio_buffer)} bytes) but returned zero valid "
                        f"sentence or word boundary timestamps for voice '{voice_id}'."
                    )

                # Re-align word boundaries back to original script tokens for exact subtitle matching
                if enable_dual_script and boundaries:
                    boundaries = self.processor.align_boundaries(boundaries, clean_text)

                # Write audio to disk (convert to broadcast WAV if .wav requested)
                if output_path.suffix.lower() == ".wav" and shutil.which("ffmpeg"):
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
                        tf.write(audio_buffer)
                        temp_mp3 = Path(tf.name)
                    try:
                        cmd = [
                            "ffmpeg", "-y", "-i", str(temp_mp3),
                            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
                            str(output_path),
                        ]
                        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    finally:
                        temp_mp3.unlink(missing_ok=True)
                else:
                    with open(output_path, "wb") as f:
                        f.write(audio_buffer)

                # Successfully completed synthesis
                last_error = None
                break

            except Exception as err:
                last_error = err
                if attempt < max_retries:
                    wait_sec = attempt * 1.5
                    logger.warning(
                        "Edge TTS attempt %d/%d encountered connection issue: %s. Retrying in %.1fs...",
                        attempt, max_retries, err, wait_sec
                    )
                    await asyncio.sleep(wait_sec)
                else:
                    msg = (
                        f"Edge TTS synthesis failed for voice '{voice_id}' after {max_retries} attempts: {err}. "
                        f"Execution stopped gracefully. Zero-cost policy prohibits fallback to paid APIs."
                    )
                    logger.error(msg)
                    raise VoiceSynthesisError(msg) from err

        file_size = output_path.stat().st_size
        elapsed = round(time.perf_counter() - start_time, 3)

        # Compute actual duration from last boundary
        last_b = max(boundaries, key=lambda b: b.end_seconds)
        duration_seconds = last_b.end_seconds

        logger.info(
            "Edge TTS successfully generated '%s' (%.2fs, %d bytes, %d boundaries in %.3fs)",
            output_path.name,
            duration_seconds,
            file_size,
            len(boundaries),
            elapsed,
        )

        return VoiceSynthesisResult(
            audio_path=str(output_path),
            duration_seconds=duration_seconds,
            voice_id=voice_id,
            provider=self.provider_name,
            file_size_bytes=file_size,
            boundaries=boundaries,
            cost_usd=0.0,
            is_mock_asset=False,  # Genuine voice synthesis
        )
