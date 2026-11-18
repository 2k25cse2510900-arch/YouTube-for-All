"""Automated test suite for Image Generation Engine, CostSafetyGuard, and Production Eligibility."""

from pathlib import Path
import pytest
from PIL import Image

from src.image_engine.cost_guard import CostSafetyGuard
from src.image_engine.eligibility import ProductionEligibilityValidator
from src.image_engine.exceptions import (
    CostSafetyViolationError,
    DisabledProviderError,
    ImageEngineError,
    ImageReviewRequiredError,
    MockAssetProductionBlockedError,
    ProductionEligibilityBlockedError,
)
from src.image_engine.models import (
    GeneratedImageMetadata,
    ImageResolution,
    SceneImageStatus,
    StoryboardImageManifest,
)
from src.image_engine.prompts import build_scene_image_prompt
from src.image_engine.providers.disabled_stubs import (
    DisabledLocalGPUProvider,
    DisabledPaidProviderStub,
)
from src.image_engine.providers.mock_provider import PillowMockImageProvider
from src.image_engine.service import ImageGenerationEngine
from src.research_engine.models import SourceType, VerificationStatus
from src.script_manager.models import Script, ScriptStatus
from src.storyboard_generator.models import (
    CameraMovement,
    ScientificClaimVerification,
    StoryboardDossier,
    StoryboardScene,
    VisualConsistencyProfile,
)


@pytest.fixture
def sample_vc():
    """Sample VisualConsistencyProfile fixture."""
    return VisualConsistencyProfile(
        character_name="Senku Ishigami",
        facial_features="Sharp crimson eyes, confident smirk",
        hairstyle="Spiky green-to-white gradient hair",
        clothing_and_attire="Science tunic with E=mc2",
        color_palette="Emerald green, stone grey, neon accents",
        art_direction="Modern cinematic high-contrast anime, vertical 9:16",
        negative_prompt="distorted anatomy, extra limbs, low resolution, blurry",
        aspect_ratio="9:16",
    )


@pytest.fixture
def sample_scenes():
    """Sample StoryboardScene list fixture."""
    return [
        StoryboardScene(
            scene_number=1,
            narration_hinglish="Kya aap 3,700 saal tak jaag sakte hain?",
            narration_english_meaning="Can you stay awake for 3,700 years?",
            camera_angle="eye-level",
            framing="medium-close-up",
            subject_placement="center-weighted for vertical 9:16",
            image_prompt_positive="Senku stone statue cracking with glowing red eyes",
            image_prompt_negative="blurry, distorted face",
            suggested_duration_seconds=20.0,
            camera_movement=CameraMovement.SLOW_ZOOM_IN,
        ),
        StoryboardScene(
            scene_number=2,
            narration_hinglish="Real science kehta hai continuous metabolic energy chahiye.",
            narration_english_meaning="Real science says continuous metabolic energy is required.",
            camera_angle="high-angle",
            framing="medium-shot",
            subject_placement="center-weighted for vertical 9:16",
            image_prompt_positive="Glowing human brain MRI scan showing synaptic firing",
            image_prompt_negative="blurry, cartoonish",
            suggested_duration_seconds=23.0,
            camera_movement=CameraMovement.STATIC_DRIFT,
        ),
    ]


@pytest.fixture
def sample_storyboard(sample_vc, sample_scenes):
    """Sample StoryboardDossier fixture with verified claims."""
    claim = ScientificClaimVerification(
        claim="Conscious perception requires continuous metabolic glucose consumption in the cortex.",
        source_title="Principles of Neural Science",
        source_type=SourceType.BOOK,
        verification_status=VerificationStatus.HUMAN_CHECKED,
        is_verified=True,
        human_reviewer_notes="Verified via Kandel textbook Chapter 14",
    )
    return StoryboardDossier(
        storyboard_id="sb_anime_test_senku",
        title="Senku Time Perception Science",
        topic="Time Perception in Stasis",
        target_duration_seconds=45.0,
        pause_budget_seconds=2.0,
        hook="Hook text",
        body="Body text",
        takeaway="Takeaway text",
        visual_consistency=sample_vc,
        scenes=sample_scenes,
        scientific_claims=[claim],
    )


# --- 1. CostSafetyGuard Tests ---

def test_cost_guard_blocks_all_paid_providers():
    """Verify that any paid provider triggers an immediate hard block."""
    paid_providers = [
        "google_imagen", "imagen", "gemini_image", "replicate",
        "fal", "fal_ai", "openai", "dalle", "midjourney", "stability",
        "pollinations", "pollinations_ai",
    ]
    for p in paid_providers:
        with pytest.raises(CostSafetyViolationError) as exc:
            CostSafetyGuard.assert_zero_cost_provider(p)
        assert "paid or external service" in str(exc.value)


