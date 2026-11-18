"""Comprehensive test suite verifying production engine upgrades:
1. Minimum 10 distinct image assets requirement.
2. Repeated images/crops/zooms are not counted as distinct assets.
3. Every visual shot maps to the correct narration/storyboard moment.
4. Character consistency and asset provenance checks remain intact.
5. Failed voice candidates cannot silently become production-ready.
6. Voice approval requires actual human listening approval, not just technical success.
"""

from pathlib import Path
import pytest

from src.audio_engine.quality_evaluator import (
    QualityStatus as AudioQualityStatus,
    VoiceLifecycleStatus,
    VoiceQualityChecker,
    VoiceQualityReport,
)
from src.image_engine.eligibility import ProductionEligibilityValidator
from src.image_engine.exceptions import (
    ImageReviewRequiredError,
    MockAssetProductionBlockedError,
    ProductionEligibilityBlockedError,
)
from src.image_engine.models import (
    GeneratedImageMetadata,
    SceneImageStatus,
    StoryboardImageManifest,
)
from src.quality_checker.fidelity_checks import FidelityChecker
from src.quality_checker.models import CheckSeverity, QualityStatus
from src.storyboard_generator.models import (
    CameraMovement,
    ScientificClaimVerification,
    StoryboardDossier,
    StoryboardScene,
    VisualConsistencyProfile,
)


@pytest.fixture
def sample_consistency_profile():
    return VisualConsistencyProfile(
        character_name="Colossal Giant",
        character_reference_image="assets/images/characters/colossal_titan_ref.png",
        facial_features="Striated crimson muscle fibers, skull teeth, glowing yellow iris eyes",
        hairstyle="Bald muscular skull with rising atmospheric vapor",
        clothing_and_attire="None (biological musculature)",
        color_palette="Crimson red, bone white, smoke charcoal, amber yellow",
        art_direction="Modern cinematic high-contrast anime key visual, 8k resolution, vertical 9:16",
        negative_prompt="photorealistic, 3d cgi render, blurry, deformed anatomy, watermark",
    )


@pytest.fixture
def sample_12shot_storyboard(sample_consistency_profile):
    scenes = [
        StoryboardScene(
            scene_number=i,
            narration_hinglish=f"कथा भाग {i} का विवरण।",
            narration_english_meaning=f"Narrative part {i} description.",
            camera_angle="low-angle" if i % 2 == 0 else "wide-angle",
            framing="medium-shot",
            subject_placement="center",
            image_prompt_positive=f"Cinematic anime scene {i} visual composition",
            suggested_duration_seconds=3.5,
            camera_movement=CameraMovement.SLOW_ZOOM_IN,
        )
        for i in range(1, 13)
    ]
    return StoryboardDossier(
        storyboard_id="sb_test_12shots",
        title="12-Shot Test Short",
        topic="Anime Science Biomechanics",
        target_duration_seconds=43.5,
        pause_budget_seconds=1.5,
        hook="Opening hook question.",
        body="Core narrative body explanation.",
        takeaway="Closing scientific takeaway.",
        visual_consistency=sample_consistency_profile,
        scenes=scenes,
        scientific_claims=[
            ScientificClaimVerification(
                claim="Square-Cube Law states mass scales with L^3 and area with L^2.",
                source_title="Galileo 1638",
                is_verified=True,
                verification_status="human_checked",
            )
        ],
        source_script_id="script_test_01",
    )


# --- 1. Minimum 10 Distinct Image Assets Tests ---

def test_minimum_10_distinct_images_requirement_pass(sample_12shot_storyboard):
    """Verify that a manifest with 12 genuinely distinct image assets passes distinctness gate."""
    images = [
        GeneratedImageMetadata(
            scene_number=i,
            image_path=f"/path/to/shot_{i:02d}.png",
            provider="cinematic_composite",
            prompt_used=f"Prompt for distinct shot {i}",
            file_hash=f"hash_distinct_unique_token_{i:04d}",
            is_mock_asset=False,
            status=SceneImageStatus.APPROVED,
        )
        for i in range(1, 13)
    ]
    manifest = StoryboardImageManifest(
        storyboard_id=sample_12shot_storyboard.storyboard_id,
        total_scenes=12,
        images=images,
    )

    # 1. Eligibility validator check
    distinct_count = ProductionEligibilityValidator.validate_minimum_distinct_images(manifest, min_distinct_images=10)
    assert distinct_count == 12

    # 2. FidelityChecker QA check
    qa_res = FidelityChecker.check_distinct_image_asset_count(manifest, sample_12shot_storyboard, min_distinct_images=10)
    assert qa_res.status == QualityStatus.PASS
    assert qa_res.measured_value == 12


def test_fewer_than_10_images_blocks_production(sample_12shot_storyboard):
    """Verify that a short with only 4 or 5 images is strictly blocked from production."""
    images = [
        GeneratedImageMetadata(
            scene_number=i,
            image_path=f"/path/to/shot_{i:02d}.png",
            provider="cinematic_composite",
            prompt_used=f"Prompt for shot {i}",
            file_hash=f"hash_{i:04d}",
            is_mock_asset=False,
            status=SceneImageStatus.APPROVED,
        )
        for i in range(1, 5)  # Only 4 images
    ]
    manifest = StoryboardImageManifest(
        storyboard_id=sample_12shot_storyboard.storyboard_id,
        total_scenes=4,
        images=images,
    )

    with pytest.raises(ProductionEligibilityBlockedError) as exc:
        ProductionEligibilityValidator.validate_minimum_distinct_images(manifest, min_distinct_images=10)
    assert "requires at least 10 genuinely distinct visual images" in str(exc.value)

    qa_res = FidelityChecker.check_distinct_image_asset_count(manifest, sample_12shot_storyboard, min_distinct_images=10)
    assert qa_res.status == QualityStatus.FAIL
    assert qa_res.measured_value == 4


