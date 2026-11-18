"""Image Generation Engine orchestrator coordinating eligibility, generation, review, and manifests."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Dict, Optional

from config.settings import get_settings
from src.common.logger import setup_logger
from src.image_engine.cost_guard import CostSafetyGuard
from src.image_engine.eligibility import ProductionEligibilityValidator
from src.image_engine.exceptions import (
    ImageEngineError,
    ImageReviewRequiredError,
    ProductionEligibilityBlockedError,
)
from src.image_engine.models import (
    GeneratedImageMetadata,
    SceneImageStatus,
    StoryboardImageManifest,
)
from src.image_engine.prompts import build_scene_image_prompt
from src.image_engine.providers.base import BaseImageProvider
from src.image_engine.providers.mock_provider import PillowMockImageProvider
from src.script_manager.models import Script
from src.storyboard_generator.models import StoryboardDossier

logger = setup_logger("image_engine")


class ImageGenerationEngine:
    """Primary orchestrator managing image asset lifecycle for YouTube Shorts."""

    def __init__(
        self,
        provider: Optional[BaseImageProvider] = None,
        base_output_dir: Optional[Path] = None,
    ):
        settings = get_settings()
        self.settings = settings
        self.provider = provider or PillowMockImageProvider()
        self.base_output_dir = Path(base_output_dir) if base_output_dir else settings.paths.images_output_dir
        self.base_output_dir.mkdir(parents=True, exist_ok=True)

        # Enforce cost safety policy on initialization
        CostSafetyGuard.assert_zero_cost_provider(self.provider.provider_name)
        logger.info("ImageGenerationEngine initialized with provider '%s'.", self.provider.provider_name)

    def _get_storyboard_dir(self, storyboard_id: str) -> Path:
        """Return dedicated project directory for storyboard images."""
        folder = self.base_output_dir / storyboard_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _get_manifest_path(self, storyboard_id: str) -> Path:
        """Return path to manifest JSON file."""
        return self._get_storyboard_dir(storyboard_id) / "manifest.json"

    def get_manifest(self, storyboard_id: str) -> Optional[StoryboardImageManifest]:
        """Load manifest from disk if it exists."""
        path = self._get_manifest_path(storyboard_id)
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return StoryboardImageManifest(**data)

    def _save_manifest(self, manifest: StoryboardImageManifest) -> None:
        """Persist manifest JSON to disk."""
        path = self._get_manifest_path(manifest.storyboard_id)
        with open(path, "w", encoding="utf-8") as f:
            f.write(manifest.model_dump_json(indent=2))

    def generate_scene_image(
        self,
        storyboard: StoryboardDossier,
        scene_number: int,
        script: Optional[Script] = None,
        prompt_override: Optional[str] = None,
        negative_override: Optional[str] = None,
    ) -> GeneratedImageMetadata:
        """Generate an image for a specific scene after enforcing scientific verification."""
        # 1. Enforce strict scientific eligibility
        ProductionEligibilityValidator.validate_for_image_generation(storyboard, script=script)

        # 2. Locate scene
        scene = next((s for s in storyboard.scenes if s.scene_number == scene_number), None)
        if not scene:
            raise ImageEngineError(f"Scene {scene_number} not found in storyboard '{storyboard.storyboard_id}'.")

        # 3. Synthesize prompts
        pos_prompt, neg_prompt = build_scene_image_prompt(storyboard.visual_consistency, scene)
        if prompt_override:
            pos_prompt = prompt_override
        if negative_override:
            neg_prompt = negative_override

        # 4. Prepare file paths
        sb_dir = self._get_storyboard_dir(storyboard.storyboard_id)
        output_file = sb_dir / f"scene_{scene_number:02d}.png"
        thumb_file = sb_dir / f"scene_{scene_number:02d}_thumb.jpg"

        # Archive prior version if regenerating
        if output_file.exists():
            history_dir = sb_dir / "history"
            history_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            archive_file = history_dir / f"scene_{scene_number:02d}_{timestamp}.png"
            shutil.copy2(output_file, archive_file)
            logger.info("Archived prior version of scene %d to '%s'.", scene_number, archive_file.name)

        # 5. Invoke Provider
        metadata = self.provider.generate_scene_image(
            scene_number=scene_number,
            positive_prompt=pos_prompt,
            negative_prompt=neg_prompt,
            output_path=output_file,
            thumbnail_path=thumb_file,
            width=self.settings.image_engine.width,
            height=self.settings.image_engine.height,
            reference_image=storyboard.visual_consistency.character_reference_image,
        )

        # 6. Verify zero-cost compliance on output
        CostSafetyGuard.verify_generation_cost(metadata.cost_usd, self.provider.provider_name)

        # 7. Update and persist manifest
        manifest = self.get_manifest(storyboard.storyboard_id)
        if not manifest:
            manifest = StoryboardImageManifest(
                storyboard_id=storyboard.storyboard_id,
                provider=self.provider.provider_name,
                total_scenes=len(storyboard.scenes),
                images=[],
            )

        manifest.upsert_image(metadata)
        self._save_manifest(manifest)

        logger.info(
            "Scene %d image successfully registered in manifest for '%s' (Status: %s, Mock: %s).",
            scene_number, storyboard.storyboard_id, metadata.status.value, metadata.is_mock_asset
        )
        return metadata

    def generate_storyboard_images(
        self,
        storyboard: StoryboardDossier,
        script: Optional[Script] = None,
    ) -> StoryboardImageManifest:
        """Generate images for all scenes in the storyboard sequentially."""
        logger.info(
            "Starting storyboard image generation for '%s' (%d scenes)...",
            storyboard.storyboard_id, len(storyboard.scenes)
        )

        # Upfront eligibility check
        ProductionEligibilityValidator.validate_for_image_generation(storyboard, script=script)

        for scene in storyboard.scenes:
            self.generate_scene_image(
                storyboard=storyboard,
                scene_number=scene.scene_number,
                script=script,
            )

        manifest = self.get_manifest(storyboard.storyboard_id)
        if not manifest:
            raise ImageEngineError(f"Failed to generate manifest for '{storyboard.storyboard_id}'.")

        logger.info(
            "Completed batch generation for '%s': %d scene image(s) created (All Approved: %s).",
            storyboard.storyboard_id, len(manifest.images), manifest.all_approved
        )
        return manifest

    def regenerate_scene_image(
        self,
        storyboard: StoryboardDossier,
        scene_number: int,
        script: Optional[Script] = None,
        prompt_override: Optional[str] = None,
        negative_override: Optional[str] = None,
    ) -> GeneratedImageMetadata:
        """Regenerate a single scene image, preserving all other scenes in the manifest."""
        logger.info("Regenerating scene %d for storyboard '%s'...", scene_number, storyboard.storyboard_id)
        return self.generate_scene_image(
            storyboard=storyboard,
            scene_number=scene_number,
            script=script,
            prompt_override=prompt_override,
            negative_override=negative_override,
        )

    # --- Manual Production Image Import Workflow ---

    def import_scene_image(
        self,
        storyboard: StoryboardDossier,
        scene_number: int,
        source_image_path: Path,
        reviewer_notes: Optional[str] = None,
        auto_approve: bool = False,
    ) -> GeneratedImageMetadata:
        """Import an externally created image for a scene (e.g. from free AI tools).

        Validates:
        - Source file exists and is non-empty.
        - Image format is valid (PNG, JPEG, WEBP) using PIL.
        - Orientation is vertical 9:16 (height > width).
        - Resizes to standard 1080x1920 if necessary.
        - Generates preview thumbnail.
        - Computes SHA-256 hash.
        - Registers asset in StoryboardImageManifest with is_mock_asset=False, cost_usd=0.0.
        """
        source_path = Path(source_image_path).resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source image file not found: {source_path}")

        scene = next((s for s in storyboard.scenes if s.scene_number == scene_number), None)
        if not scene:
            raise ImageEngineError(f"Scene {scene_number} not found in storyboard '{storyboard.storyboard_id}'.")

        from PIL import Image

        sb_dir = self._get_storyboard_dir(storyboard.storyboard_id)
        output_file = sb_dir / f"scene_{scene_number:02d}.png"
        thumb_file = sb_dir / f"scene_{scene_number:02d}_thumb.jpg"
        target_w = self.settings.image_engine.width
        target_h = self.settings.image_engine.height

        try:
            with Image.open(source_path) as img:
                width, height = img.size

                if height <= width:
                    raise ImageEngineError(
                        f"Image for scene {scene_number} is horizontal or square ({width}x{height}). "
                        "Vertical 9:16 orientation (height > width) is required for Shorts."
                    )

                if (width, height) != (target_w, target_h):
                    resized = img.resize((target_w, target_h), Image.Resampling.LANCZOS)
                    resized.convert("RGB").save(output_file, format="PNG")
                else:
                    img.convert("RGB").save(output_file, format="PNG")

                thumb = img.copy()
                thumb.thumbnail((270, 480), Image.Resampling.LANCZOS)
                thumb.convert("RGB").save(thumb_file, format="JPEG", quality=85)

        except Exception as e:
            if isinstance(e, ImageEngineError):
                raise
            raise ImageEngineError(f"Failed to process and validate image '{source_path}': {e}") from e

        file_size = output_file.stat().st_size
        with open(output_file, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()

        pos_prompt, neg_prompt = build_scene_image_prompt(storyboard.visual_consistency, scene)
        status = SceneImageStatus.APPROVED if auto_approve else SceneImageStatus.PENDING_IMAGE_REVIEW

        metadata = GeneratedImageMetadata(
            scene_number=scene_number,
            image_path=str(output_file),
            thumbnail_path=str(thumb_file),
            provider="manual_import",
            model_id="external_free_tool",
            prompt_used=pos_prompt,
            negative_prompt_used=neg_prompt,
            width=target_w,
            height=target_h,
            aspect_ratio="9:16",
            file_hash=file_hash,
            file_size_bytes=file_size,
            is_mock_asset=False,  # CRITICAL: Real production asset
            cost_usd=0.0,
            status=status,
            reviewer_notes=reviewer_notes or ("Imported real asset" if not auto_approve else "Imported and approved"),
            approved_at=datetime.now(timezone.utc) if auto_approve else None,
            generated_at=datetime.now(timezone.utc),
            metadata={"source_file": str(source_path), "original_dimensions": f"{width}x{height}"},
        )

        manifest = self.get_manifest(storyboard.storyboard_id)
        if not manifest:
            manifest = StoryboardImageManifest(
                storyboard_id=storyboard.storyboard_id,
                provider="manual_import",
                total_scenes=len(storyboard.scenes),
                images=[],
            )

        manifest.upsert_image(metadata)
        self._save_manifest(manifest)
        logger.info(
            "Imported scene %d image for '%s' from '%s' (Mock: False, Status: %s)",
            scene_number, storyboard.storyboard_id, source_path.name, metadata.status.value
        )
        return metadata

    def import_storyboard_images(
        self,
        storyboard: StoryboardDossier,
        image_mapping: Dict[int, Path],
        auto_approve: bool = False,
    ) -> StoryboardImageManifest:
        """Batch import externally generated images for multiple or all scenes in a storyboard."""
        for scene_num, img_path in sorted(image_mapping.items()):
            self.import_scene_image(
                storyboard=storyboard,
                scene_number=scene_num,
                source_image_path=img_path,
                auto_approve=auto_approve,
            )

        manifest = self.get_manifest(storyboard.storyboard_id)
        if not manifest:
            raise ImageEngineError(f"Failed to generate manifest for '{storyboard.storyboard_id}'.")
        return manifest

    # --- Human Review & Approval Workflow ---

    def approve_scene_image(
        self,
        storyboard_id: str,
        scene_number: int,
        notes: Optional[str] = None,
    ) -> GeneratedImageMetadata:
        """Approve an individual scene image after human inspection."""
        manifest = self.get_manifest(storyboard_id)
        if not manifest:
            raise ImageEngineError(f"No manifest found for storyboard '{storyboard_id}'.")

        approved_img = manifest.approve_scene(scene_number, notes=notes)
        self._save_manifest(manifest)
        logger.info("Human approval recorded for scene %d of storyboard '%s'.", scene_number, storyboard_id)
        return approved_img

    def reject_scene_image(
        self,
        storyboard_id: str,
        scene_number: int,
        reason: str,
    ) -> GeneratedImageMetadata:
        """Reject an individual scene image, signaling that regeneration is required."""
        manifest = self.get_manifest(storyboard_id)
        if not manifest:
            raise ImageEngineError(f"No manifest found for storyboard '{storyboard_id}'.")

        rejected_img = manifest.reject_scene(scene_number, reason=reason)
        self._save_manifest(manifest)
        logger.info("Rejection recorded for scene %d of storyboard '%s': %s", scene_number, storyboard_id, reason)
        return rejected_img

    def approve_all_images(
        self,
        storyboard_id: str,
        notes: Optional[str] = None,
    ) -> StoryboardImageManifest:
        """Approve all images in the storyboard manifest in one step."""
        manifest = self.get_manifest(storyboard_id)
        if not manifest:
            raise ImageEngineError(f"No manifest found for storyboard '{storyboard_id}'.")

        manifest.approve_all(notes=notes)
        self._save_manifest(manifest)
        logger.info("All %d images approved for storyboard '%s'.", len(manifest.images), storyboard_id)
        return manifest

    def validate_ready_for_video(
        self,
        storyboard: StoryboardDossier,
        script: Optional[Script] = None,
    ) -> None:
        """Verify that visual assets are completely verified, approved, and ready for video rendering.

        Raises:
            ProductionEligibilityBlockedError: If scientific claims are unverified or scenes are missing.
            MockAssetProductionBlockedError: If any asset is a mock.
            ImageReviewRequiredError: If any image is unapproved or rejected.
        """
        manifest = self.get_manifest(storyboard.storyboard_id)
        if not manifest:
            raise ProductionEligibilityBlockedError(
                f"No visual manifest found for storyboard '{storyboard.storyboard_id}'. "
                f"Images must be generated before video production."
            )

        ProductionEligibilityValidator.validate_for_video_production(
            storyboard=storyboard,
            manifest=manifest,
            script=script,
        )
