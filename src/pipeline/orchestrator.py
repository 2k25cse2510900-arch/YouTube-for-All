"""Central Pipeline Orchestrator coordinating all subsystems, safety gates, and state tracking."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from config.settings import get_settings
from src.audio_engine.models import AudioMixResult, BGMTrackMetadata, VoiceSynthesisResult
from src.audio_engine.service import AudioEngine
from src.caption_generator.service import SubtitleGenerator
from src.common.logger import setup_logger
from src.image_engine.models import StoryboardImageManifest
from src.image_engine.service import ImageGenerationEngine
from src.pipeline.exceptions import (
    AudioSynthesisError,
    CaptionGenerationError,
    HumanApprovalRequiredError,
    MissingAudioAssetError,
    MissingSceneImageError,
    PipelineError,
    QualityGateError,
    ScriptNotApprovedError,
    UploadDisabledError,
    VideoRenderingError,
)
from src.pipeline.models import (
    PipelineConfig,
    PipelineProductionState,
    PipelineStage,
    SceneImageInspectionReport,
    StageStatus,
)
from src.pipeline.recovery import PipelineRecoveryManager
from src.pipeline.state_manager import PipelineStateManager
from src.pipeline.validators import PipelineGatekeeper
from src.quality_checker.models import QualityReport
from src.quality_checker.service import QualityChecker
from src.research_engine.service import ResearchEngine
from src.script_manager.models import Script
from src.script_manager.service import ScriptManager
from src.storage_manager.models import ProductionAssetType, ProductionPackage
from src.storage_manager.service import StorageManager
from src.storyboard_generator.models import StoryboardDossier
from src.video_editor.models import VideoRenderResult
from src.video_editor.service import VideoAssemblyEngine
from src.youtube_uploader.approval import UploadApprovalGate
from src.youtube_uploader.models import PrivacyStatus, UploadApprovalRecord, UploadMetadata
from src.youtube_uploader.upload_service import YouTubeUploader

logger = setup_logger("pipeline_orchestrator")


class PipelineOrchestrator:
    """Master coordinator orchestrating end-to-end Shorts production under strict ₹0 safeguards."""

    def __init__(
        self,
        script_manager: Optional[ScriptManager] = None,
        research_engine: Optional[ResearchEngine] = None,
        image_engine: Optional[ImageGenerationEngine] = None,
        audio_engine: Optional[AudioEngine] = None,
        caption_generator: Optional[SubtitleGenerator] = None,
        video_editor: Optional[VideoAssemblyEngine] = None,
        quality_checker: Optional[QualityChecker] = None,
        youtube_uploader: Optional[YouTubeUploader] = None,
        storage_manager: Optional[StorageManager] = None,
        state_manager: Optional[PipelineStateManager] = None,
        recovery_manager: Optional[PipelineRecoveryManager] = None,
        config: Optional[PipelineConfig] = None,
    ):
        settings = get_settings()
        self.settings = settings
        self.config = config or PipelineConfig(
            upload_enabled=False,  # MANDATORY SAFETY DEFAULT
            require_human_approval=settings.publishing.require_human_approval,
            allow_synthetic_audio=False,
            default_privacy=PrivacyStatus(settings.publishing.default_privacy_status),
        )

        self.storage_manager = storage_manager or StorageManager()
        self.state_manager = state_manager or PipelineStateManager(
            base_productions_dir=self.storage_manager.productions_dir
        )
        self.recovery_manager = recovery_manager or PipelineRecoveryManager(state_manager=self.state_manager)

        self.script_manager = script_manager or ScriptManager()
        self.research_engine = research_engine or ResearchEngine()
        self.image_engine = image_engine or ImageGenerationEngine()
        self.audio_engine = audio_engine or AudioEngine(storage_manager=self.storage_manager)
        self.caption_generator = caption_generator or SubtitleGenerator()
        self.video_editor = video_editor or VideoAssemblyEngine(storage_manager=self.storage_manager)
        self.quality_checker = quality_checker or QualityChecker()
        self.youtube_uploader = youtube_uploader or YouTubeUploader(storage_manager=self.storage_manager)

        logger.info("PipelineOrchestrator initialized (Upload Enabled: %s)", self.config.upload_enabled)

    # =========================================================================
    # STAGE 1 & 2: Script Selection and Human Approval Validation
    # =========================================================================

    def select_and_validate_script(self, script_id: Optional[str] = None) -> Script:
        """Stage 1 & 2: Select a script and validate Gate A (Human Approval)."""
        if script_id:
            script = self.script_manager.get_script(script_id)
            if not script:
                raise ScriptNotApprovedError(f"Script with ID '{script_id}' not found in repository.")
        else:
            script = self.script_manager.get_next_daily_script(mark_in_production=False)
            if not script:
                raise ScriptNotApprovedError("No approved scripts found in the daily production queue.")

        PipelineGatekeeper.validate_gate_a_script(script)
        logger.info("Stage 1-2 Passed: Script '%s' ('%s') validated successfully.", script.id, script.title)
        return script

    # =========================================================================
    # STAGE 3: Scientific Research Verification Gate
    # =========================================================================

    def verify_research(self, storyboard: StoryboardDossier, script: Script) -> None:
        """Stage 3: Validate Gate B (Scientific Research Verification)."""
        PipelineGatekeeper.validate_gate_b_research(storyboard, script=script)
        logger.info("Stage 3 Passed: Scientific research verified for storyboard '%s'.", storyboard.storyboard_id)

    # =========================================================================
    # STAGE 4: Storyboard Structure Validation
    # =========================================================================

    def validate_storyboard(self, storyboard: StoryboardDossier, script: Optional[Script] = None) -> None:
        """Stage 4: Verify storyboard scene counts, narrative pacing, visual prompts, and script fidelity."""
        if not storyboard or not storyboard.scenes:
            raise PipelineError("Storyboard validation failed: Storyboard is missing or has zero scenes.")

        if len(storyboard.scenes) < 2:
            raise PipelineError(f"Storyboard '{storyboard.storyboard_id}' requires at least 2 scenes (has {len(storyboard.scenes)}).")

        if not storyboard.visual_consistency or not storyboard.visual_consistency.character_name:
            raise PipelineError(f"Storyboard '{storyboard.storyboard_id}' lacks a defined VisualConsistencyProfile.")

        # Enforce script-to-storyboard fidelity gate
        if script:
            PipelineGatekeeper.validate_script_fidelity(storyboard=storyboard, script=script)

        logger.info("Stage 4 Passed: Storyboard '%s' (%d scenes) structure and fidelity validated.", storyboard.storyboard_id, len(storyboard.scenes))


    # =========================================================================
    # STAGE 5: Production Package and State Initialization
    # =========================================================================

    def initialize_production_package(
        self,
        storyboard: StoryboardDossier,
        script: Script,
        production_id: Optional[str] = None,
    ) -> Tuple[ProductionPackage, PipelineProductionState]:
        """Stage 5: Create isolated production directory tree and initialize persistent state."""
        package = self.storage_manager.create_production_package(
            storyboard_id=storyboard.storyboard_id,
            production_id=production_id,
        )

        state = self.state_manager.get_state(package.production_id, storyboard.storyboard_id)
        if not state:
            state = self.state_manager.init_production_state(
                production_id=package.production_id,
                script_id=script.id,
                storyboard_id=storyboard.storyboard_id,
                upload_enabled=self.config.upload_enabled,
            )

        self.state_manager.acquire_lock(package.production_id)
        self.state_manager.record_stage_completed(
            production_id=package.production_id,
            stage=PipelineStage.PACKAGE_CREATION,
            output_assets={"root_dir": package.root_dir},
            notes=f"Initialized production folder at {package.root_dir}",
            storyboard_id=storyboard.storyboard_id,
        )
        logger.info("Stage 5 Passed: Created production package '%s'.", package.production_id)
        return package, state

    # =========================================================================
    # STAGE 6: Scene Image Validation and Manual Import
    # =========================================================================

    def prepare_and_validate_images(
        self,
        storyboard: StoryboardDossier,
        package: ProductionPackage,
        image_mapping: Optional[Dict[int, Path]] = None,
        auto_approve: bool = False,
    ) -> StoryboardImageManifest:
        """Stage 6: Import external production images and enforce Gate C (No mocks, all approved)."""
        self.state_manager.record_stage_start(
            production_id=package.production_id,
            stage=PipelineStage.IMAGE_VALIDATION,
            storyboard_id=storyboard.storyboard_id,
        )

        # 1. Execute manual import if mappings provided
        if image_mapping:
            logger.info("Importing %d scene image(s) for storyboard '%s'...", len(image_mapping), storyboard.storyboard_id)
            manifest = self.image_engine.import_storyboard_images(
                storyboard=storyboard,
                image_mapping=image_mapping,
                auto_approve=auto_approve or self.config.auto_approve_images,
            )
        else:
            manifest = self.image_engine.get_manifest(storyboard.storyboard_id)

        # 2. Enforce Gate C
        report = PipelineGatekeeper.validate_gate_c_images(storyboard, manifest=manifest)

        # 3. Register images in storage package
        output_assets: Dict[str, str] = {}
        if manifest:
            for img in manifest.images:
                p = Path(img.image_path)
                if p.exists():
                    self.storage_manager.register_asset(
                        production_id=package.production_id,
                        asset_type=ProductionAssetType.SCENE_IMAGE,
                        file_path=p,
                        storyboard_id=storyboard.storyboard_id,
                        is_mock_asset=img.is_mock_asset,
                        metadata={"scene_number": img.scene_number, "status": img.status.value},
                    )
                    output_assets[f"scene_{img.scene_number:02d}"] = str(p)

        self.state_manager.record_stage_completed(
            production_id=package.production_id,
            stage=PipelineStage.IMAGE_VALIDATION,
            output_assets=output_assets,
            notes=f"Validated {report.total_scenes} scene images. All approved and ready.",
            storyboard_id=storyboard.storyboard_id,
        )
        logger.info("Stage 6 Passed: Visual asset manifest verified for '%s'.", storyboard.storyboard_id)
        return manifest

    # =========================================================================
    # STAGE 7: Voiceover Synthesis
    # =========================================================================

    def synthesize_voiceover(
        self,
        storyboard: StoryboardDossier,
        package: ProductionPackage,
        voice_id: Optional[str] = None,
    ) -> VoiceSynthesisResult:
        """Stage 7: Generate natural voiceover narration and extract timestamp boundaries."""
        self.state_manager.record_stage_start(
            production_id=package.production_id,
            stage=PipelineStage.VOICE_SYNTHESIS,
            storyboard_id=storyboard.storyboard_id,
        )

        voice_out = Path(package.root_dir) / "audio" / "voiceover.mp3"
        target_voice = voice_id or self.config.voice_id or self.settings.audio.default_voice

        try:
            voice_result = self.audio_engine.synthesize_voiceover(
                storyboard=storyboard,
                output_path=voice_out,
                voice_id=target_voice,
            )
        except Exception as err:
            self.state_manager.record_stage_failed(
                package.production_id, PipelineStage.VOICE_SYNTHESIS, str(err), storyboard.storyboard_id
            )
            raise AudioSynthesisError(f"Voice synthesis failed for '{storyboard.storyboard_id}': {err}") from err

        # Enforce non-mock and non-empty
        PipelineGatekeeper.validate_gate_d_audio(
            voice_result=voice_result,
            require_bgm=False,
            allow_synthetic_audio=self.config.allow_synthetic_audio,
        )

        # Register in StorageManager
        self.storage_manager.register_asset(
            production_id=package.production_id,
            asset_type=ProductionAssetType.VOICEOVER_AUDIO,
            file_path=Path(voice_result.audio_path),
            storyboard_id=storyboard.storyboard_id,
            is_mock_asset=voice_result.is_mock_asset,
            metadata={
                "voice_id": voice_result.voice_id,
                "duration_seconds": voice_result.duration_seconds,
                "boundaries_count": len(voice_result.boundaries),
            },
        )

        self.state_manager.record_stage_completed(
            production_id=package.production_id,
            stage=PipelineStage.VOICE_SYNTHESIS,
            output_assets={"voiceover": voice_result.audio_path},
            notes=f"Synthesized {voice_result.duration_seconds:.2f}s audio with {len(voice_result.boundaries)} timestamp boundaries.",
            storyboard_id=storyboard.storyboard_id,
        )
        logger.info("Stage 7 Passed: Voiceover synthesized at '%s'.", voice_result.audio_path)
        return voice_result

    # =========================================================================
    # STAGE 8: Caption Generation
    # =========================================================================

    def generate_captions(
        self,
        voice_result: VoiceSynthesisResult,
        package: ProductionPackage,
        storyboard_id: Optional[str] = None,
    ) -> Tuple[Path, Path]:
        """Stage 8: Build synchronized SRT and styled ASS subtitles using real speech boundaries."""
        sb_id = storyboard_id or package.storyboard_id
        self.state_manager.record_stage_start(
            production_id=package.production_id,
            stage=PipelineStage.CAPTION_GENERATION,
            storyboard_id=sb_id,
        )

        srt_path = Path(package.root_dir) / "captions" / "captions.srt"
        ass_path = Path(package.root_dir) / "captions" / "captions.ass"

        try:
            caption_items = self.caption_generator.build_caption_items(voice_result.boundaries)
            exported_srt = self.caption_generator.export_srt(caption_items, srt_path)
            exported_ass = self.caption_generator.export_ass(caption_items, ass_path)
        except Exception as err:
            self.state_manager.record_stage_failed(
                package.production_id, PipelineStage.CAPTION_GENERATION, str(err), sb_id
            )
            raise CaptionGenerationError(f"Caption generation failed: {err}") from err

        # Register in storage package
        self.storage_manager.register_asset(
            production_id=package.production_id,
            asset_type=ProductionAssetType.CAPTIONS,
            file_path=exported_srt,
            storyboard_id=sb_id,
            is_mock_asset=False,
            metadata={"format": "srt", "events": len(caption_items)},
        )
        self.storage_manager.register_asset(
            production_id=package.production_id,
            asset_type=ProductionAssetType.CAPTIONS,
            file_path=exported_ass,
            storyboard_id=sb_id,
            is_mock_asset=False,
            metadata={"format": "ass", "events": len(caption_items)},
        )

        self.state_manager.record_stage_completed(
            production_id=package.production_id,
            stage=PipelineStage.CAPTION_GENERATION,
            output_assets={"captions_srt": str(exported_srt), "captions_ass": str(exported_ass)},
            notes=f"Exported {len(caption_items)} caption events to SRT and ASS.",
            storyboard_id=sb_id,
        )
        logger.info("Stage 8 Passed: Captions generated at '%s' and '%s'.", exported_srt.name, exported_ass.name)
        return exported_srt, exported_ass

    # =========================================================================
    # STAGE 9 & 10: Audio Selection and Mixing
    # =========================================================================

    def select_and_mix_audio(
        self,
        storyboard: StoryboardDossier,
        voice_result: VoiceSynthesisResult,
        package: ProductionPackage,
    ) -> Optional[AudioMixResult]:
        """Stage 9 & 10: Select licensed BGM, apply voice ducking, and mix audio."""
        self.state_manager.record_stage_start(
            production_id=package.production_id,
            stage=PipelineStage.AUDIO_MIXING,
            storyboard_id=storyboard.storyboard_id,
        )

        mood = storyboard.bgm_suggestion.get("mood", "Cinematic")
        bgm_track = self.audio_engine.bgm_manager.get_track_for_mood(mood)

        # Validate Gate D
        PipelineGatekeeper.validate_gate_d_audio(
            voice_result=voice_result,
            bgm_track=bgm_track,
            require_bgm=self.config.require_bgm,
            allow_synthetic_audio=self.config.allow_synthetic_audio,
        )

        out_mixed_wav = Path(package.root_dir) / "audio" / "mixed_audio.wav"

        # If voiceover is not WAV (e.g. MP3 from Edge TTS), convert or handle
        voice_wav_path = Path(voice_result.audio_path)
        if voice_wav_path.suffix.lower() != ".wav":
            converted_wav = Path(package.root_dir) / "audio" / "voiceover_temp.wav"
            cmd = ["-y", "-i", str(voice_wav_path), "-ar", "44100", "-ac", "2", str(converted_wav)]
            try:
                self.video_editor.ffmpeg_runner.run_ffmpeg(cmd, timeout=30)
                voice_wav_path = converted_wav
            except Exception as err:
                logger.warning("Could not transcode voiceover to WAV for mixer: %s. Using primary voice track directly.", err)
                self.state_manager.record_stage_completed(
                    production_id=package.production_id,
                    stage=PipelineStage.AUDIO_MIXING,
                    output_assets={"primary_audio": voice_result.audio_path},
                    notes="Direct voiceover track used without secondary mixer transcode.",
                    storyboard_id=storyboard.storyboard_id,
                )
                return None

        try:
            mix_result = self.audio_engine.mix_storyboard_audio(
                voiceover_wav_path=voice_wav_path,
                storyboard=storyboard,
                output_wav_path=out_mixed_wav,
                allow_synthetic_fallback=self.config.allow_synthetic_audio,
                is_mock_asset=voice_result.is_mock_asset,
            )
        except Exception as err:
            self.state_manager.record_stage_failed(
                package.production_id, PipelineStage.AUDIO_MIXING, str(err), storyboard.storyboard_id
            )
            raise MissingAudioAssetError(f"Audio mixing failed: {err}") from err

        # Register in storage package
        self.storage_manager.register_asset(
            production_id=package.production_id,
            asset_type=ProductionAssetType.INTERMEDIATE_RENDER,
            file_path=Path(mix_result.mixed_audio_path),
            storyboard_id=storyboard.storyboard_id,
            is_mock_asset=mix_result.is_synthetic_mix,
            metadata={"duration": mix_result.duration_seconds, "sfx_count": mix_result.sfx_count},
        )

        self.state_manager.record_stage_completed(
            production_id=package.production_id,
            stage=PipelineStage.AUDIO_MIXING,
            output_assets={"mixed_audio": mix_result.mixed_audio_path},
            notes=f"Mixed audio duration {mix_result.duration_seconds:.2f}s with ducked BGM and {mix_result.sfx_count} SFX.",
            storyboard_id=storyboard.storyboard_id,
        )
        logger.info("Stage 9-10 Passed: Mixed audio produced at '%s'.", mix_result.mixed_audio_path)
        return mix_result

    # =========================================================================
    # STAGE 11: Video Rendering
    # =========================================================================

    def render_video(
        self,
        storyboard: StoryboardDossier,
        manifest: StoryboardImageManifest,
        script: Script,
        voice_result: VoiceSynthesisResult,
        package: ProductionPackage,
        mixed_audio: Optional[AudioMixResult] = None,
        ass_caption_path: Optional[Path] = None,
    ) -> VideoRenderResult:
        """Stage 11: Render vertical 1080x1920 Short with Ken Burns motion, transitions, and audio."""
        self.state_manager.record_stage_start(
            production_id=package.production_id,
            stage=PipelineStage.VIDEO_RENDERING,
            storyboard_id=storyboard.storyboard_id,
        )

        # Pre-render sanity validation
        PipelineGatekeeper.validate_gate_a_script(script)
        PipelineGatekeeper.validate_gate_b_research(storyboard, script=script)
        PipelineGatekeeper.validate_gate_c_images(storyboard, manifest=manifest)
        PipelineGatekeeper.validate_gate_d_audio(
            voice_result=voice_result,
            require_bgm=False,
            allow_synthetic_audio=self.config.allow_synthetic_audio,
        )

        try:
            render_res = self.video_editor.render_short_video(
                storyboard=storyboard,
                manifest=manifest,
                script=script,
                voice_result=voice_result,
                production_package=package,
                mixed_audio_result=mixed_audio,
                ass_caption_path=ass_caption_path,
            )
        except Exception as err:
            self.state_manager.record_stage_failed(
                package.production_id, PipelineStage.VIDEO_RENDERING, str(err), storyboard.storyboard_id
            )
            raise VideoRenderingError(f"Video assembly failed for '{storyboard.storyboard_id}': {err}") from err

        res_path_str = getattr(render_res, "video_path", None) or getattr(render_res, "output_video_path", "")
        video_path = Path(res_path_str).resolve()
        if not video_path.exists() or video_path.stat().st_size == 0:
            msg = f"Video render failed: output file missing or zero bytes at {video_path}"
            self.state_manager.record_stage_failed(package.production_id, PipelineStage.VIDEO_RENDERING, msg, storyboard.storyboard_id)
            raise VideoRenderingError(msg)

        # Register in storage package if not already registered by video editor
        pkg = self.storage_manager.get_package(package.production_id, storyboard_id=storyboard.storyboard_id)
        if pkg and not any(a.file_path == str(video_path) for a in pkg.assets):
            self.storage_manager.register_asset(
                production_id=package.production_id,
                asset_type=ProductionAssetType.FINAL_VIDEO,
                file_path=video_path,
                storyboard_id=storyboard.storyboard_id,
                is_mock_asset=getattr(render_res, "is_mock_asset", False),
                metadata={
                    "duration_seconds": getattr(render_res, "duration_seconds", 0.0),
                    "resolution": getattr(render_res, "resolution", "1080x1920"),
                    "fps": getattr(render_res, "fps", 30),
                    "file_size_bytes": getattr(render_res, "file_size_bytes", 0),
                },
            )

        self.state_manager.record_stage_completed(
            production_id=package.production_id,
            stage=PipelineStage.VIDEO_RENDERING,
            output_assets={"video": str(video_path)},
            notes=f"Rendered {render_res.duration_seconds:.2f}s 1080x1920 @ {render_res.fps}fps ({render_res.file_size_bytes} bytes).",
            storyboard_id=storyboard.storyboard_id,
        )
        logger.info("Stage 11 Passed: Rendered video at '%s'.", video_path.name)
        return render_res

    # =========================================================================
    # STAGE 12: Automated Quality Verification Gate
    # =========================================================================

    def run_quality_checks(
        self,
        package: ProductionPackage,
        video_path: Path,
        script: Script,
        caption_path: Optional[Path] = None,
        storyboard_id: Optional[str] = None,
        storyboard: Optional[StoryboardDossier] = None,
        bgm_track: Optional[BGMTrackMetadata] = None,
    ) -> QualityReport:
        """Stage 12: Run complete automated quality check suite (Video, Audio, Captions, Metadata, Fidelity)."""
        sb_id = storyboard_id or package.storyboard_id
        self.state_manager.record_stage_start(
            production_id=package.production_id,
            stage=PipelineStage.QUALITY_CHECK,
            storyboard_id=sb_id,
        )

        report_file = Path(package.root_dir) / "quality_report.json"
        upload_meta = self._build_upload_metadata(script=script, bgm_track=bgm_track)

        # Quality check orchestration
        report = self.quality_checker.check_production(
            production_id=package.production_id,
            video_path=video_path,
            caption_path=caption_path,
            title=upload_meta.title,
            description=upload_meta.description,
            tags=upload_meta.tags,
            category_id=upload_meta.category_id,
            made_for_kids=upload_meta.made_for_kids,
            allow_no_captions=self.config.allow_no_captions,
            output_report_path=report_file,
            script=script,
            storyboard=storyboard,
            bgm_track=bgm_track,
        )


        # Enforce Gate E
        PipelineGatekeeper.validate_gate_e_video(video_path, report)

        state = self.state_manager.get_state(package.production_id, sb_id)
        if state:
            state.quality_report_status = report.overall_status.value
            self.state_manager.save_state(state)

        self.state_manager.record_stage_completed(
            production_id=package.production_id,
            stage=PipelineStage.QUALITY_CHECK,
            output_assets={"quality_report": str(report_file)},
            notes=f"Quality check {report.overall_status.value}. Failures: {report.total_failures}, Warnings: {report.total_warnings}.",
            storyboard_id=sb_id,
        )
        logger.info("Stage 12 Passed: Quality check %s for production '%s'.", report.overall_status.value, package.production_id)
        return report

    # =========================================================================
    # STAGE 13 & 14: Human Review, Approval Binding & Upload Preparation
    # =========================================================================

    def _build_upload_metadata(
        self,
        script: Script,
        privacy_status: PrivacyStatus = PrivacyStatus.PRIVATE,
        bgm_track: Optional[BGMTrackMetadata] = None,
    ) -> UploadMetadata:
        """Construct consistent YouTube upload metadata with transparent BGM attribution."""
        from src.audio_engine.bgm_library import BGMLibraryManager

        tags = ["#Shorts", "Science", "Anime", "ALessonWithAI"]
        if script.tags:
            tags.extend(script.tags)
        unique_tags = list(dict.fromkeys(tags))

        description = f"{script.hook}\n\n{script.body}\n\n{script.takeaway}\n\n#Shorts #Anime #Science"

        # Check for BGM attribution
        target_bgm = bgm_track
        if not target_bgm and script.metadata.get("bgm_track_id"):
            target_bgm = self.audio_engine.bgm_manager.get_track(script.metadata["bgm_track_id"])

        if target_bgm:
            attribution = BGMLibraryManager.format_attribution(target_bgm)
            if attribution and attribution not in description:
                description += f"\n\nMusic Credit:\n{attribution}"
        elif script.metadata.get("bgm_attribution_text"):
            credit = script.metadata["bgm_attribution_text"]
            if credit not in description:
                description += f"\n\nMusic Credit:\n{credit}"

        return UploadMetadata(
            title=script.title[:100],
            description=description,
            tags=unique_tags[:20],
            category_id="28",
            default_language="hi",
            default_audio_language="hi",
            privacy_status=privacy_status,
            made_for_kids=False,
        )

    def create_human_approval(
        self,
        package: ProductionPackage,
        video_path: Path,
        script: Script,
        quality_report: QualityReport,
        approver_notes: str,
        accept_warnings: bool = False,
        requested_privacy: PrivacyStatus = PrivacyStatus.PRIVATE,
        storyboard_id: Optional[str] = None,
        storyboard: Optional[StoryboardDossier] = None,
        bgm_track: Optional[BGMTrackMetadata] = None,
    ) -> UploadApprovalRecord:
        """Stage 13: Issue cryptographically bound human approval record gating upload."""
        sb_id = storyboard_id or package.storyboard_id
        self.state_manager.record_stage_start(
            production_id=package.production_id,
            stage=PipelineStage.HUMAN_REVIEW,
            storyboard_id=sb_id,
        )

        metadata = self._build_upload_metadata(script, requested_privacy, bgm_track=bgm_track)

        record = UploadApprovalGate.create_approval_record(
            production_id=package.production_id,
            video_path=video_path,
            metadata=metadata,
            quality_report=quality_report,
            approver_notes=approver_notes,
            requested_privacy=requested_privacy,
            accept_warnings=accept_warnings,
            script=script,
            storyboard=storyboard,
        )

        # Save approval in package folder
        approval_file = Path(package.root_dir) / "upload_approval.json"
        with open(approval_file, "w", encoding="utf-8") as f:
            f.write(record.model_dump_json(indent=2))

        state = self.state_manager.get_state(package.production_id, sb_id)
        if state:
            state.human_approval_id = record.video_checksum[:12]
            self.state_manager.save_state(state)

        self.state_manager.record_stage_completed(
            production_id=package.production_id,
            stage=PipelineStage.HUMAN_REVIEW,
            output_assets={"approval_record": str(approval_file)},
            notes=f"Human authorization recorded by creator (Asset SHA-256 integrity: {record.video_checksum[:12]}...).",
            storyboard_id=sb_id,
        )
        logger.info("Stage 13 Passed: Human approval issued for '%s'.", package.production_id)
        return record

    def prepare_upload_package(
        self,
        package: ProductionPackage,
        approval: UploadApprovalRecord,
        script: Script,
        video_path: Path,
        storyboard_id: Optional[str] = None,
        storyboard: Optional[StoryboardDossier] = None,
        bgm_track: Optional[BGMTrackMetadata] = None,
    ) -> Dict[str, Any]:
        """Stage 14: Prepare normalized YouTube upload metadata without executing network upload.

        CRITICAL STAGE 7D SAFEGUARD:
        Uploads are strictly disabled by default (upload_enabled=False).
        This method prepares and validates the upload package but NEVER transmits bytes to YouTube.
        """
        sb_id = storyboard_id or package.storyboard_id
        self.state_manager.record_stage_start(
            production_id=package.production_id,
            stage=PipelineStage.UPLOAD_PREPARATION,
            storyboard_id=sb_id,
        )

        metadata = self._build_upload_metadata(script, approval.requested_privacy, bgm_track=bgm_track)

        # Enforce Gate F with script and storyboard provenance
        PipelineGatekeeper.validate_gate_f_upload_approval(
            approval=approval,
            video_path=video_path,
            metadata=metadata,
            script=script,
            storyboard=storyboard,
        )

        payload_manifest = {
            "production_id": package.production_id,
            "storyboard_id": sb_id,
            "video_path": str(video_path),
            "video_checksum": approval.video_checksum,
            "metadata": metadata.model_dump(mode="json"),
            "approval_status": "VERIFIED_ACTIVE",
            "upload_enabled": self.config.upload_enabled,
            "status": "READY_FOR_UPLOAD_WHEN_AUTHORIZED",
            "message": "Upload package prepared and gated. Real YouTube upload is strictly disabled in Stage 7D.",
        }

        # Save upload staging metadata
        manifest_file = Path(package.root_dir) / "upload_staging_manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(payload_manifest, f, indent=2)

        self.state_manager.record_stage_completed(
            production_id=package.production_id,
            stage=PipelineStage.UPLOAD_PREPARATION,
            output_assets={"upload_manifest": str(manifest_file)},
            notes="Upload package prepared and gated. Upload is disabled by policy.",
            storyboard_id=sb_id,
        )


        state = self.state_manager.get_state(package.production_id, sb_id)
        if state:
            state.overall_status = StageStatus.COMPLETED
            state.completed_at = datetime.now(timezone.utc)
            self.state_manager.save_state(state)

        logger.info("Stage 14 Passed: Upload package prepared for '%s' (Upload Enabled: %s).", package.production_id, self.config.upload_enabled)
        return payload_manifest

    # =========================================================================
    # END-TO-END PIPELINE EXECUTION
    # =========================================================================

    def run_pipeline(
        self,
        script_id: Optional[str] = None,
        storyboard: Optional[StoryboardDossier] = None,
        image_mapping: Optional[Dict[int, Path]] = None,
        approver_notes: Optional[str] = None,
        accept_warnings: bool = False,
        production_id: Optional[str] = None,
        human_approval_confirmed: bool = False,
    ) -> PipelineProductionState:
        """Execute end-to-end pipeline through upload preparation under strict safety gating.

        Workflow:
        1-2. Select and validate script (Gate A).
        3. Verify research (Gate B).
        4. Validate storyboard structure.
        5. Initialize storage package and pipeline state.
        6. Validate/import scene images (Gate C).
        7. Synthesize voiceover audio (Gate D).
        8. Generate synced SRT and ASS subtitles.
        9-10. Select BGM and mix audio.
        11. Render 1080x1920 vertical video via FFmpeg.
        12. Run automated quality checks (Gate E).
        13. Issue cryptographic human approval record.
        14. Prepare gated upload package (Gate F, upload disabled).
        """
        # 1-2. Script Selection & Validation
        script = self.select_and_validate_script(script_id=script_id)

        if not storyboard:
            raise PipelineError(
                f"No StoryboardDossier provided for script '{script.id}'. "
                "A verified storyboard is required for image-based Shorts assembly."
            )

        # 3. Research Verification
        self.verify_research(storyboard, script=script)

        # 4. Storyboard Validation
        self.validate_storyboard(storyboard)

        # 5. Production Package Creation
        package, state = self.initialize_production_package(storyboard, script, production_id=production_id)

        try:
            # 6. Scene Image Validation & Import
            manifest = self.prepare_and_validate_images(
                storyboard=storyboard,
                package=package,
                image_mapping=image_mapping,
            )

            # 7. Voiceover Synthesis
            voice_result = self.synthesize_voiceover(storyboard=storyboard, package=package)

            # 8. Caption Generation
            srt_path, ass_path = self.generate_captions(
                voice_result=voice_result,
                package=package,
                storyboard_id=storyboard.storyboard_id,
            )

            # 9-10. Audio Mixing
            mixed_audio = self.select_and_mix_audio(
                storyboard=storyboard,
                voice_result=voice_result,
                package=package,
            )
            bgm_track = None
            if mixed_audio and mixed_audio.bgm_track_id:
                bgm_track = self.audio_engine.bgm_manager.get_track(mixed_audio.bgm_track_id)
            if not bgm_track:
                mood = storyboard.bgm_suggestion.get("mood", "Cinematic")
                bgm_track = self.audio_engine.bgm_manager.get_track_for_mood(mood)


            # 11. Video Rendering
            render_res = self.render_video(
                storyboard=storyboard,
                manifest=manifest,
                script=script,
                voice_result=voice_result,
                package=package,
                mixed_audio=mixed_audio,
                ass_caption_path=ass_path,
            )
            video_path = Path(getattr(render_res, "video_path", None) or getattr(render_res, "output_video_path", "")).resolve()

            # 12. Quality Checks
            quality_report = self.run_quality_checks(
                package=package,
                video_path=video_path,
                script=script,
                caption_path=srt_path,
                storyboard_id=storyboard.storyboard_id,
                storyboard=storyboard,
                bgm_track=bgm_track,
            )


            # 13. Human Review & Approval Gate
            # Non-Negotiable Rule: A passing QA report MUST NEVER automatically create human approval.
            # Require explicit confirmation (human_approval_confirmed=True) with reviewer notes.
            if not human_approval_confirmed:
                logger.info(
                    "Pipeline execution paused after Stage 12 (Quality Check) for '%s'. Explicit human approval is required.",
                    package.production_id,
                )
                state = self.state_manager.get_state(package.production_id, storyboard.storyboard_id)
                if state:
                    state.current_stage = PipelineStage.QUALITY_CHECK
                    state.overall_status = StageStatus.BLOCKED
                    state.error_message = (
                        f"Quality checks passed. Awaiting explicit human approval sign-off. "
                        f"Execute 'pipeline approve -p {package.production_id} --notes \"YOUR_NOTES\"' to approve."
                    )
                    self.state_manager.save_state(state)
                raise HumanApprovalRequiredError(
                    f"Automated quality checks passed for production '{package.production_id}', but human approval "
                    "cannot be issued automatically. Explicit human review and authorization are mandatory."
                )

            if not approver_notes or not approver_notes.strip():
                raise HumanApprovalRequiredError(
                    f"Human approval confirmed for '{package.production_id}', but mandatory approver notes are missing."
                )

            approval = self.create_human_approval(
                package=package,
                video_path=video_path,
                script=script,
                quality_report=quality_report,
                approver_notes=approver_notes,
                accept_warnings=accept_warnings,
                storyboard_id=storyboard.storyboard_id,
                storyboard=storyboard,
                bgm_track=bgm_track,
            )

            # 14. Upload Preparation
            self.prepare_upload_package(
                package=package,
                approval=approval,
                script=script,
                video_path=video_path,
                storyboard_id=storyboard.storyboard_id,
                storyboard=storyboard,
                bgm_track=bgm_track,
            )


            updated_state = self.state_manager.get_state(package.production_id, storyboard.storyboard_id)
            return updated_state or state

        finally:
            self.state_manager.release_lock(package.production_id)

    # =========================================================================
    # RESUMPTION AND RECOVERY
    # =========================================================================

    def resume_production(
        self,
        production_id: str,
        storyboard: StoryboardDossier,
        script: Script,
        image_mapping: Optional[Dict[int, Path]] = None,
        human_approval_confirmed: bool = False,
        approver_notes: Optional[str] = None,
        accept_warnings: bool = False,
    ) -> PipelineProductionState:
        """Resume an interrupted or failed production from its last safe checkpoint."""
        state, plan = self.recovery_manager.recover_production(
            production_id=production_id, storyboard_id=storyboard.storyboard_id
        )

        package = self.storage_manager.get_package(production_id, storyboard.storyboard_id)
        if not package:
            package = self.storage_manager.create_production_package(
                storyboard_id=storyboard.storyboard_id,
                production_id=production_id,
            )

        self.state_manager.acquire_lock(production_id)

        try:
            resume_stage = PipelineStage(plan["resume_stage"])
            logger.info("Resuming production '%s' from stage '%s'...", production_id, resume_stage.value)

            # Execute remaining stages starting from resume_stage
            manifest = self.image_engine.get_manifest(storyboard.storyboard_id)
            if not manifest or resume_stage == PipelineStage.IMAGE_VALIDATION:
                manifest = self.prepare_and_validate_images(storyboard, package, image_mapping=image_mapping)

            # Voiceover
            voice_out = Path(package.root_dir) / "audio" / "voiceover.mp3"
            voice_rec = state.stages.get(PipelineStage.VOICE_SYNTHESIS.value)
            if not voice_out.exists() or not voice_rec or voice_rec.status != StageStatus.COMPLETED:
                voice_result = self.synthesize_voiceover(storyboard, package)
            else:
                voice_result = VoiceSynthesisResult(
                    audio_path=str(voice_out),
                    duration_seconds=storyboard.target_duration_seconds,
                    voice_id=self.settings.audio.default_voice,
                    provider="edge_tts",
                    boundaries=[],
                    is_mock_asset=False,
                )

            # Captions
            ass_path = Path(package.root_dir) / "captions" / "captions.ass"
            srt_path = Path(package.root_dir) / "captions" / "captions.srt"
            cap_rec = state.stages.get(PipelineStage.CAPTION_GENERATION.value)
            if not ass_path.exists() or not cap_rec or cap_rec.status != StageStatus.COMPLETED:
                srt_path, ass_path = self.generate_captions(voice_result, package, storyboard.storyboard_id)

            # Video Render
            video_path = Path(package.root_dir) / "video" / f"final_{storyboard.storyboard_id}.mp4"
            vid_rec = state.stages.get(PipelineStage.VIDEO_RENDERING.value)
            if not video_path.exists() or not vid_rec or vid_rec.status != StageStatus.COMPLETED:
                render_res = self.render_video(
                    storyboard=storyboard,
                    manifest=manifest,
                    script=script,
                    voice_result=voice_result,
                    package=package,
                    ass_caption_path=ass_path,
                )
                video_path = Path(getattr(render_res, "video_path", None) or getattr(render_res, "output_video_path", "")).resolve()

            # Quality Check
            qa_rec = state.stages.get(PipelineStage.QUALITY_CHECK.value)
            qa_file = Path(package.root_dir) / "quality_report.json"
            if not qa_file.exists() or not qa_rec or qa_rec.status != StageStatus.COMPLETED:
                quality_report = self.run_quality_checks(
                    package=package,
                    video_path=video_path,
                    script=script,
                    caption_path=srt_path,
                    storyboard_id=storyboard.storyboard_id,
                )
            else:
                with open(qa_file, "r", encoding="utf-8") as f:
                    quality_report = QualityReport(**json.load(f))

            # Approval
            app_file = Path(package.root_dir) / "upload_approval.json"
            app_rec = state.stages.get(PipelineStage.HUMAN_REVIEW.value)
            if not app_file.exists() or not app_rec or app_rec.status != StageStatus.COMPLETED:
                if not human_approval_confirmed:
                    logger.info(
                        "Resumption paused after Quality Check for '%s'. Explicit human approval is required.",
                        production_id,
                    )
                    state.current_stage = PipelineStage.QUALITY_CHECK
                    state.overall_status = StageStatus.BLOCKED
                    state.error_message = (
                        f"Quality checks passed. Awaiting explicit human approval sign-off. "
                        f"Execute 'pipeline approve -p {production_id} --notes \"YOUR_NOTES\"' to approve."
                    )
                    self.state_manager.save_state(state)
                    raise HumanApprovalRequiredError(
                        f"Automated quality checks passed for production '{production_id}', but human approval "
                        "cannot be issued automatically during resumption. Explicit human review and authorization are mandatory."
                    )

                if not approver_notes or not approver_notes.strip():
                    raise HumanApprovalRequiredError(
                        f"Human approval confirmed for '{production_id}', but mandatory approver notes are missing."
                    )

                approval = self.create_human_approval(
                    package=package,
                    video_path=video_path,
                    script=script,
                    quality_report=quality_report,
                    approver_notes=approver_notes,
                    accept_warnings=accept_warnings,
                    storyboard_id=storyboard.storyboard_id,
                    storyboard=storyboard,
                )
            else:
                with open(app_file, "r", encoding="utf-8") as f:
                    approval = UploadApprovalRecord(**json.load(f))
                # Validate existing approval against tampering or expiration
                UploadApprovalGate.validate_approval(
                    approval=approval,
                    current_video_path=video_path,
                    current_metadata=self._build_upload_metadata(script, approval.requested_privacy),
                    current_script=script,
                    current_storyboard=storyboard,
                )

            # Upload Preparation
            self.prepare_upload_package(
                package=package,
                approval=approval,
                script=script,
                video_path=video_path,
                storyboard_id=storyboard.storyboard_id,
            )

            resumed_state = self.state_manager.get_state(production_id, storyboard.storyboard_id)
            return resumed_state or state

        finally:
            self.state_manager.release_lock(production_id)