def test_cost_guard_allows_verified_free_providers():
    """Verify that permitted free providers pass inspection."""
    CostSafetyGuard.assert_zero_cost_provider("mock_pillow")
    CostSafetyGuard.assert_zero_cost_provider("disabled_local_gpu")


def test_cost_guard_blocks_nonzero_cost():
    """Verify that any generation cost > $0.00 raises CostSafetyViolationError."""
    with pytest.raises(CostSafetyViolationError) as exc:
        CostSafetyGuard.verify_generation_cost(0.0001, "mock_pillow")
    assert "non-zero cost" in str(exc.value)

    # $0.00 passes cleanly
    CostSafetyGuard.verify_generation_cost(0.0, "mock_pillow")


def test_cost_guard_blocks_fallback_to_paid():
    """Verify that fallback to paid providers is strictly blocked."""
    with pytest.raises(CostSafetyViolationError) as exc:
        CostSafetyGuard.assert_no_fallback_to_paid("mock_pillow", "replicate")
    assert "strictly forbidden" in str(exc.value)


# --- 2. Production Eligibility Gate Tests ---

def test_unverified_claims_strictly_block_image_generation(sample_vc, sample_scenes):
    """Verify that unverified scientific claims raise ProductionEligibilityBlockedError (NO WAIVERS)."""
    unverified_claim = ScientificClaimVerification(
        claim="Brain remains perfectly conscious without oxygen for centuries.",
        source_title="Unverified Proposal",
        source_type=SourceType.UNVERIFIED_PROPOSAL,
        verification_status=VerificationStatus.UNVERIFIED,
        is_verified=False,
    )
    storyboard = StoryboardDossier(
        storyboard_id="sb_unverified_test",
        title="Unverified Topic",
        topic="Petrification",
        target_duration_seconds=45.0,
        pause_budget_seconds=2.0,
        hook="Hook",
        body="Body",
        takeaway="Takeaway",
        visual_consistency=sample_vc,
        scenes=sample_scenes,
        scientific_claims=[unverified_claim],
    )

    with pytest.raises(ProductionEligibilityBlockedError) as exc:
        ProductionEligibilityValidator.validate_for_image_generation(storyboard)
    assert "unverified scientific claim" in str(exc.value)
    assert "Principles of Neural Science" not in str(exc.value)


def test_verified_claims_allow_image_generation(sample_storyboard):
    """Verify that fully human-verified claims pass production eligibility."""
    # Should not raise any error
    ProductionEligibilityValidator.validate_for_image_generation(sample_storyboard)


def test_unapproved_script_blocks_image_generation(sample_storyboard):
    """Verify that an unapproved Script linked to storyboard blocks image generation."""
    unapproved_script = Script(
        id=sample_storyboard.storyboard_id,
        title=sample_storyboard.title,
        category="anime_science",
        hook="Hook",
        body="Body",
        takeaway="Takeaway",
        status=ScriptStatus.PENDING_REVIEW,
    )

    with pytest.raises(ProductionEligibilityBlockedError) as exc:
        ProductionEligibilityValidator.validate_for_image_generation(
            sample_storyboard, script=unapproved_script
        )
    assert "must be human-approved" in str(exc.value)


# --- 3. Mock Asset Video Blocker Tests ---

def test_mock_assets_strictly_blocked_from_video_production(sample_storyboard, tmp_path):
    """Verify that any mock asset in the manifest blocks video production assembly."""
    manifest = StoryboardImageManifest(
        storyboard_id=sample_storyboard.storyboard_id,
        provider="mock_pillow",
        total_scenes=2,
        images=[
            GeneratedImageMetadata(
                scene_number=1,
                image_path=str(tmp_path / "scene_01.png"),
                provider="mock_pillow",
                prompt_used="prompt",
                is_mock_asset=True,  # Mock asset flag
                status=SceneImageStatus.APPROVED,
            ),
            GeneratedImageMetadata(
                scene_number=2,
                image_path=str(tmp_path / "scene_02.png"),
                provider="mock_pillow",
                prompt_used="prompt",
                is_mock_asset=True,  # Mock asset flag
                status=SceneImageStatus.APPROVED,
            ),
        ],
    )

    # Even though all images are marked APPROVED, mock assets MUST be blocked
    with pytest.raises(MockAssetProductionBlockedError) as exc:
        ProductionEligibilityValidator.validate_for_video_production(sample_storyboard, manifest)
    assert "contains MOCK assets" in str(exc.value)


