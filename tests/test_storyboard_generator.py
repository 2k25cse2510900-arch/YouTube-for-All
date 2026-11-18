"""Automated tests for AI Script & Storyboard Generator."""

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from src.research_engine.client import GeminiResearchClient
from src.research_engine.models import (
    AnimeScienceDossier,
    ResearchCitation,
    SourceType,
    VerificationStatus,
)
from src.script_manager import (
    DailyScriptQueue,
    ScriptApprovalRequiredError,
    ScriptManager,
    ScriptRepository,
    ScriptStatus,
)
from src.storyboard_generator import (
    CameraMovement,
    PacingExceededError,
    ScientificClaimVerification,
    StoryboardDossier,
    StoryboardGenerator,
    StoryboardScene,
    VisualConsistencyProfile,
    calculate_pacing_budget,
    validate_combined_duration,
)


# --- 1. Dynamic Pacing Calculation Tests ---

def test_dynamic_pacing_calculation():
    """Verify that word-budget targets dynamically scale with duration and speech rate."""
    # 30s Short with 1.5s pause budget at 2.2 words/sec
    pacing_30 = calculate_pacing_budget(target_duration_seconds=30.0, words_per_second=2.2, pause_budget_seconds=1.5)
    assert pacing_30.effective_speaking_seconds == 28.5
    assert pacing_30.target_word_count == 63
    assert pacing_30.min_word_count <= 63 <= pacing_30.max_word_count

    # 45s Short with 2.0s pause budget at 2.2 words/sec
    pacing_45 = calculate_pacing_budget(target_duration_seconds=45.0, words_per_second=2.2, pause_budget_seconds=2.0)
    assert pacing_45.effective_speaking_seconds == 43.0
    assert pacing_45.target_word_count == 95

    # 60s Short with 2.5s pause budget at 2.4 words/sec
    pacing_60 = calculate_pacing_budget(target_duration_seconds=60.0, words_per_second=2.4, pause_budget_seconds=2.5)
    assert pacing_60.effective_speaking_seconds == 57.5
    assert pacing_60.target_word_count == 138


def test_combined_duration_validation_pass():
    """Verify that valid combined scene durations + pause budget pass cleanly."""
    scenes = [
        MagicMock(suggested_duration_seconds=8.0),
        MagicMock(suggested_duration_seconds=12.0),
        MagicMock(suggested_duration_seconds=13.0),
        MagicMock(suggested_duration_seconds=10.0),
    ]
    # 8 + 12 + 13 + 10 = 43s scenes + 2s pause = 45s total
    total = validate_combined_duration(scenes, pause_budget_seconds=2.0, target_duration_seconds=45.0)
    assert total == 45.0


def test_combined_duration_validation_exceeds_60s():
    """Verify that combined duration exceeding 60.0s raises PacingExceededError."""
    scenes = [
        MagicMock(suggested_duration_seconds=30.0),
        MagicMock(suggested_duration_seconds=30.0),
    ]
    # 60s scenes + 2s pause = 62s > 60s ceiling
    with pytest.raises(PacingExceededError) as exc:
        validate_combined_duration(scenes, pause_budget_seconds=2.0, target_duration_seconds=60.0)
    assert "exceeds the 60.0s YouTube Shorts hard ceiling" in str(exc.value)


def test_combined_duration_validation_deviates_from_target():
    """Verify that combined duration deviating beyond tolerance raises PacingExceededError."""
    scenes = [
        MagicMock(suggested_duration_seconds=10.0),
        MagicMock(suggested_duration_seconds=10.0),
    ]
    # 20s scenes + 2s pause = 22s (target: 45s, deviation: 23s > 3.5s)
    with pytest.raises(PacingExceededError) as exc:
        validate_combined_duration(scenes, pause_budget_seconds=2.0, target_duration_seconds=45.0)
    assert "deviates by" in str(exc.value)


# --- 2. Scientific Claim-Level Verification Tracking Tests ---

