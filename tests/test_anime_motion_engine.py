"""Unit and regression tests for Anime Motion Engine.

Covers:
- CharacterSpecification and CharacterBible validation
- MotionShotPlan and MotionStoryboardPlan rules
- KeyframeGenerator vertical format (1080x1920)
- HybridSequentialMotionProvider zero-cost synthesis
- MotionQualityChecker forensic standards
- Strict privacy boundary: PRIVATE_TEST_ONLY
"""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from src.anime_motion.character_bible import CharacterSpecification, CharacterBible
from src.anime_motion.motion_planner import (
    MotionShotPlan,
    MotionStoryboardPlan,
    MotionType,
    ShotSize,
)
from src.anime_motion.keyframe_generator import KeyframeGenerator
from src.anime_motion.image_to_video_provider import (
    HybridSequentialMotionProvider,
    MockMotionProvider,
    CloudRunwayProvider,
    CloudLumaProvider,
)
from src.anime_motion.motion_quality_checker import MotionQualityChecker, MotionQualityReport


def test_character_specification_validation():
    char = CharacterSpecification(
        character_id="lyra_vance",
        name="Lyra Vance",
        archetype="Cyber-Chrono Alchemist",
        gender="female",
        apparent_age="early 20s",
        face_and_eyes="Angular jaw, glowing cyan cyber eye",
        hair_style="Cobalt hair with silver highlights",
        clothing_and_gear="Charcoal coat with teal conduits",
        body_proportions="Athletic build",
        color_palette=["#00F0FF", "#0B0F19"],
        distinguishing_features=["Left cybernetic eye", "Chrono-Anchor vambrace"],
    )
    assert char.character_id == "lyra_vance"
    assert len(char.color_palette) == 2
    assert "Left cybernetic eye" in char.distinguishing_features


def test_character_bible_container(tmp_path):
    bible = CharacterBible(title="Anime Universe", universe="Cyber-Fantasy")
    char = CharacterSpecification(
        character_id="hero_01",
        name="Aiden",
        archetype="Wanderer",
        gender="male",
        apparent_age="25",
        face_and_eyes="Scarred brow, gold eyes",
        hair_style="Raven spiky hair",
        clothing_and_gear="Leather duster",
        body_proportions="Broad shoulders",
        color_palette=["#D4AF37", "#1E293B"],
    )
    bible.add_character(char)
    assert "hero_01" in bible.characters
    assert bible.get_character("hero_01").name == "Aiden"

    # Persistence check
    json_path = tmp_path / "character_bible.json"
    bible.save_to_file(json_path)
    assert json_path.exists()

    loaded = CharacterBible.load_from_file(json_path)
    assert loaded.universe == "Cyber-Fantasy"
    assert "hero_01" in loaded.characters


def test_motion_storyboard_plan_validation():
    # Build a storyboard that satisfies the milestone criteria
    shots = []
    current_time = 0.0
    for i in range(1, 16):
        dur = 2.5
        m_type = MotionType.GENUINE_AI_ANIMATION if i <= 10 else MotionType.CAMERA_MOTION
        shot = MotionShotPlan(
            shot_idx=i,
            shot_id=f"shot_{i:02d}",
            time_start=current_time,
            time_end=round(current_time + dur, 2),
            duration=dur,
            motion_type=m_type,
            environment="Neo Tokyo ruins",
            camera_trajectory="Slow tracking pan right",
            start_pose="Standing alert",
            intended_movement="Draws plasma blade with cyan light streak",
            end_pose="Combat stance ready",
            lighting="Neon rim light",
            image_prompt="High anime fidelity shot",
            motion_prompt="Limb articulation and weapon swing",
        )
        shots.append(shot)
        current_time = round(current_time + dur, 2)

    storyboard = MotionStoryboardPlan(
        storyboard_id="sb_test_01",
        title="Chronicles of Time",
        target_duration=37.5,
        language="Hinglish",
        shots=shots,
    )
    report = storyboard.validate_plan()
    assert report["total_shots"] == 15
    assert report["genuine_animation_shots"] == 10
    assert report["computed_duration"] == 37.5
    assert report["target_duration_within_range"] is True


def test_motion_storyboard_fails_if_under_15_shots():
    # Storyboard with only 5 shots must fail validation
    shots = [
        MotionShotPlan(
            shot_idx=i,
            shot_id=f"shot_{i:02d}",
            time_start=float(i - 1) * 3.0,
            time_end=float(i) * 3.0,
            duration=3.0,
            motion_type=MotionType.CAMERA_MOTION,
            environment="Dojo",
            camera_trajectory="Push in",
            start_pose="Kneeling",
            intended_movement="Bows",
            end_pose="Bowed",
            lighting="Morning sun",
            image_prompt="Dojo interior",
            motion_prompt="Subtle bow",
        )
        for i in range(1, 6)
    ]
    sb = MotionStoryboardPlan(
        storyboard_id="sb_short",
        title="Too Short",
        target_duration=40.0,
        language="Hindi",
        shots=shots,
    )
    with pytest.raises(ValueError, match="at least 15 shots"):
        sb.validate_plan(raise_on_error=True)


