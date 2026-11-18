"""Comprehensive Offline Regression Tests for Script Fidelity, Pacing, Attribution, and Approval Invalidation."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from src.audio_engine.bgm_library import BGMLibraryManager
from src.audio_engine.models import BGMTrackMetadata
from src.pipeline.exceptions import HumanApprovalRequiredError, ScriptFidelityError
from src.pipeline.validators import PipelineGatekeeper
from src.quality_checker.fidelity_checks import FidelityChecker
from src.quality_checker.models import QualityReport, QualityStatus
from src.script_manager.models import ContentCategory, ResearchReference, Script, ScriptStatus
from src.storyboard_generator.fidelity import (
    ScriptStoryboardFidelityValidator,
    compute_canonical_narration_checksum,
)
from src.storyboard_generator.models import (
    CameraMovement,
    StoryboardDossier,
    StoryboardScene,
    VisualConsistencyProfile,
)
from src.storyboard_generator.pacing import (
    check_narration_duration_limits,
    estimate_duration_from_narration,
)
from src.youtube_uploader.approval import UploadApprovalGate
from src.youtube_uploader.exceptions import ApprovalRequiredError, UploadIntegrityError
from src.youtube_uploader.models import PrivacyStatus, UploadApprovalRecord, UploadMetadata


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_script() -> Script:
    """Standard approved 104-word script."""
    return Script(
        id="script_test_fidelity_titans",
        title="Kyu Nahi Ban Sakte Real Life Titans?",
        category=ContentCategory.ANIME_SCIENCE,
        hook="Kya Giant Science Fiction ka 60-meter lamba Colossal Giant real life mein zinda reh sakta hai?",
        body=(
            "Anime mein toh Titans bina kisi problem ke move kar lete hain. "
            "Lekin science ke mutaabiq, jab koi creature bada hota hai, toh uska volume and weight cube ki speed se badhta hai, jabki bones aur muscles sirf square ki speed se! "
            "Ise kehte hain Square-Cube Law. "
            "Is law ke chalte, itne bade weight ke neeche insaani haddiyan ek hi second mein toot jayengi, aur wo apne hi weight ke niche crush ho jayenge!"
        ),
        takeaway="Toh अगली baar anime dekho, toh physics ke is rule ko zaroor yaad rakhna!",
        status=ScriptStatus.APPROVED,
        research_references=[
            ResearchReference(
                claim="As linear dimensions increase, volume scales cubically while surface area scales quadratically.",
                source="On Growth and Form",
                is_verified=True,
            )
        ],
    )


@pytest.fixture
def sample_vc_profile() -> VisualConsistencyProfile:
    return VisualConsistencyProfile(
        character_name="Host Professor AI",
        facial_features="Expressive eyes, smart futuristic visor",
        hairstyle="Short silver hair",
        clothing_and_attire="Grey tech hoodie with neon lines",
        color_palette="Dark blue and cyan",
        art_direction="Anime style, vertical 9:16",
        negative_prompt="blurry, watermark",
        aspect_ratio="9:16",
    )


@pytest.fixture
def perfect_storyboard(sample_script: Script, sample_vc_profile: VisualConsistencyProfile) -> StoryboardDossier:
    """5-scene storyboard preserving the sample script verbatim."""
    scenes = [
        StoryboardScene(
            scene_number=1,
            narration_hinglish="Kya Giant Science Fiction ka 60-meter lamba Colossal Giant real life mein zinda reh sakta hai?",
            narration_english_meaning="Can the Colossal Giant survive in real life?",
            camera_angle="low-angle",
            framing="medium-close-up",
            subject_placement="center",
            image_prompt_positive="Towering colossus titan, 9:16 vertical",
            suggested_duration_seconds=8.0,
            camera_movement=CameraMovement.SLOW_ZOOM_IN,
        ),
        StoryboardScene(
            scene_number=2,
            narration_hinglish="Anime mein toh Titans bina kisi problem ke move kar lete hain.",
            narration_english_meaning="In anime Titans move without problem.",
            camera_angle="eye-level",
            framing="medium-close-up",
            subject_placement="center",
            image_prompt_positive="Anime scientist, 9:16 vertical",
            suggested_duration_seconds=6.0,
            camera_movement=CameraMovement.STATIC_DRIFT,
        ),
        StoryboardScene(
            scene_number=3,
            narration_hinglish="Lekin science ke mutaabiq, jab koi creature bada hota hai, toh uska volume and weight cube ki speed se badhta hai, jabki bones aur muscles sirf square ki speed se!",
            narration_english_meaning="According to science scaling principles.",
            camera_angle="high-angle",
            framing="wide-establishing",
            subject_placement="center",
            image_prompt_positive="Mathematical 3D geometric cubes scaling, 9:16 vertical",
            suggested_duration_seconds=14.0,
            camera_movement=CameraMovement.PAN_UP,
        ),
        StoryboardScene(
            scene_number=4,
            narration_hinglish="Ise kehte hain Square-Cube Law. Is law ke chalte, itne bade weight ke neeche insaani haddiyan ek hi second mein toot jayengi, aur wo apne hi weight ke niche crush ho jayenge!",
            narration_english_meaning="This is the Square-Cube Law.",
            camera_angle="eye-level",
            framing="medium-close-up",
            subject_placement="center",
            image_prompt_positive="Fantasy titan skeleton collapsing, 9:16 vertical",
            suggested_duration_seconds=16.0,
            camera_movement=CameraMovement.SLOW_ZOOM_OUT,
        ),
        StoryboardScene(
            scene_number=5,
            narration_hinglish="Toh अगली baar anime dekho, toh physics ke is rule ko zaroor yaad rakhna!",
            narration_english_meaning="So next time you watch anime, remember physics.",
            camera_angle="eye-level",
            framing="medium-close-up",
            subject_placement="center",
            image_prompt_positive="Host Professor AI concluding takeaway, 9:16 vertical",
            suggested_duration_seconds=7.0,
            camera_movement=CameraMovement.SLOW_ZOOM_IN,
        ),
    ]

    return StoryboardDossier(
        storyboard_id="sb_perfect_fidelity_test",
        title=sample_script.title,
        topic=sample_script.title,
        target_duration_seconds=53.0,
        pause_budget_seconds=2.0,
        hook=sample_script.hook,
        body=sample_script.body,
        takeaway=sample_script.takeaway,
        visual_consistency=sample_vc_profile,
        scenes=scenes,
        source_script_id=sample_script.id,
        source_script_checksum=sample_script.content_hash,
        source_script_version="1.0",
        narration_fidelity_status="VERIFIED",
    )


# =============================================================================
# 1. SCRIPT FIDELITY TESTS
# =============================================================================

def test_exact_narration_passes_fidelity(sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Verbatim narration preserves all components and passes validation."""
    report = ScriptStoryboardFidelityValidator.validate_fidelity(
        script=sample_script,
        storyboard=perfect_storyboard,
        raise_on_error=True,
    )
    assert report.is_valid is True
    assert report.hook_preserved is True
    assert report.body_preserved is True
    assert report.takeaway_preserved is True
    assert report.sentence_order_preserved is True
    assert len(report.missing_sentences) == 0
    assert len(report.inserted_sentences) == 0