def test_unapproved_images_block_video_production(sample_storyboard, tmp_path):
    """Verify that images in PENDING_IMAGE_REVIEW or REJECTED status block video production."""
    manifest = StoryboardImageManifest(
        storyboard_id=sample_storyboard.storyboard_id,
        provider="future_free_local",
        total_scenes=2,
        images=[
            GeneratedImageMetadata(
                scene_number=1,
                image_path=str(tmp_path / "scene_01.png"),
                provider="future_free_local",
                prompt_used="prompt",
                is_mock_asset=False,
                status=SceneImageStatus.APPROVED,
            ),
            GeneratedImageMetadata(
                scene_number=2,
                image_path=str(tmp_path / "scene_02.png"),
                provider="future_free_local",
                prompt_used="prompt",
                is_mock_asset=False,
                status=SceneImageStatus.PENDING_IMAGE_REVIEW,  # Not approved yet
            ),
        ],
    )

    with pytest.raises(ImageReviewRequiredError) as exc:
        ProductionEligibilityValidator.validate_for_video_production(sample_storyboard, manifest)
    assert "requires explicit human approval" in str(exc.value)


# --- 4. Pillow Mock Provider & 9:16 Vertical Formatting Tests ---

def test_pillow_mock_provider_generates_valid_vertical_image(tmp_path):
    """Verify that PillowMockImageProvider produces exact 1080x1920 9:16 images with watermark."""
    provider = PillowMockImageProvider()
    out_file = tmp_path / "scene_01.png"
    thumb_file = tmp_path / "scene_01_thumb.jpg"

    meta = provider.generate_scene_image(
        scene_number=1,
        positive_prompt="Anime test prompt with high detail",
        negative_prompt="blurry, distorted",
        output_path=out_file,
        thumbnail_path=thumb_file,
        width=1080,
        height=1920,
    )

    # 1. Output file exists
    assert out_file.exists()
    assert thumb_file.exists()

    # 2. Dimensions are exact 1080x1920
    with Image.open(out_file) as img:
        assert img.size == (1080, 1920)

    with Image.open(thumb_file) as thumb:
        assert thumb.size == (270, 480)

    # 3. Metadata flags
    assert meta.is_mock_asset is True
    assert meta.cost_usd == 0.0
    assert meta.status == SceneImageStatus.PENDING_IMAGE_REVIEW
    assert meta.file_hash != ""
    assert meta.aspect_ratio == "9:16"


def test_disabled_providers_raise_error():
    """Verify that disabled provider stubs refuse execution."""
    p1 = DisabledLocalGPUProvider()
    with pytest.raises(DisabledProviderError) as exc:
        p1.generate_scene_image(1, "prompt", "neg", Path("out.png"))
    assert "INACTIVE" in str(exc.value)

    p2 = DisabledPaidProviderStub()
    with pytest.raises(DisabledProviderError) as exc:
        p2.generate_scene_image(1, "prompt", "neg", Path("out.png"))
    assert "permanently blocked" in str(exc.value)


# --- 5. ImageGenerationEngine Orchestration & Single Scene Regeneration Tests ---

def test_engine_single_scene_generation_and_manifest(sample_storyboard, tmp_path):
    """Verify that ImageGenerationEngine generates a single scene, creates manifest, and saves metadata."""
    engine = ImageGenerationEngine(base_output_dir=tmp_path / "images")

    meta = engine.generate_scene_image(storyboard=sample_storyboard, scene_number=1)

    assert meta.scene_number == 1
    assert meta.is_mock_asset is True
    assert meta.status == SceneImageStatus.PENDING_IMAGE_REVIEW

    manifest = engine.get_manifest(sample_storyboard.storyboard_id)
    assert manifest is not None
    assert len(manifest.images) == 1
    assert manifest.get_image(1) is not None
    assert manifest.all_approved is False
    assert manifest.has_mock_assets is True


def test_engine_single_scene_regeneration_preserves_other_scenes(sample_storyboard, tmp_path):
    """Verify that regenerating Scene 1 archives previous version and preserves Scene 2."""
    engine = ImageGenerationEngine(base_output_dir=tmp_path / "images")

    # Generate scene 1 and scene 2
    engine.generate_scene_image(storyboard=sample_storyboard, scene_number=1)
    engine.generate_scene_image(storyboard=sample_storyboard, scene_number=2)

    manifest_before = engine.get_manifest(sample_storyboard.storyboard_id)
    assert len(manifest_before.images) == 2
    hash_s2_before = manifest_before.get_image(2).file_hash

    # Regenerate scene 1 with prompt override
    new_meta1 = engine.regenerate_scene_image(
        storyboard=sample_storyboard,
        scene_number=1,
        prompt_override="Custom regenerated prompt for Scene 1",
    )

    manifest_after = engine.get_manifest(sample_storyboard.storyboard_id)
    assert len(manifest_after.images) == 2
    # Scene 2 was untouched
    assert manifest_after.get_image(2).file_hash == hash_s2_before
    # Scene 1 prompt updated
    assert new_meta1.prompt_used == "Custom regenerated prompt for Scene 1"

    # Verify history archive was created
    history_dir = tmp_path / "images" / sample_storyboard.storyboard_id / "history"
    assert history_dir.exists()
    assert len(list(history_dir.iterdir())) >= 1