def test_claim_level_verification_tracking():
    """Verify that unverified scientific claims remain flagged until explicit human sign-off."""
    claim1 = ScientificClaimVerification(
        claim="Sensory deprivation causes temporal distortion after 72 hours.",
        source_title="Principles of Neural Science",
        source_type=SourceType.BOOK,
    )
    claim2 = ScientificClaimVerification(
        claim="Directed mental arithmetic maintains cognitive baseline under extreme stress.",
        source_title="Cognitive Psychology Review",
        source_type=SourceType.JOURNAL_ARTICLE,
    )

    # Initial state: Must be unverified
    assert claim1.is_verified is False
    assert claim1.verification_status == VerificationStatus.UNVERIFIED

    vc = VisualConsistencyProfile(
        character_name="Senku Ishigami",
        facial_features="Sharp crimson eyes, twin stone cracks extending from forehead across cheeks",
        hairstyle="Distinctive spiky celery-green hair fading to white tips",
        clothing_and_attire="Primitive cream-colored flax tunic with Einstein E=mc2 formula on chest",
        color_palette="Emerald green, stone grey, flax cream",
    )

    scenes = [
        StoryboardScene(
            scene_number=1,
            narration_hinglish="Senku ne 3,700 saal count kiye, lekin real science kya kehti hai?",
            narration_english_meaning="Senku counted for 3,700 years, but what does real science say?",
            camera_angle="low-angle",
            framing="extreme-close-up",
            subject_placement="center-weighted for vertical 9:16",
            image_prompt_positive="Senku Ishigami looking determined, stone cracked texture, spiky green hair, vertical 9:16",
            suggested_duration_seconds=13.0,
            camera_movement=CameraMovement.SLOW_ZOOM_IN,
        ),
        StoryboardScene(
            scene_number=2,
            narration_hinglish="Sensory deprivation mein dimaag bina signals ke hallucinate karne lagta hai.",
            narration_english_meaning="In sensory deprivation the brain starts hallucinating without signals.",
            camera_angle="eye-level",
            framing="medium-close-up",
            subject_placement="center-weighted",
            image_prompt_positive="Abstract neural network in sensory isolation chamber, vertical 9:16",
            suggested_duration_seconds=15.0,
            camera_movement=CameraMovement.STATIC_DRIFT,
        ),
        StoryboardScene(
            scene_number=3,
            narration_hinglish="Continuous calculation dimaag ko temporal anchor provide karta hai.",
            narration_english_meaning="Continuous calculation provides a temporal anchor to the mind.",
            camera_angle="high-angle",
            framing="medium-shot",
            subject_placement="center-weighted",
            image_prompt_positive="Mathematical formulas glowing around Senku in the dark stone shell, vertical 9:16",
            suggested_duration_seconds=15.0,
            camera_movement=CameraMovement.SLOW_ZOOM_OUT,
        ),
    ]

    dossier = StoryboardDossier(
        storyboard_id="test_sb_01",
        title="Counting in Stone",
        topic="Consciousness in Stone",
        target_duration_seconds=45.0,
        pause_budget_seconds=2.0,
        hook="Hook text in Hinglish",
        body="Body text in Hinglish",
        takeaway="Takeaway text in Hinglish",
        visual_consistency=vc,
        scenes=scenes,
        scientific_claims=[claim1, claim2],
    )

    # Must flag unverified claims at top level
    assert dossier.has_unverified_claims is True
    assert len(dossier.claims_pending_verification) == 2

    # Human verifies claim 1
    verified_ok = dossier.verify_claim(
        claim1.claim, reviewer_notes="Checked Chapter 14 of Principles of Neural Science"
    )
    assert verified_ok is True
    assert claim1.is_verified is True
    assert claim1.verification_status == VerificationStatus.HUMAN_CHECKED
    assert len(dossier.claims_pending_verification) == 1
    assert dossier.has_unverified_claims is True  # Claim 2 is still pending!

    # Human verifies claim 2
    dossier.verify_claim(claim2.claim, reviewer_notes="Checked DOI 10.1037/rev0001")
    assert claim2.is_verified is True
    assert len(dossier.claims_pending_verification) == 0
    assert dossier.has_unverified_claims is False


# --- 3. Visual Consistency & Reference Image Tests ---

def test_visual_consistency_profile_with_reference_image():
    """Verify that VisualConsistencyProfile supports character reference image paths for future engines."""
    vc = VisualConsistencyProfile(
        character_name="Senku Ishigami",
        character_reference_image="assets/character_refs/senku_front.png",
        facial_features="Crimson eyes, stone scars",
        hairstyle="Spiky green hair",
        clothing_and_attire="Flax tunic",
        color_palette="Green, stone grey, cream",
        art_direction="Ufotable anime style, volumetric lighting, vertical 9:16",
        negative_prompt="extra limbs, distorted anatomy",
    )
    assert vc.character_reference_image == "assets/character_refs/senku_front.png"
    assert vc.aspect_ratio == "9:16"


