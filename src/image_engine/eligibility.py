"""Strict Production Eligibility and Scientific Claim Verification Gate."""

from pathlib import Path
from typing import Any, List, Optional

from src.common.logger import setup_logger
from src.image_engine.exceptions import (
    ImageReviewRequiredError,
    MockAssetProductionBlockedError,
    ProductionEligibilityBlockedError,
)
from src.image_engine.models import SceneImageStatus, StoryboardImageManifest
from src.script_manager.models import Script, ScriptStatus
from src.storyboard_generator.models import StoryboardDossier

logger = setup_logger("eligibility_validator")


class ProductionEligibilityValidator:
    """Strict gatekeeper verifying that stories satisfy all factual and creative standards.

    CRITICAL RULES:
    1. Unverified scientific claims STRICTLY BLOCK production.
    2. No waivers or bypasses: unverified claims must be verified by a human or rewritten.
    3. Mock assets (images, voiceover, SFX) are strictly prohibited from entering video production.
    4. All scene images must be explicitly APPROVED by human review before video assembly.

    STAGE 7B ARCHITECTURAL MANDATE:
    Every future video rendering entry point (e.g. VideoAssemblyEngine.assemble_short_video)
    MUST invoke `ProductionEligibilityValidator.validate_for_video_production(...)` as its
    mandatory Step 0 before generating FFmpeg filtergraphs or executing any FFmpeg subprocesses.

    The validation gate MUST receive:
    - storyboard: StoryboardDossier (verified scientific claims)
    - manifest: StoryboardImageManifest (all scene images present and SceneImageStatus.APPROVED)
    - script: Optional[Script] (ScriptStatus.APPROVED if provided)
    - voice_result: Optional[VoiceSynthesisResult] (is_mock_asset=False)
    - production_package: Optional[ProductionPackage] (zero mock assets across all registered files)

    If any check fails, rendering MUST immediately abort with zero files passed to FFmpeg.
    """

    @classmethod
    def validate_for_image_generation(
        cls,
        storyboard: StoryboardDossier,
        script: Optional[Script] = None,
    ) -> None:
        """Verify that a storyboard is eligible to generate image assets.

        Requires:
        1. Script dialogue approval (if linked to a Script object).
        2. 100% human verification of all scientific claims (NO UNVERIFIED CLAIMS).
        """
        # 1. Script status check (if script is provided)
        if script is not None:
            if script.status != ScriptStatus.APPROVED:
                msg = (
                    f"PRODUCTION BLOCKED: Script '{script.id}' status is '{script.status.value}'. "
                    f"Script dialogue must be human-approved before image generation can begin."
                )
                logger.warning(msg)
                raise ProductionEligibilityBlockedError(msg)

        # 2. Strict scientific claim verification check (NO WAIVERS ALLOWED)
        unverified_claims: List[str] = []

        for claim_obj in storyboard.scientific_claims:
            if not claim_obj.is_verified:
                unverified_claims.append(f"'{claim_obj.claim}' (Source: {claim_obj.source_title})")

        if storyboard.has_unverified_claims or unverified_claims:
            msg = (
                f"PRODUCTION BLOCKED: Storyboard '{storyboard.storyboard_id}' contains "
                f"{len(unverified_claims)} unverified scientific claim(s). "
                f"Under strict integrity guidelines, image generation cannot proceed until all factual assertions "
                f"are independently verified by a human reviewer or removed/rewritten. "
                f"Unverified claims: {unverified_claims}"
            )
            logger.critical(msg)
            raise ProductionEligibilityBlockedError(msg)

        logger.info(
            "Production eligibility verified for image generation on storyboard '%s'.",
            storyboard.storyboard_id,
        )

    @classmethod
    def validate_audio_for_production(cls, voice_result: Any) -> None:
        """Verify that voiceover audio is authentic, not a mock asset, and passed human listening."""
        if getattr(voice_result, "is_mock_asset", False):
            msg = (
                f"VIDEO PRODUCTION BLOCKED: Voice synthesis asset is a MOCK asset "
                f"(provider: {getattr(voice_result, 'provider', 'unknown')}). "
                f"Mock audio is for testing only and must NEVER be used in final video composition."
            )
            logger.critical(msg)
            raise MockAssetProductionBlockedError(msg)

        lifecycle = getattr(voice_result, "lifecycle_status", None)
        if lifecycle in ["HUMAN_LISTENING_FAILED", "REJECTED"]:
            msg = (
                f"VIDEO PRODUCTION BLOCKED: Voice synthesis asset failed human listening evaluation "
                f"(lifecycle status: '{lifecycle}'). Voices that failed human listening cannot enter video production."
            )
            logger.critical(msg)
            raise ProductionEligibilityBlockedError(msg)

    @classmethod
    def validate_for_video_production(
        cls,
        storyboard: StoryboardDossier,
        manifest: StoryboardImageManifest,
        script: Optional[Script] = None,
        voice_result: Optional[Any] = None,
        production_package: Optional[Any] = None,
        min_distinct_images: Optional[int] = None,
    ) -> None:
        """Verify that visual assets are 100% approved and ready for video composition.

        Requires:
        1. Prior scientific claim verification must still hold.
        2. Zero mock assets (Mocks are permanently forbidden in video assembly).
        3. Every scene in the storyboard must have a corresponding image.
        4. Every scene image must be in SceneImageStatus.APPROVED status.
        5. Zero mock audio assets (Voice and SFX).
        """
        # Re-verify scientific claims first
        cls.validate_for_image_generation(storyboard, script=script)

        # Enforce zero mock visual assets
        if manifest.has_mock_assets or any(img.is_mock_asset for img in manifest.images):
            msg = (
                f"VIDEO PRODUCTION BLOCKED: Storyboard '{storyboard.storyboard_id}' contains MOCK assets. "
                f"Mock images are for testing and structural validation only and must NEVER be used in "
                f"final video composition."
            )
            logger.critical(msg)
            raise MockAssetProductionBlockedError(msg)

        # Enforce zero mock voice audio assets
        if voice_result is not None:
            cls.validate_audio_for_production(voice_result)

        # Enforce zero mock assets in production package
        if production_package is not None:
            for asset in getattr(production_package, "assets", []):
                if getattr(asset, "is_mock_asset", False):
                    msg = (
                        f"VIDEO PRODUCTION BLOCKED: Production package '{getattr(production_package, 'production_id', 'unknown')}' "
                        f"contains MOCK asset '{asset.asset_id}' ({getattr(asset.asset_type, 'value', str(asset.asset_type))}). "
                        f"Mock assets must NEVER be used in final video composition."
                    )
                    logger.critical(msg)
                    raise MockAssetProductionBlockedError(msg)

        # Enforce full scene coverage
        expected_scenes = len(storyboard.scenes)
        actual_scenes = len(manifest.images)
        if actual_scenes < expected_scenes:
            msg = (
                f"VIDEO PRODUCTION BLOCKED: Incomplete visual assets for '{storyboard.storyboard_id}'. "
                f"Expected {expected_scenes} scenes, but manifest only contains {actual_scenes}."
            )
            logger.error(msg)
            raise ProductionEligibilityBlockedError(msg)

        # Enforce human review approval for every individual image
        for img in manifest.images:
            if img.status != SceneImageStatus.APPROVED:
                msg = (
                    f"VIDEO PRODUCTION BLOCKED: Scene {img.scene_number} image is in '{img.status.value}' status. "
                    f"Every scene image requires explicit human approval before video assembly."
                )
                logger.error(msg)
                raise ImageReviewRequiredError(msg)

        # Enforce distinct images if specified
        if min_distinct_images is not None:
            cls.validate_minimum_distinct_images(manifest, min_distinct_images=min_distinct_images)

        logger.info(
            "Video production eligibility verified for storyboard '%s': All %d images approved and production-ready.",
            storyboard.storyboard_id,
            len(manifest.images),
        )

    @classmethod
    def validate_minimum_distinct_images(
        cls,
        manifest: StoryboardImageManifest,
        min_distinct_images: int = 10,
    ) -> int:
        """Verify that a production package contains at least `min_distinct_images` genuinely distinct assets.

        CRITICAL ENFORCEMENT:
        - Must contain at least 10 genuinely distinct image assets for a 30-60s Short.
        - Repeated copies, duplicate file paths, or identical image hashes are NOT counted.
        - Zooms, crops, overlays, text changes, or filters of the same image do NOT count as distinct images.
        """
        if not manifest or not manifest.images:
            raise ProductionEligibilityBlockedError("Production manifest contains zero images.")

        seen_hashes = set()
        seen_paths = set()
        distinct_count = 0

        for img in manifest.images:
            img_path = str(Path(img.image_path).resolve()) if img.image_path else ""
            h = img.file_hash.strip().lower() if img.file_hash else ""
            if not h and img.image_path and Path(img.image_path).exists():
                import hashlib
                with open(img.image_path, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()

            # Unique key is hash if available, or path
            dedup_key = h if h else img_path
            if dedup_key and dedup_key not in seen_hashes and img_path not in seen_paths:
                seen_hashes.add(dedup_key)
                if img_path:
                    seen_paths.add(img_path)
                distinct_count += 1

        if distinct_count < min_distinct_images:
            msg = (
                f"VIDEO PRODUCTION BLOCKED: Production Short requires at least {min_distinct_images} "
                f"genuinely distinct visual images (found {distinct_count} distinct assets out of {len(manifest.images)} scenes). "
                f"Repeated images, duplicate crops, or identical image hashes do not satisfy this requirement."
            )
            logger.error(msg)
            raise ProductionEligibilityBlockedError(msg)

        logger.info(
            "Distinct image requirement verified: %d unique image assets (threshold: %d).",
            distinct_count,
            min_distinct_images,
        )
        return distinct_count