# --- 6. Human Review & Approval Workflow Tests ---

def test_human_review_workflow_and_all_approved_flag(sample_storyboard, tmp_path):
    """Verify approving scene images updates manifest and sets all_approved."""
    engine = ImageGenerationEngine(base_output_dir=tmp_path / "images")

    engine.generate_scene_image(storyboard=sample_storyboard, scene_number=1)
    engine.generate_scene_image(storyboard=sample_storyboard, scene_number=2)

    # Initially pending review
    manifest = engine.get_manifest(sample_storyboard.storyboard_id)
    assert manifest.all_approved is False

    # Approve scene 1
    engine.approve_scene_image(sample_storyboard.storyboard_id, scene_number=1, notes="Looks good")
    manifest = engine.get_manifest(sample_storyboard.storyboard_id)
    assert manifest.get_image(1).status == SceneImageStatus.APPROVED
    assert manifest.get_image(2).status == SceneImageStatus.PENDING_IMAGE_REVIEW
    assert manifest.all_approved is False  # Scene 2 still pending

    # Reject scene 2
    engine.reject_scene_image(sample_storyboard.storyboard_id, scene_number=2, reason="Composition too dark")
    manifest = engine.get_manifest(sample_storyboard.storyboard_id)
    assert manifest.get_image(2).status == SceneImageStatus.REJECTED
    assert manifest.all_approved is False

    # Approve all images
    engine.approve_all_images(sample_storyboard.storyboard_id, notes="Final sign-off")
    manifest = engine.get_manifest(sample_storyboard.storyboard_id)
    assert manifest.get_image(1).status == SceneImageStatus.APPROVED
    assert manifest.get_image(2).status == SceneImageStatus.APPROVED
    assert manifest.all_approved is True


# --- 7. Manual Image Import Workflow Tests ---

def test_manual_image_import_creates_real_production_asset(sample_storyboard, tmp_path):
    """Verify importing an external 1080x1920 image marks it is_mock_asset=False and generates thumbnail."""
    from PIL import Image

    # Create dummy external 1080x1920 vertical image
    external_img_path = tmp_path / "external_ai_art.png"
    img = Image.new("RGB", (1080, 1920), color=(30, 60, 90))
    img.save(external_img_path)

    engine = ImageGenerationEngine(base_output_dir=tmp_path / "images")

    imported = engine.import_scene_image(
        storyboard=sample_storyboard,
        scene_number=1,
        source_image_path=external_img_path,
        reviewer_notes="Imported from free Leonardo.ai generation",
        auto_approve=True,
    )

    assert imported.is_mock_asset is False
    assert imported.provider == "manual_import"
    assert imported.cost_usd == 0.0
    assert imported.status == SceneImageStatus.APPROVED
    assert Path(imported.image_path).exists()
    assert Path(imported.thumbnail_path).exists()
    assert len(imported.file_hash) == 64

    manifest = engine.get_manifest(sample_storyboard.storyboard_id)
    assert manifest.has_mock_assets is False


def test_manual_image_import_horizontal_fails(sample_storyboard, tmp_path):
    """Attempting to import a horizontal image (1920x1080) raises ImageEngineError."""
    from PIL import Image

    horizontal_path = tmp_path / "horizontal_art.png"
    img = Image.new("RGB", (1920, 1080), color=(10, 20, 30))
    img.save(horizontal_path)

    engine = ImageGenerationEngine(base_output_dir=tmp_path / "images")

    with pytest.raises(ImageEngineError, match="Vertical 9:16 orientation"):
        engine.import_scene_image(
            storyboard=sample_storyboard,
            scene_number=1,
            source_image_path=horizontal_path,
        )


def test_batch_import_storyboard_images_passes_video_validation(sample_storyboard, tmp_path):
    """Batch importing all scenes with auto_approve=True satisfies validate_ready_for_video."""
    from PIL import Image

    ext_1 = tmp_path / "scene1.png"
    ext_2 = tmp_path / "scene2.png"
    Image.new("RGB", (1080, 1920), color="blue").save(ext_1)
    Image.new("RGB", (1080, 1920), color="green").save(ext_2)

    engine = ImageGenerationEngine(base_output_dir=tmp_path / "images")
    manifest = engine.import_storyboard_images(
        storyboard=sample_storyboard,
        image_mapping={1: ext_1, 2: ext_2},
        auto_approve=True,
    )

    assert manifest.all_approved is True
    assert manifest.has_mock_assets is False

    # Validation for video assembly passes without error
    engine.validate_ready_for_video(sample_storyboard)