# --- 4. Mocked Storyboard Generation Service Tests ---

def test_generate_storyboard_service(tmp_path):
    """Verify StoryboardGenerator creates a valid StoryboardDossier with unverified claims and pacing."""
    mock_llm_json = {
        "title": "Dr. Stone: Time Counting Science",
        "hook": "Kya aap bina soye 3,700 saal count kar sakte hain?",
        "body": "Anime mein to Senku ne time count kar liya, lekin real neuroscience mein sensory deprivation dimaag ko tod deta hai.",
        "takeaway": "Real science mein time count karna nahi, dimaag ko anchor karna sabse bada task hai.",
        "visual_consistency": {
            "character_name": "Senku Ishigami",
            "facial_features": "Crimson eyes, symmetrical stone cracks on forehead",
            "hairstyle": "Spiky vertical green hair",
            "clothing_and_attire": "Primitive flax tunic with E=mc2 on chest",
            "color_palette": "Emerald green, granite grey, cream",
            "art_direction": "High-contrast anime key visual, volumetric rim lighting, 8k resolution, vertical 9:16",
            "negative_prompt": "distorted anatomy, extra limbs, deformed fingers, low resolution, blurry, watermark",
        },
        "scenes": [
            {
                "scene_number": 1,
                "narration_hinglish": "Kya ek insaan bina sensory input ke 3,700 saal tak awake reh sakta hai?",
                "narration_english_meaning": "Can a human stay awake for 3,700 years without sensory input?",
                "camera_angle": "low-angle",
                "framing": "extreme-close-up",
                "subject_placement": "center-weighted for vertical 9:16",
                "image_prompt_positive": "Petrified stone statue of Senku Ishigami, glowing crimson eyes behind stone, vertical 9:16",
                "image_prompt_negative": "distorted anatomy, blurry",
                "suggested_duration_seconds": 10.0,
                "camera_movement": "slow_zoom_in",
                "sound_effect_cue": "[SFX: Stone cracking heartbeat]",
            },
            {
                "scene_number": 2,
                "narration_hinglish": "Dr. Stone mein Senku lagatar seconds ginta raha taaki consciousness bani rahe.",
                "narration_english_meaning": "In Dr. Stone Senku continuously counted seconds to preserve consciousness.",
                "camera_angle": "eye-level",
                "framing": "medium-close-up",
                "subject_placement": "center-weighted",
                "image_prompt_positive": "Abstract mental clock ticking with mathematical equations swirling in darkness, vertical 9:16",
                "suggested_duration_seconds": 15.0,
                "camera_movement": "static_drift",
            },
            {
                "scene_number": 3,
                "narration_hinglish": "Lekin real neuroscience kehta hai ki 72 ghante mein dimaag hallucinations shuru kar deta hai.",
                "narration_english_meaning": "Real neuroscience states the brain starts hallucinating in 72 hours.",
                "camera_angle": "high-angle",
                "framing": "medium-shot",
                "subject_placement": "center-weighted",
                "image_prompt_positive": "Brain neural network glowing with fading electrical signals under sensory deprivation, vertical 9:16",
                "suggested_duration_seconds": 18.0,
                "camera_movement": "slow_zoom_out",
            },
        ],
        "bgm_suggestion": {
            "mood": "Tense mystery to electronic revelation",
            "tempo": "120 BPM",
            "instrumentation": "Sub-bass, clock ticking, synths",
        },
        "scientific_claims": [
            {
                "claim": "Sensory deprivation induces temporal hallucination within 72 hours.",
                "source_title": "Principles of Neural Science",
                "source_type": "book",
                "url": None,
                "verification_status": "unverified",
                "is_verified": False,
            }
        ],
    }

    mock_client = MagicMock(spec=GeminiResearchClient)
    mock_client.generate_json.return_value = mock_llm_json

    generator = StoryboardGenerator(client=mock_client, base_dir=tmp_path / "storyboards")

    dossier_input = AnimeScienceDossier(
        dossier_id="dossier_dr_stone_01",
        topic="Counting Consciousness in Stone",
        anime_title="Dr. Stone",
        character_or_scene="Senku Ishigami",
        anime_canon_premise="Consciousness maintained in stone for 3,700 years.",
        scientific_domain="Neuroscience",
        real_world_scientific_explanation="Sensory deprivation leads to cognitive drift without external anchors.",
        citations=[
            ResearchCitation(
                claim="Sensory deprivation induces temporal hallucination within 72 hours.",
                source_title="Principles of Neural Science",
                source_type=SourceType.BOOK,
            )
        ],
    )

    storyboard = generator.generate_storyboard(
        dossier=dossier_input,
        target_duration_seconds=45.0,
        pause_budget_seconds=2.0,
    )

    assert storyboard.storyboard_id.startswith("sb_anime_")
    assert len(storyboard.scenes) == 3
    # Duration validation: scenes (43.0s) + pause (2.0s) = 45.0s
    assert storyboard.total_estimated_seconds == 45.0
    # Must preserve unverified status
    assert storyboard.has_unverified_claims is True
    assert storyboard.scientific_claims[0].is_verified is False
    assert storyboard.visual_consistency.character_name == "Senku Ishigami"


