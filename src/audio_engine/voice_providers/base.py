"""Abstract Base Provider for Voiceover Synthesis."""

from abc import ABC, abstractmethod
import asyncio
from pathlib import Path
from typing import Any

from src.audio_engine.models import VoiceSynthesisResult


class BaseVoiceProvider(ABC):
    """Abstract interface for replaceable voice synthesis engines.

    Guarantees:
    1. Provider-independent interface.
    2. Zero-cost enforcement (paid services strictly blocked).
    3. Clear declaration of experimental status and online requirements.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier for this voice provider."""
        pass

    @property
    @abstractmethod
    def is_paid(self) -> bool:
        """True if provider incurs API fees or credit spending."""
        pass

    @property
    @abstractmethod
    def is_experimental(self) -> bool:
        """True if provider relies on uncommitted/reverse-engineered community services."""
        pass

    @property
    @abstractmethod
    def is_offline(self) -> bool:
        """True if provider operates 100% locally without internet connectivity."""
        pass

    @abstractmethod
    async def synthesize_async(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        **kwargs: Any,
    ) -> VoiceSynthesisResult:
        """Synthesize voiceover audio asynchronously, returning actual timestamp boundaries."""
        pass

    def synthesize(
        self,
        text: str,
        voice_id: str,
        output_path: Path,
        **kwargs: Any,
    ) -> VoiceSynthesisResult:
        """Synchronous wrapper around synthesize_async."""
        return asyncio.run(self.synthesize_async(text, voice_id, output_path, **kwargs))