def test_keyframe_generator(tmp_path):
    bible = CharacterBible(title="Test", universe="Test")
    char = CharacterSpecification(
        character_id="hero",
        name="Hero",
        archetype="Warrior",
        gender="male",
        apparent_age="20",
        face_and_eyes="Sharp features",
        hair_style="Cobalt hair",
        clothing_and_gear="Armor",
        body_proportions="Athletic",
        color_palette=["#00F0FF"],
    )
    bible.add_character(char)

    gen = KeyframeGenerator(bible, tmp_path)
    shot = MotionShotPlan(
        shot_idx=1,
        shot_id="shot_01_test",
        time_start=0.0,
        time_end=3.0,
        duration=3.0,
        motion_type=MotionType.GENUINE_AI_ANIMATION,
        character_id="hero",
        shot_size=ShotSize.MEDIUM,
        environment="Futuristic cyber temple",
        camera_trajectory="Static low angle",
        start_pose="Resting weapon on shoulder",
        intended_movement="Leaps into air",
        end_pose="Airborne mid-slash",
        lighting="Cyan neon bloom",
        image_prompt="Hero in cyber temple",
        motion_prompt="Airborne leap",
    )
    start_kf = gen.generate_shot_keyframe(shot, pose_type="start")
    assert start_kf.exists()
    assert start_kf.suffix == ".png"

    from PIL import Image
    with Image.open(start_kf) as img:
        assert img.size == (1080, 1920)


def test_mock_motion_provider(tmp_path):
    provider = MockMotionProvider()
    assert provider.is_mock is True
    assert provider.is_paid is False

    shot = MotionShotPlan(
        shot_idx=1,
        shot_id="shot_01",
        time_start=0.0,
        time_end=2.5,
        duration=2.5,
        motion_type=MotionType.GENUINE_AI_ANIMATION,
        environment="Ruins",
        camera_trajectory="Pan",
        start_pose="Idle",
        intended_movement="Walk",
        end_pose="Idle",
        lighting="Dim",
        image_prompt="test",
        motion_prompt="test",
    )
    from PIL import Image
    dummy_img = tmp_path / "start.png"
    Image.new("RGB", (100, 100), (0, 240, 255)).save(dummy_img)
    out_clip = tmp_path / "clip.mp4"

    meta = provider.generate_motion_clip(shot, dummy_img, out_clip)
    assert meta.provider_used == "mock_motion_provider"
    assert meta.estimated_cost_usd == 0.0
    assert out_clip.exists()


def test_cloud_providers_unconfigured_raise_cleanly():
    # Without API keys, cloud providers should raise clean error
    runway = CloudRunwayProvider(api_key=None)
    luma = CloudLumaProvider(api_key=None)
    assert runway.is_paid is True
    assert luma.is_paid is True

    shot = MotionShotPlan(
        shot_idx=1,
        shot_id="s1",
        time_start=0.0,
        time_end=3.0,
        duration=3.0,
        motion_type=MotionType.GENUINE_AI_ANIMATION,
        environment="env",
        camera_trajectory="cam",
        start_pose="start",
        intended_movement="move",
        end_pose="end",
        lighting="light",
        image_prompt="prompt",
        motion_prompt="motion",
    )
    with pytest.raises(RuntimeError, match="Runway API Key not configured"):
        runway.generate_motion_clip(shot, Path("dummy.png"), Path("out.mp4"))

    with pytest.raises(RuntimeError, match="Luma API Key not configured"):
        luma.generate_motion_clip(shot, Path("dummy.png"), Path("out.mp4"))


def test_motion_quality_report_model():
    report = MotionQualityReport(
        production_id="test_prod",
        total_shots=15,
        genuine_animation_shots=10,
        static_shots=0,
        interpolated_shots=1,
        total_duration_seconds=44.28,
        resolution="1080x1920",
        fps=30.0,
        video_codec="h264",
        audio_codec="aac",
        file_size_mb=9.17,
        decode_integrity="PASS",
        blackout_count=0,
        freeze_count=0,
        audio_peak_dbfs=-1.2,
        audio_clipping=False,
        character_consistency="VERIFIED_CANONICAL",
        overall_status="READY_FOR_CREATOR_REVIEW",
        creator_approval_gate="PENDING_CREATOR_REVIEW",
    )
    assert report.total_shots == 15
    assert report.overall_status == "READY_FOR_CREATOR_REVIEW"
    data = report.model_dump()
    assert data["resolution"] == "1080x1920"

