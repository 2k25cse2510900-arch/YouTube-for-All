"""Audio Engine package exports."""

from src.audio_engine.bgm_library import BGMLibraryManager
from src.audio_engine.exceptions import (
    AudioEngineError,
    AudioLicenseVerificationError,
    AudioMixingError,
    PaidVoiceServiceBlockedError,
    VoiceSynthesisError,
)
from src.audio_engine.mixer import AudioMixer
from src.audio_engine.native_hindi_processor import NativeHindiTextProcessor, ProcessedHindiResult
from src.audio_engine.models import (
    AudioMixResult,
    BGMTrackMetadata,
    BoundaryType,
    SFXCue,
    SFXTrackMetadata,
    TimestampBoundary,
    VoiceSynthesisResult,
)
from src.audio_engine.service import AudioEngine
from src.audio_engine.voice_providers.base import BaseVoiceProvider
from src.audio_engine.voice_providers.edge_tts_provider import EdgeTTSVoiceProvider
from src.audio_engine.voice_providers.mock_voice_provider import MockVoiceProvider

__all__ = [
    "AudioEngine",
    "NativeHindiTextProcessor",
    "ProcessedHindiResult",
    "AudioMixer",
    "BGMLibraryManager",
    "BaseVoiceProvider",
    "EdgeTTSVoiceProvider",
    "MockVoiceProvider",
    "VoiceSynthesisResult",
    "TimestampBoundary",
    "BoundaryType",
    "BGMTrackMetadata",
    "SFXTrackMetadata",
    "SFXCue",
    "AudioMixResult",
    "AudioEngineError",
    "VoiceSynthesisError",
    "AudioMixingError",
    "AudioLicenseVerificationError",
    "PaidVoiceServiceBlockedError",
]
