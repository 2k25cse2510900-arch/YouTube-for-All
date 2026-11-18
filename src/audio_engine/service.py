"""Audio Engine orchestrating voiceover synthesis, BGM curation, prosody control, and audio ducking."""

from pathlib import Path
import shutil
from typing import Any, List, Optional

from config.settings import get_settings
from src.audio_engine.bgm_library import BGMLibraryManager
from src.audio_engine.continuity import AudioContinuityProcessor
from src.audio_engine.exceptions import AudioEngineError
from src.audio_engine.hinglish_processor import HinglishTextProcessor
from src.audio_engine.native_hindi_processor import NativeHindiTextProcessor
from src.audio_engine.mixer import AudioMixer
from src.audio_engine.models import (
    AudioMixResult,
    BGMTrackMetadata,
    BoundaryType,
    SFXCue,
    TimestampBoundary,
    VoiceSynthesisResult,
)
from src.audio_engine.prosody import DeliveryStyle, EmotionController, ProsodyController
from src.audio_engine.quality_evaluator import VoiceQualityChecker, VoiceQualityReport
from src.audio_engine.voice_providers.base import BaseVoiceProvider
from src.audio_engine.voice_providers.edge_tts_provider import EdgeTTSVoiceProvider
from src.audio_engine.voice_providers.mock_voice_provider import MockVoiceProvider
from src.common.logger import setup_logger
from src.storyboard_generator.models import StoryboardDossier

logger = setup_logger("audio_engine")


