"""Video Assembly Engine orchestrating 9:16 Shorts composition and FFmpeg rendering."""

from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from config.settings import get_settings
from src.audio_engine.models import AudioMixResult, VoiceSynthesisResult
from src.common.logger import setup_logger
from src.image_engine.eligibility import ProductionEligibilityValidator
from src.image_engine.exceptions import (
    MockAssetProductionBlockedError,
    ProductionEligibilityBlockedError,
)
from src.image_engine.models import StoryboardImageManifest
from src.script_manager.models import Script
from src.storage_manager.models import ProductionAsset, ProductionAssetType, ProductionPackage
from src.storage_manager.service import StorageManager
from src.storyboard_generator.models import StoryboardDossier
from src.video_editor.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    VideoAssetMissingError,
    VideoCompositionError,
)
from src.video_editor.ffmpeg_runner import FFmpegRunner
from src.video_editor.filtergraph import FiltergraphBuilder
from src.video_editor.models import SceneClipSpec, VideoRenderResult, VideoRenderSettings

logger = setup_logger("video_assembly_engine")


class VideoAssemblyEngine:
    """Orchestrates video rendering for YouTube Shorts under strict production safeguards.

    ARCHITECTURAL SAFEGUARDS:
    1. Step 0 Eligibility Gate: Every render request MUST pass
       `ProductionEligibilityValidator.validate_for_video_production(...)`.
    2. Strict Mock Quarantine: Rejects any mock images, mock voice, or mock production assets.
    3. Zero-Cost Enforcement: Uses strictly local FFmpeg rendering. Cost is permanently ₹0.00.
    4. Memory Safety: Uses streaming FFmpeg filtergraphs optimized for 8 GB RAM laptops.
    5. Storage Integration: Automatically registers rendered videos into the ProductionPackage.
    """

    def __init__(
        self,
        render_settings: Optional[VideoRenderSettings] = None,
        ffmpeg_runner: Optional[FFmpegRunner] = None,
        storage_manager: Optional[StorageManager] = None,
    ):
        settings = get_settings().video
        self.settings = render_settings or VideoRenderSettings(
            width=settings.width,
            height=settings.height,
            fps=settings.fps,
            preset=settings.encoding_preset,
            crf=settings.crf,
            video_codec=settings.video_codec,
            audio_codec=settings.audio_codec,
            audio_bitrate=settings.audio_bitrate,
            pixel_format=settings.pixel_format,
            render_timeout_seconds=settings.render_timeout_seconds,
        )
        self.ffmpeg_runner = ffmpeg_runner or FFmpegRunner()
        self.storage_manager = storage_manager or StorageManager()
        self.filtergraph_builder = FiltergraphBuilder(render_settings=self.settings)

    def render_short_video(
        self,
        storyboard: StoryboardDossier,
        manifest: StoryboardImageManifest,
        script: Script,
        voice_result: VoiceSynthesisResult,
        production_package: ProductionPackage,
        mixed_audio_result: Optional[AudioMixResult] = None,
        ass_caption_path: Optional[Path] = None,
        custom_settings: Optional[VideoRenderSettings] = None,
    ) -> VideoRenderResult:
        """Render a vertical 9:16 YouTube Short from approved production assets.

        Args:
            storyboard: Fully verified storyboard dossier.
            manifest: Manifest containing 100% approved scene images.
            script: Approved script model.
            voice_result: Authentic voice synthesis result (is_mock_asset=False).
            production_package: Storage manager package tracking temporary production files.
            mixed_audio_result: Optional ducked BGM + SFX mixed audio.
            ass_caption_path: Optional stylized ASS subtitle file.
            custom_settings: Optional per-render encoding settings override.

        Returns:
            VideoRenderResult: Metadata and path to rendered MP4 video.

        Raises:
            ProductionEligibilityBlockedError: If scientific claims or script dialogue are unverified.
            MockAssetProductionBlockedError: If any visual or audio asset is a mock.
            ImageReviewRequiredError: If any image is unapproved.
            VideoAssetMissingError: If a required media file does not exist on disk.
            FFmpegNotFoundError: If FFmpeg executable is missing.
            FFmpegExecutionError: If FFmpeg encoding fails.
        """
        # =========================================================================
        # MANDATORY STEP 0: Strict Production Eligibility Gate
        # =========================================================================
        if not all([storyboard, manifest, script, voice_result, production_package]):
            raise ProductionEligibilityBlockedError(
                "MANDATORY PRODUCTION GATE FAILED: Video assembly requires all core production artifacts: "
                "script, storyboard, image manifest, voice result, and production package."
            )

        # Validate scientific integrity, approval states, and zero-mock invariant
        ProductionEligibilityValidator.validate_for_video_production(
            storyboard=storyboard,
            manifest=manifest,
            script=script,
            voice_result=voice_result,
            production_package=production_package,
        )

        # Validate mixed audio mock status if provided
        if mixed_audio_result and mixed_audio_result.is_mock_asset:
            raise MockAssetProductionBlockedError(
                "VIDEO PRODUCTION BLOCKED: Mixed audio asset is flagged as a MOCK asset. "
                "Mock audio must NEVER enter final video composition."
            )

        logger.info("Production eligibility gate passed for storyboard '%s'.", storyboard.storyboard_id)

        # =========================================================================
        # STEP 1: Verify Media Assets on Disk
        # =========================================================================
        # 1. Verify images on disk
        image_map: Dict[int, Path] = {}
        for img in manifest.images:
            p = Path(img.image_path).resolve()
            if not p.exists():
                raise VideoAssetMissingError(
                    f"Scene {img.scene_number} image file does not exist on disk: '{p}'"
                )
            image_map[img.scene_number] = p

        # 2. Verify primary audio file
        if mixed_audio_result and Path(mixed_audio_result.mixed_audio_path).resolve().exists():
            primary_audio = Path(mixed_audio_result.mixed_audio_path).resolve()
            total_audio_duration = mixed_audio_result.duration_seconds
        else:
            primary_audio = Path(voice_result.audio_path).resolve()
            total_audio_duration = voice_result.duration_seconds

        if not primary_audio.exists():
            raise VideoAssetMissingError(f"Primary audio file does not exist on disk: '{primary_audio}'")

        # 3. Verify captions if specified
        valid_caption_path = None
        if ass_caption_path:
            cap_p = Path(ass_caption_path).resolve()
            if not cap_p.exists():
                raise VideoAssetMissingError(f"ASS caption file does not exist on disk: '{cap_p}'")
            valid_caption_path = cap_p

        # =========================================================================
        # STEP 2: Verify FFmpeg Executable Availability
        # =========================================================================
        is_avail, version_info = self.ffmpeg_runner.check_ffmpeg_availability()
        if not is_avail:
            raise FFmpegNotFoundError(
                f"Video assembly blocked: {version_info}. "
                f"Please install FFmpeg and ensure it is available on system PATH."
            )

        # =========================================================================
        # STEP 3: Assemble Scene Clip Specifications
        # =========================================================================
        active_settings = custom_settings or self.settings
        builder = FiltergraphBuilder(render_settings=active_settings)

        scene_specs: List[SceneClipSpec] = []
        for s in storyboard.scenes:
            if s.scene_number not in image_map:
                raise VideoAssetMissingError(
                    f"Missing image mapping for scene {s.scene_number} in storyboard '{storyboard.storyboard_id}'."
                )

            # Camera movement from storyboard scene specification
            cam_move = getattr(s, "camera_movement", "static")
            if hasattr(cam_move, "value"):
                cam_move = cam_move.value

            transition = getattr(s, "transition_to_next", "hard-cut") or "hard-cut"

            scene_specs.append(
                SceneClipSpec(
                    scene_number=s.scene_number,
                    image_path=str(image_map[s.scene_number]),
                    duration_seconds=s.suggested_duration_seconds,
                    camera_movement=str(cam_move),
                    transition_to_next=str(transition),
                )
            )

        if not scene_specs:
            raise VideoCompositionError(
                f"Storyboard '{storyboard.storyboard_id}' contains zero scene specifications."
            )

        # =========================================================================
        # STEP 4: Output File Destination Inside Production Package
        # =========================================================================
        video_dir = Path(production_package.root_dir) / "video"
        video_dir.mkdir(parents=True, exist_ok=True)
        output_mp4 = video_dir / f"final_{storyboard.storyboard_id}.mp4"

        # =========================================================================
        # STEP 5: Build FFmpeg Command & Execute Subprocess
        # =========================================================================
        cmd_args = builder.build_full_command(
            scene_specs=scene_specs,
            audio_path=primary_audio,
            output_path=output_mp4,
            ass_caption_path=valid_caption_path,
        )

        logger.info(
            "Starting FFmpeg render for '%s' (Output: %s, Resolution: %dx%d, Preset: %s)...",
            storyboard.storyboard_id,
            output_mp4.name,
            active_settings.width,
            active_settings.height,
            getattr(active_settings, "preset", getattr(active_settings, "encoding_preset", "veryfast")),
        )

        proc, elapsed = self.ffmpeg_runner.run_ffmpeg(cmd_args, timeout=active_settings.render_timeout_seconds)

        # =========================================================================
        # STEP 6: Verify Rendered Output & Register Asset in StorageManager
        # =========================================================================
        if not output_mp4.exists() or output_mp4.stat().st_size == 0:
            raise FFmpegExecutionError(
                f"FFmpeg process reported completion but output file '{output_mp4.name}' is missing or 0 bytes."
            )

        output_size = output_mp4.stat().st_size
        logger.info(
            "Video render successful: '%s' (Size: %d bytes, Render Time: %.2fs)",
            output_mp4.name, output_size, elapsed
        )

        # Register final video asset with StorageManager
        asset = self.storage_manager.register_asset(
            production_id=production_package.production_id,
            asset_type=ProductionAssetType.FINAL_VIDEO,
            file_path=output_mp4,
            storyboard_id=storyboard.storyboard_id,
            is_mock_asset=False,
            metadata={
                "duration_seconds": total_audio_duration,
                "resolution": f"{active_settings.width}x{active_settings.height}",
                "fps": active_settings.fps,
                "render_duration_seconds": elapsed,
                "codec": active_settings.video_codec,
                "file_size_bytes": output_size,
            },
        )

        return VideoRenderResult(
            video_path=str(output_mp4),
            duration_seconds=total_audio_duration,
            resolution=f"{active_settings.width}x{active_settings.height}",
            fps=active_settings.fps,
            file_size_bytes=output_size,
            render_duration_seconds=elapsed,
            cost_usd=0.0,
            is_mock_asset=False,
            metadata={
                "asset_id": asset.asset_id,
                "production_id": production_package.production_id,
                "scenes_count": len(scene_specs),
                "audio_track": primary_audio.name,
                "burned_captions": valid_caption_path.name if valid_caption_path else None,
            },
        )