# --- 2. Repeated Images Detection Tests ---

def test_repeated_images_not_counted_as_distinct(sample_12shot_storyboard):
    """Verify that repeated copies or duplicate hashes of the same image are NOT counted as distinct."""
    # 12 scene entries, but only 3 distinct hashes repeated 4 times each
    images = []
    for i in range(1, 13):
        group_id = (i % 3) + 1  # 1, 2, or 3
        images.append(
            GeneratedImageMetadata(
                scene_number=i,
                image_path=f"/path/to/repeated_image_{group_id}.png",
                provider="cinematic_composite",
                prompt_used=f"Repeated prompt for group {group_id}",
                file_hash=f"shared_hash_for_group_{group_id}",
                is_mock_asset=False,
                status=SceneImageStatus.APPROVED,
            )
        )

    manifest = StoryboardImageManifest(
        storyboard_id=sample_12shot_storyboard.storyboard_id,
        total_scenes=12,
        images=images,
    )

    # Even though len(images) == 12, distinct hashes == 3 < 10
    with pytest.raises(ProductionEligibilityBlockedError) as exc:
        ProductionEligibilityValidator.validate_minimum_distinct_images(manifest, min_distinct_images=10)
    assert "found 3 distinct assets out of 12 scenes" in str(exc.value)

    qa_res = FidelityChecker.check_distinct_image_asset_count(manifest, sample_12shot_storyboard, min_distinct_images=10)
    assert qa_res.status == QualityStatus.FAIL
    assert qa_res.measured_value == 3


# --- 3. Visual Shot to Storyboard Mapping Tests ---

def test_unmapped_visual_shots_fail_qa(sample_12shot_storyboard):
    """Verify that images whose scene numbers do not map to valid storyboard scenes fail QA."""
    images = [
        GeneratedImageMetadata(
            scene_number=99,  # Unmapped scene number
            image_path="/path/to/shot_unmapped.png",
            provider="cinematic_composite",
            prompt_used="Unmapped prompt",
            file_hash="hash_unmapped_shot",
            is_mock_asset=False,
            status=SceneImageStatus.APPROVED,
        )
    ]
    manifest = StoryboardImageManifest(
        storyboard_id=sample_12shot_storyboard.storyboard_id,
        total_scenes=1,
        images=images,
    )

    qa_res = FidelityChecker.check_distinct_image_asset_count(manifest, sample_12shot_storyboard, min_distinct_images=1)
    assert qa_res.status == QualityStatus.FAIL
    assert "do not map to valid storyboard scenes" in qa_res.message


# --- 4. Character Consistency & Provenance Tests ---

def test_visual_consistency_profile_integrity(sample_consistency_profile):
    """Verify that visual consistency profile maintains all required character continuity fields."""
    assert sample_consistency_profile.character_name == "Colossal Giant"
    assert "muscle" in sample_consistency_profile.facial_features.lower()
    assert "crimson" in sample_consistency_profile.color_palette.lower()
    assert "vertical 9:16" in sample_consistency_profile.art_direction.lower()
    assert sample_consistency_profile.aspect_ratio == "9:16"


# --- 5. Strict Voice Human Listening Gate Tests ---

def test_failed_voice_candidate_cannot_enter_video_production():
    """Verify that a voice candidate marked HUMAN_LISTENING_FAILED is strictly blocked from production."""
    class FakeFailedVoiceResult:
        provider = "edge_tts"
        is_mock_asset = False
        lifecycle_status = "HUMAN_LISTENING_FAILED"

    with pytest.raises(ProductionEligibilityBlockedError) as exc:
        ProductionEligibilityValidator.validate_audio_for_production(FakeFailedVoiceResult())
    assert "failed human listening evaluation" in str(exc.value)


def test_voice_approval_requires_explicit_human_approval():
    """Verify that acoustic metric pass alone cannot grant PRODUCTION_READY without human approval."""
    checker = VoiceQualityChecker()

    # Report without human review
    report = VoiceQualityReport(
        audio_path="test_audio.wav",
        overall_status=AudioQualityStatus.PASS,
        lifecycle_status=VoiceLifecycleStatus.HUMAN_LISTENING_REVIEW_PENDING,
        duration_seconds=40.0,
        word_count=85,
        speech_rate_wpm=128.0,
        peak_dbfs=-1.5,
        rms_dbfs=-20.0,
        clipped_samples=0,
        clipping_ratio=0.0,
        max_silence_gap_seconds=0.25,
        leading_silence_seconds=0.05,
        trailing_silence_seconds=0.08,
        passed=True,
    )

    # Initial state should be review pending, not production ready
    assert report.lifecycle_status == VoiceLifecycleStatus.HUMAN_LISTENING_REVIEW_PENDING
    assert report.is_production_ready is False

    # Recording human listening approval elevates to PRODUCTION_READY
    approved_report = checker.record_human_listening_evaluation(
        report=report,
        score=9.2,
        approved=True,
        notes="Authentic Indian Hindi native speaker cadence and pronunciation confirmed.",
    )
    assert approved_report.lifecycle_status == VoiceLifecycleStatus.PRODUCTION_READY
    assert approved_report.is_production_ready is True
    assert approved_report.human_listening_score == 9.2

    # Rejecting via human listening transitions to HUMAN_LISTENING_FAILED
    failed_report = checker.record_human_listening_evaluation(
        report=report,
        score=4.5,
        approved=False,
        notes="Robotic cadence and artificial syllable gaps detected.",
    )
    assert failed_report.lifecycle_status == VoiceLifecycleStatus.HUMAN_LISTENING_FAILED
    assert failed_report.is_production_ready is False