class AudioEngine:
    """Primary service coordinating voiceover generation, licensed BGM, and audio mixing."""

    def __init__(
        self,
        voice_provider: Optional[BaseVoiceProvider] = None,
        bgm_manager: Optional[BGMLibraryManager] = None,
        mixer: Optional[AudioMixer] = None,
        storage_manager: Optional[Any] = None,
        hinglish_processor: Optional[HinglishTextProcessor] = None,
        native_hindi_processor: Optional[NativeHindiTextProcessor] = None,
        prosody_controller: Optional[ProsodyController] = None,
        continuity_processor: Optional[AudioContinuityProcessor] = None,
        quality_checker: Optional[VoiceQualityChecker] = None,
    ):
        settings = get_settings()
        self.settings = settings.audio

        # Select provider based on configuration
        if voice_provider is not None:
            self.voice_provider = voice_provider
        elif self.settings.voice_provider == "edge_tts":
            self.voice_provider = EdgeTTSVoiceProvider()
        else:
            self.voice_provider = MockVoiceProvider()

        self.bgm_manager = bgm_manager or BGMLibraryManager()
        self.mixer = mixer or AudioMixer()
        self.hinglish_processor = hinglish_processor or HinglishTextProcessor()
        self.native_hindi_processor = native_hindi_processor or NativeHindiTextProcessor()
        self.prosody_controller = prosody_controller or ProsodyController()
        self.continuity_processor = continuity_processor or AudioContinuityProcessor()
        self.quality_checker = quality_checker or VoiceQualityChecker(self.continuity_processor)

        if storage_manager is not None:
            self.storage_manager = storage_manager
        else:
            from src.storage_manager.service import StorageManager
            self.storage_manager = StorageManager()

        logger.info(
            "AudioEngine initialized (Provider: %s, Paid: %s)",
            self.voice_provider.provider_name,
            self.voice_provider.is_paid,
        )

    def synthesize_voiceover(
        self,
        storyboard: StoryboardDossier,
        output_path: Path,
        voice_id: Optional[str] = None,
        delivery_style: Optional[DeliveryStyle] = None,
        scene_by_scene: bool = False,
    ) -> VoiceSynthesisResult:
        """Synthesize Hinglish voiceover narration for all scenes in a storyboard."""
        selected_voice = voice_id or self.settings.default_voice

        # Extract all scene voiceover segments
        valid_scenes = [s for s in storyboard.scenes if s.narration_hinglish and s.narration_hinglish.strip()]
        if not valid_scenes:
            raise AudioEngineError(f"Storyboard '{storyboard.storyboard_id}' contains no spoken narration.")

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if scene_by_scene and len(valid_scenes) > 1:
            logger.info(
                "Synthesizing voiceover scene-by-scene for '%s' (%d scenes)...",
                storyboard.storyboard_id,
                len(valid_scenes),
            )
            temp_dir = output_path.parent / f"_temp_scenes_{storyboard.storyboard_id}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            scene_audio_files: List[Path] = []
            all_boundaries: List[TimestampBoundary] = []
            current_offset_ms = 0.0

            try:
                for s in valid_scenes:
                    style = delivery_style or EmotionController.map_scene_to_style(
                        scene_number=s.scene_number,
                        total_scenes=len(storyboard.scenes),
                        scene_narration=s.narration_hinglish,
                        sound_effect_cue=s.sound_effect_cue,
                    )
                    sc_raw_path = temp_dir / f"scene_{s.scene_number:02d}_raw.wav"
                    sc_path = temp_dir / f"scene_{s.scene_number:02d}.wav"
                    res = self.voice_provider.synthesize(
                        text=s.narration_hinglish,
                        voice_id=selected_voice,
                        output_path=sc_raw_path,
                        delivery_style=style,
                    )

                    # Trim trailing and leading dead air produced by TTS
                    _, lead_trim_ms, _ = self.continuity_processor.trim_silence_pcm(
                        input_path=sc_raw_path,
                        output_path=sc_path,
                        pad_ms=50,
                    )
                    trimmed_metrics = self.continuity_processor.analyze_wav(sc_path)
                    scene_audio_files.append(sc_path)

                    for b in res.boundaries:
                        adj_offset = max(0.0, b.offset_ms - lead_trim_ms)
                        all_boundaries.append(
                            TimestampBoundary(
                                text=b.text,
                                offset_ms=round(current_offset_ms + adj_offset, 2),
                                duration_ms=b.duration_ms,
                                boundary_type=b.boundary_type,
                            )
                        )
                    # Natural clause pause between scenes (220ms)
                    current_offset_ms += (trimmed_metrics.duration_seconds * 1000.0) + 220.0

                self.continuity_processor.stitch_segments(
                    segment_paths=scene_audio_files,
                    output_path=output_path,
                    pause_between_ms=220,
                )
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

            file_size = output_path.stat().st_size
            last_b = max(all_boundaries, key=lambda b: b.end_seconds) if all_boundaries else None
            duration = last_b.end_seconds if last_b else self.continuity_processor.analyze_wav(output_path).duration_seconds

            return VoiceSynthesisResult(
                audio_path=str(output_path),
                duration_seconds=round(duration, 3),
                voice_id=selected_voice,
                provider=self.voice_provider.provider_name,
                file_size_bytes=file_size,
                boundaries=all_boundaries,
                cost_usd=0.0,
                is_mock_asset=self.voice_provider.is_offline,
            )

        # Single-pass synthesis
        narration_segments = [s.narration_hinglish.strip() for s in valid_scenes]
        full_narration = " ".join(narration_segments)
        logger.info(
            "Synthesizing voiceover for storyboard '%s' (%d scenes, %d words)...",
            storyboard.storyboard_id,
            len(narration_segments),
            len(full_narration.split()),
        )

        return self.voice_provider.synthesize(
            text=full_narration,
            voice_id=selected_voice,
            output_path=output_path,
            delivery_style=delivery_style,
        )

    def evaluate_voice_quality(
        self,
        audio_path: Path,
        script_text: str,
        boundaries: Optional[List[TimestampBoundary]] = None,
    ) -> VoiceQualityReport:
        """Run automated acoustic QA on synthesized speech."""
        return self.quality_checker.evaluate_audio(audio_path, script_text, boundaries)

    def mix_storyboard_audio(
        self,
        voiceover_wav_path: Path,
        storyboard: StoryboardDossier,
        output_wav_path: Path,
        bgm_track: Optional[BGMTrackMetadata] = None,
        allow_synthetic_fallback: bool = False,
        is_mock_asset: bool = False,
    ) -> AudioMixResult:
        """Mix voiceover audio with licensed background music (if available) and sound effect cues."""
        if bgm_track is None:
            mood = storyboard.bgm_suggestion.get("mood", "Cinematic")
            bgm_track = self.bgm_manager.get_track_for_mood(mood)

        # Collect SFX cues from storyboard scenes
        sfx_cues: List[SFXCue] = []
        accumulated_time = 0.0
        for scene in storyboard.scenes:
            if scene.sound_effect_cue:
                sfx_cues.append(
                    SFXCue(
                        cue_name=scene.sound_effect_cue,
                        start_time_seconds=accumulated_time,
                        volume=0.8,
                    )
                )
            accumulated_time += scene.suggested_duration_seconds

        if bgm_track:
            logger.info(
                "Mixing audio for '%s': Voiceover + BGM '%s' (%s) + %d SFX cue(s)...",
                storyboard.storyboard_id,
                bgm_track.title,
                bgm_track.license,
                len(sfx_cues),
            )
        else:
            logger.info(
                "Mixing audio for '%s': Voiceover only (No BGM) + %d SFX cue(s)...",
                storyboard.storyboard_id,
                len(sfx_cues),
            )

        return self.mixer.mix_wav_audio(
            voiceover_wav_path=voiceover_wav_path,
            output_wav_path=output_wav_path,
            bgm_track=bgm_track,
            sfx_cues=sfx_cues,
            voice_volume=self.settings.voice_volume,
            bgm_ducked_volume=self.settings.bgm_volume_ducked,
            bgm_normal_volume=self.settings.bgm_volume_normal,
            allow_synthetic_fallback=allow_synthetic_fallback,
            is_mock_asset=is_mock_asset,
        )

    def synthesize_and_register_voiceover(
        self,
        storyboard: StoryboardDossier,
        production_id: str,
        voice_id: Optional[str] = None,
    ) -> tuple[VoiceSynthesisResult, Any]:
        """Synthesize voiceover directly into the production package directory and register it with StorageManager."""
        from src.storage_manager.models import ProductionAssetType

        package = self.storage_manager.get_package(production_id, storyboard_id=storyboard.storyboard_id)
        if not package:
            package = self.storage_manager.create_production_package(
                storyboard_id=storyboard.storyboard_id,
                production_id=production_id,
            )

        audio_dir = Path(package.root_dir) / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        wav_path = audio_dir / f"voiceover_{storyboard.storyboard_id}.wav"

        voice_res = self.synthesize_voiceover(storyboard, wav_path, voice_id=voice_id)

        asset = self.storage_manager.register_asset(
            production_id=production_id,
            asset_type=ProductionAssetType.VOICEOVER_AUDIO,
            file_path=wav_path,
            storyboard_id=storyboard.storyboard_id,
            is_mock_asset=voice_res.is_mock_asset,
            metadata={
                "provider": voice_res.provider,
                "voice_id": voice_res.voice_id,
                "duration_seconds": voice_res.duration_seconds,
                "cost_usd": voice_res.cost_usd,
            },
        )
        return voice_res, asset