# --- 5. ScriptManager Registration & Human Approval Safeguard Tests ---

def test_register_with_script_manager_enforces_pending_review(tmp_path):
    """Verify that registering a storyboard with ScriptManager forces PENDING_REVIEW and blocks queueing."""
    repo = ScriptRepository(base_dir=tmp_path / "processed")
    queue = DailyScriptQueue(repository=repo)
    sm = ScriptManager(repository=repo, queue=queue)

    generator = StoryboardGenerator(script_manager=sm, base_dir=tmp_path / "processed" / "storyboards")

    vc = VisualConsistencyProfile(
        character_name="Senku Ishigami",
        facial_features="Crimson eyes, stone marks",
        hairstyle="Green spiky hair",
        clothing_and_attire="Flax tunic",
        color_palette="Green, stone grey, cream",
    )

    scenes = [
        StoryboardScene(
            scene_number=1,
            narration_hinglish="Kya aap 3,700 saal count kar sakte hain?",
            narration_english_meaning="Can you count 3,700 years?",
            camera_angle="low-angle",
            framing="extreme-close-up",
            subject_placement="center",
            image_prompt_positive="Senku stone statue cracking, vertical 9:16",
            suggested_duration_seconds=20.0,
            camera_movement=CameraMovement.SLOW_ZOOM_IN,
        ),
        StoryboardScene(
            scene_number=2,
            narration_hinglish="Real science kehti hai dimaag 72 ghante mein hallucinate karne lagta hai.",
            narration_english_meaning="Real science says the brain hallucinates in 72 hours.",
            camera_angle="eye-level",
            framing="medium-shot",
            subject_placement="center",
            image_prompt_positive="Sensory deprivation chamber, vertical 9:16",
            suggested_duration_seconds=23.0,
            camera_movement=CameraMovement.SLOW_ZOOM_OUT,
        ),
    ]

    storyboard = StoryboardDossier(
        storyboard_id="sb_anime_senku_demo",
        title="Senku Time Counting",
        topic="Time Counting in Stone",
        target_duration_seconds=45.0,
        pause_budget_seconds=2.0,
        hook="Hook in Hinglish",
        body="Body in Hinglish",
        takeaway="Takeaway in Hinglish",
        visual_consistency=vc,
        scenes=scenes,
    )

    # Register with ScriptManager
    script = generator.register_with_script_manager(storyboard)

    # 1. Must be registered with PENDING_REVIEW status
    assert script.id == "sb_anime_senku_demo"
    assert script.status == ScriptStatus.PENDING_REVIEW

    # 2. Daily queue must refuse to select it until approved
    with pytest.raises(ScriptApprovalRequiredError) as exc:
        sm.get_next_daily_script()
    assert "waiting for human approval" in str(exc.value)

    # 3. Explicit human approval workflow
    approved = sm.approve_script(script.id, notes="Creator approved Hinglish script & image prompts")
    assert approved.status == ScriptStatus.APPROVED

    # 4. Now eligible for daily queue selection
    selected = sm.get_next_daily_script()
    assert selected.id == "sb_anime_senku_demo"
    assert selected.status == ScriptStatus.IN_PRODUCTION
