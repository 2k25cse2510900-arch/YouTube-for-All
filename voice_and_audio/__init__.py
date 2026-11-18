"""Voice and Audio Processing domain facade for YouTube-for-All."""
from src.audio_engine.service import AudioEngine
from src.audio_engine.voice_providers.edge_tts_provider import EdgeTTSVoiceProvider
from src.audio_engine.voice_providers.sarvam_provider import SarvamAIVoiceProvider
from src.audio_engine.mixer import AudioMixer
from src.audio_engine.continuity import AudioContinuityProcessor
from src.audio_engine.prosody import ProsodyController, EmotionController
from src.audio_engine.hinglish_processor import HinglishTextProcessor
from src.audio_engine.native_hindi_processor import NativeHindiTextProcessor

__all__ = [
    "AudioEngine",
    "EdgeTTSVoiceProvider",
    "SarvamAIVoiceProvider",
    "AudioMixer",
    "AudioContinuityProcessor",
    "ProsodyController",
    "EmotionController",
    "HinglishTextProcessor",
    "NativeHindiTextProcessor",
]