def test_missing_hook_fails_fidelity(sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Modifying or missing opening hook fails fidelity validation."""
    perfect_storyboard.scenes[0].narration_hinglish = "Titans real life mein possible nahi hain."
    with pytest.raises(ScriptFidelityError, match="Hook not preserved"):
        ScriptStoryboardFidelityValidator.validate_fidelity(
            script=sample_script,
            storyboard=perfect_storyboard,
            raise_on_error=True,
        )


def test_missing_body_sentence_fails_fidelity(sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Silently omitting any body sentence fails fidelity validation."""
    # Omit Scene 2 ("Anime mein toh Titans...")
    perfect_storyboard.scenes.pop(1)
    with pytest.raises(ScriptFidelityError, match="Approved script sentences missing"):
        ScriptStoryboardFidelityValidator.validate_fidelity(
            script=sample_script,
            storyboard=perfect_storyboard,
            raise_on_error=True,
        )


def test_missing_takeaway_fails_fidelity(sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Omitting the concluding takeaway fails fidelity validation."""
    # Drop Scene 5 (takeaway)
    perfect_storyboard.scenes.pop(4)
    with pytest.raises(ScriptFidelityError, match="Script Takeaway omitted"):
        ScriptStoryboardFidelityValidator.validate_fidelity(
            script=sample_script,
            storyboard=perfect_storyboard,
            raise_on_error=True,
        )


def test_changed_word_fails_fidelity(sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Replacing a word in the narration fails exact word sequence check."""
    # Change 'Square-Cube Law' to 'Scaling Principle'
    perfect_storyboard.scenes[3].narration_hinglish = perfect_storyboard.scenes[3].narration_hinglish.replace("Square-Cube Law", "Scaling Principle")
    with pytest.raises(ScriptFidelityError, match="discrepancy|mismatch"):
        ScriptStoryboardFidelityValidator.validate_fidelity(
            script=sample_script,
            storyboard=perfect_storyboard,
            raise_on_error=True,
        )


def test_reordered_sentences_fail_fidelity(sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Narrating approved sentences out of order fails fidelity validation."""
    # Swap scene 2 and scene 3
    perfect_storyboard.scenes[1], perfect_storyboard.scenes[2] = perfect_storyboard.scenes[2], perfect_storyboard.scenes[1]
    with pytest.raises(ScriptFidelityError, match="ordering violated"):
        ScriptStoryboardFidelityValidator.validate_fidelity(
            script=sample_script,
            storyboard=perfect_storyboard,
            raise_on_error=True,
        )


def test_duplicated_sentence_fails_fidelity(sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Repeating a sentence across multiple scenes fails fidelity validation."""
    # Duplicate scene 2 narration into scene 3
    perfect_storyboard.scenes[2].narration_hinglish = perfect_storyboard.scenes[1].narration_hinglish
    with pytest.raises(ScriptFidelityError):
        ScriptStoryboardFidelityValidator.validate_fidelity(
            script=sample_script,
            storyboard=perfect_storyboard,
            raise_on_error=True,
        )


def test_additional_narration_inserted_fails_fidelity(sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Inserting unapproved creative commentary fails fidelity validation."""
    perfect_storyboard.scenes[1].narration_hinglish += " Ye sach mein bohot ajeeb baat hai!"
    with pytest.raises(ScriptFidelityError, match="extra sentences inserted|word count mismatch"):
        ScriptStoryboardFidelityValidator.validate_fidelity(
            script=sample_script,
            storyboard=perfect_storyboard,
            raise_on_error=True,
        )


def test_source_script_id_mismatch_fails_fidelity(sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Mismatched source_script_id fails provenance check."""
    perfect_storyboard.source_script_id = "script_different_topic"
    with pytest.raises(ScriptFidelityError, match="script ID mismatch"):
        ScriptStoryboardFidelityValidator.validate_fidelity(
            script=sample_script,
            storyboard=perfect_storyboard,
            raise_on_error=True,
        )


# =============================================================================
# 2. PACING & DURATION TESTS
# =============================================================================

def test_104_word_script_estimates_51_seconds(sample_script: Script):
    """104 words at ~2.12 WPS with 2s pause budget estimates approximately 51 seconds."""
    full_text = f"{sample_script.hook} {sample_script.body} {sample_script.takeaway}"
    total_dur, w_count = estimate_duration_from_narration(
        narration_text=full_text,
        words_per_second=2.12,
        pause_budget_seconds=2.0,
    )
    assert w_count == 104
    assert 50.0 <= total_dur <= 52.0


def test_script_within_limits_not_condensed(sample_script: Script):
    """A script within 60s Shorts ceiling is accepted without condensation warnings."""
    full_text = f"{sample_script.hook} {sample_script.body} {sample_script.takeaway}"
    is_within, est_dur, warning = check_narration_duration_limits(
        narration_text=full_text,
        words_per_second=2.12,
        pause_budget_seconds=2.0,
        max_duration_seconds=60.0,
    )
    assert is_within is True
    assert warning is None
    assert est_dur <= 60.0


def test_script_exceeding_limits_produces_warning_without_silent_condensing():
    """Scripts exceeding 60.0s generate an explicit warning and are not silently condensed."""
    long_narration = "Yeh ek bohot hi lamba script hai. " * 35  # ~210 words -> ~100s
    is_within, est_dur, warning = check_narration_duration_limits(
        narration_text=long_narration,
        words_per_second=2.12,
        pause_budget_seconds=2.0,
        max_duration_seconds=60.0,
    )
    assert is_within is False
    assert est_dur > 60.0
    assert "exceeding the 60.0s YouTube Shorts ceiling" in warning
    assert "Pacing Engine will NOT silently condense" in warning


# =============================================================================
# 3. MUSIC ATTRIBUTION TESTS
# =============================================================================

def test_creative_commons_attribution_format_complete():
    """CC BY tracks format transparent attribution with title, artist, and license."""
    track = BGMTrackMetadata(
        track_id="test_cc_track",
        title="Airplane Mode (Instrumental Version)",
        artist="Josh Woodward",
        source="Free Music Archive",
        license="Creative Commons Attribution 4.0 International (CC BY 4.0)",
        license_url="http://creativecommons.org/licenses/by/4.0/",
        attribution_required=True,
        file_path="mock/path.mp3",
    )
    attribution = BGMLibraryManager.format_attribution(track)
    assert 'Music: "Airplane Mode (Instrumental Version)"' in attribution
    assert "Josh Woodward" in attribution
    assert "CC BY 4.0" in attribution


def test_attribution_not_required_returns_none():
    """Attribution-not-required YouTube Audio Library tracks return None (no fabricated credits)."""
    track = BGMTrackMetadata(
        track_id="test_yt_track",
        title="Space Station",
        artist="Jeremy Blake",
        source="YouTube Audio Library",
        license="YouTube Audio Library License - Attribution Not Required",
        attribution_required=False,
        file_path="mock/path.mp3",
    )
    attribution = BGMLibraryManager.format_attribution(track)
    assert attribution is None


def test_missing_artist_raises_error_when_attribution_required():
    """Missing artist on an attribution-required track raises ValueError."""
    track = BGMTrackMetadata(
        track_id="test_broken_track",
        title="Broken Track",
        artist="Temp Artist",
        source="FMA",
        license="CC BY 4.0",
        attribution_required=True,
        file_path="mock/path.mp3",
    )
    track.artist = ""
    with pytest.raises(ValueError, match="title and artist are required"):
        BGMLibraryManager.format_attribution(track)


def test_fidelity_checker_flags_missing_attribution_in_description():
    """FidelityChecker fails QA check when description lacks required CC BY attribution."""
    track = BGMTrackMetadata(
        track_id="test_cc_track",
        title="Airplane Mode (Instrumental Version)",
        artist="Josh Woodward",
        source="Free Music Archive",
        license="CC BY 4.0",
        attribution_required=True,
        file_path="mock/path.mp3",
    )
    bad_desc = "Kya Colossal Giant real life mein zinda reh sakta hai? #Shorts #Anime"
    res = FidelityChecker.check_music_attribution_completeness(track, bad_desc)
    assert res.status == QualityStatus.FAIL
    assert "requires attribution, but attribution is missing" in res.message


def test_fidelity_checker_passes_when_attribution_present_in_description():
    """FidelityChecker passes QA check when description includes verified CC BY attribution."""
    track = BGMTrackMetadata(
        track_id="test_cc_track",
        title="Airplane Mode (Instrumental Version)",
        artist="Josh Woodward",
        source="Free Music Archive",
        license="CC BY 4.0",
        attribution_required=True,
        file_path="mock/path.mp3",
    )
    good_desc = (
        "Kya Colossal Giant real life mein zinda reh sakta hai? #Shorts\n\n"
        "Music: \"Airplane Mode (Instrumental Version)\" by Josh Woodward (https://www.joshwoodward.com/) licensed under CC BY 4.0"
    )
    res = FidelityChecker.check_music_attribution_completeness(track, good_desc)
    assert res.status == QualityStatus.PASS


# =============================================================================
# 4. APPROVAL INVALIDATION & INTEGRITY TESTS
# =============================================================================

def test_changed_video_invalidates_approval(tmp_path: Path):
    """Modifying video file bytes invalidates cryptographic approval record."""
    v1 = tmp_path / "video1.mp4"
    v1.write_bytes(b"initial_rendered_video_bytes")

    meta = UploadMetadata(title="Test Short", made_for_kids=False)
    report = QualityReport(production_id="prod_test_01", overall_status=QualityStatus.PASS)

    record = UploadApprovalGate.create_approval_record(
        production_id="prod_test_01",
        video_path=v1,
        metadata=meta,
        quality_report=report,
        approver_notes="Approved initial",
    )

    # Valid initially
    UploadApprovalGate.validate_approval(record, v1, meta)

    # Modify video file
    v1.write_bytes(b"modified_video_content_different_hash")
    with pytest.raises(UploadIntegrityError, match="Video file was modified"):
        UploadApprovalGate.validate_approval(record, v1, meta)


def test_changed_metadata_or_attribution_invalidates_approval(tmp_path: Path):
    """Modifying metadata description or attribution invalidates approval."""
    v1 = tmp_path / "video1.mp4"
    v1.write_bytes(b"stable_video_bytes")

    meta1 = UploadMetadata(title="Test Short", description="Initial description", made_for_kids=False)
    report = QualityReport(production_id="prod_test_01", overall_status=QualityStatus.PASS)

    record = UploadApprovalGate.create_approval_record(
        production_id="prod_test_01",
        video_path=v1,
        metadata=meta1,
        quality_report=report,
        approver_notes="Approved initial",
    )

    meta2 = UploadMetadata(title="Test Short", description="Modified description with new text", made_for_kids=False)
    with pytest.raises(UploadIntegrityError, match="Upload metadata was modified"):
        UploadApprovalGate.validate_approval(record, v1, meta2)


def test_changed_privacy_status_invalidates_approval(tmp_path: Path):
    """Modifying publication privacy level invalidates approval."""
    v1 = tmp_path / "video1.mp4"
    v1.write_bytes(b"stable_video_bytes")

    meta_private = UploadMetadata(title="Test Short", privacy_status=PrivacyStatus.PRIVATE, made_for_kids=False)
    report = QualityReport(production_id="prod_test_01", overall_status=QualityStatus.PASS)

    record = UploadApprovalGate.create_approval_record(
        production_id="prod_test_01",
        video_path=v1,
        metadata=meta_private,
        quality_report=report,
        approver_notes="Approved private",
        requested_privacy=PrivacyStatus.PRIVATE,
    )

    meta_public = UploadMetadata(title="Test Short", privacy_status=PrivacyStatus.PUBLIC, made_for_kids=False)
    with pytest.raises(UploadIntegrityError, match="Privacy status was modified"):
        UploadApprovalGate.validate_approval(record, v1, meta_public)


def test_changed_script_or_narration_invalidates_approval(tmp_path: Path, sample_script: Script, perfect_storyboard: StoryboardDossier):
    """Modifying bound script or storyboard narration invalidates approval."""
    v1 = tmp_path / "video1.mp4"
    v1.write_bytes(b"stable_video_bytes")

    meta = UploadMetadata(title=sample_script.title, made_for_kids=False)
    report = QualityReport(production_id="prod_test_01", overall_status=QualityStatus.PASS)

    record = UploadApprovalGate.create_approval_record(
        production_id="prod_test_01",
        video_path=v1,
        metadata=meta,
        quality_report=report,
        approver_notes="Approved with provenance",
        script=sample_script,
        storyboard=perfect_storyboard,
    )

    # Valid with original script and storyboard
    UploadApprovalGate.validate_approval(record, v1, meta, current_script=sample_script, current_storyboard=perfect_storyboard)

    # Modify script
    modified_script = sample_script.model_copy(update={"hook": "Completely new hook sentence?"})
    modified_script.content_hash = "different_hash_value"
    with pytest.raises(UploadIntegrityError, match="Source script was modified"):
        UploadApprovalGate.validate_approval(record, v1, meta, current_script=modified_script, current_storyboard=perfect_storyboard)


def test_expired_approval_fails(tmp_path: Path):
    """An approval record older than approval_ttl_hours fails validation."""
    v1 = tmp_path / "video1.mp4"
    v1.write_bytes(b"stable_video_bytes")

    meta = UploadMetadata(title="Test Short", made_for_kids=False)
    report = QualityReport(production_id="prod_test_01", overall_status=QualityStatus.PASS)

    record = UploadApprovalGate.create_approval_record(
        production_id="prod_test_01",
        video_path=v1,
        metadata=meta,
        quality_report=report,
        approver_notes="Approved in the past",
        approval_ttl_hours=24,
    )

    # Age it 25 hours
    record.approved_at = datetime.now(timezone.utc) - timedelta(hours=25)
    with pytest.raises(UploadIntegrityError, match="Approval record has expired"):
        UploadApprovalGate.validate_approval(record, v1, meta)
