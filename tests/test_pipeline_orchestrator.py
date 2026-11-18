"""Comprehensive offline unit and integration tests for Pipeline Orchestrator and Safety Gates."""

from datetime import datetime, timezone
import os
from pathlib import Path
import struct
from unittest.mock import MagicMock, patch
import wave
import pytest
from PIL import Image

from src.audio_engine.models import AudioMixResult, BGMTrackMetadata, TimestampBoundary, VoiceSynthesisResult
from src.caption_generator.models import CaptionFormat, CaptionItem, CaptionStyle
from src.caption_generator.service import SubtitleGenerator
from src.common.logger import setup_logger
from src.image_engine.models import GeneratedImageMetadata, SceneImageStatus, StoryboardImageManifest
from src.pipeline.cli import handle_list, handle_prepare, handle_report, handle_status, handle_validate
from src.pipeline.exceptions import (
    ConcurrentPipelineExecutionError,
    HumanApprovalRequiredError,
    MissingAudioAssetError,
    MissingSceneImageError,
    MockAssetQuarantineError,
    QualityGateError,
    ScientificClaimUnverifiedError,
    ScriptNotApprovedError,
    UploadDisabledError,
    VideoRenderingError,
)
from src.pipeline.models import (
    PipelineConfig,
    PipelineProductionState,
    PipelineStage,
    StageStatus,
)
from src.pipeline.orchestrator import PipelineOrchestrator
from src.pipeline.recovery import PipelineRecoveryManager
from src.pipeline.reporter import PipelineReporter
from src.pipeline.state_manager import PipelineStateManager
from src.pipeline.validators import PipelineGatekeeper
from src.quality_checker.models import CheckSeverity, QualityCheckResult, QualityReport, QualityStatus
from src.research_engine.models import VerificationStatus
from src.script_manager.models import ContentCategory, Script, ScriptStatus
from src.storage_manager.models import CleanupStatus, ProductionAssetType, ProductionPackage
from src.storage_manager.service import StorageManager
from src.storyboard_generator.models import (
    CameraMovement,
    ScientificClaimVerification,
    StoryboardDossier,
    StoryboardScene,
    VisualConsistencyProfile,
)
from src.video_editor.models import VideoRenderResult
from src.youtube_uploader.approval import UploadApprovalGate
from src.youtube_uploader.models import PrivacyStatus, UploadApprovalRecord, UploadMetadata

logger = setup_logger("test_pipeline_orchestrator")


# --- Test Fixtures ---

@pytest.fixture
def sample_script():
    """Approved Script fixture."""
    return Script(
        id="sc_orch_test_01",
        title="Chronobiology Science",
        category=ContentCategory.ANIME_SCIENCE,
        hook="Opening hook question about Chronobiology",
        body="Core narrative and scientific explanation of chronometry",
        takeaway="Concluding scientific reflection",
        target_duration_seconds=30.0,
        status=ScriptStatus.APPROVED,
    )


@pytest.fixture
def sample_storyboard():
    """Fully verified StoryboardDossier fixture with verified scientific claims."""
    vc = VisualConsistencyProfile(
        character_name="Chronos Scientist",
        facial_features="Sharp focused eyes",
        hairstyle="Spiky green-to-white gradient hair",
        clothing_and_attire="Science tunic",
        color_palette="Emerald green, futuristic grey",
    )
    claim = ScientificClaimVerification(
        claim="Counting seconds activates the prefrontal cortex.",
        source_title="Neuroscience Journal",
        url="https://doi.org/10.1016/sample",
        verification_status=VerificationStatus.HUMAN_CHECKED,
        is_verified=True,
    )
    scenes = [
        StoryboardScene(
            scene_number=1,
            narration_hinglish="Kya aapko lagta hai ki insaan hazaron saal tak deep sleep mein jaag sakta tha?",
            narration_english_meaning="Do you think a human could stay awake in stasis for centuries?",
            camera_angle="eye-level",
            framing="medium-close-up",
            subject_placement="center",
            camera_movement=CameraMovement.SLOW_ZOOM_IN,
            image_prompt_positive="Scientist in stasis chamber with energy field",
            suggested_duration_seconds=14.0,
            sound_effect_cue="sfx_stone_crack",
        ),
        StoryboardScene(
            scene_number=2,
            narration_hinglish="Real neuroscience kehti hai ki rhythm consciousness ko lock karti hai.",
            narration_english_meaning="Real neuroscience says internal rhythm locks consciousness.",
            camera_angle="low-angle",
            framing="close-up",
            subject_placement="center",
            camera_movement=CameraMovement.STATIC_DRIFT,
            image_prompt_positive="Neural synapses pulsing in brain",
            suggested_duration_seconds=14.0,
            sound_effect_cue="sfx_electric_hum",
        ),
    ]
    return StoryboardDossier(
        storyboard_id="sb_orch_test_01",
        title="Chronobiology Science",
        topic="Time Perception in Chronobiology",
        target_duration_seconds=30.0,
        pause_budget_seconds=2.0,
        hook="Opening hook text",
        body="Body narrative text",
        takeaway="Takeaway reflection text",
        visual_consistency=vc,
        scenes=scenes,
        scientific_claims=[claim],
        has_unverified_claims=False,
    )


@pytest.fixture
def genuine_audio_files(tmp_path):
    """Create genuine WAV audio files on disk."""
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    def _write_wav(filename, duration_sec=4.0):
        path = audio_dir / filename
        sample_rate = 44100
        num_samples = int(sample_rate * duration_sec)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            data = bytearray(num_samples * 2)
            for i in range(num_samples):
                val = int(32767.0 * 0.1 * (1.0 if (i % 100) < 50 else -1.0))
                struct.pack_into("<h", data, i * 2, val)
            wf.writeframes(data)
        return path

    voice_wav = _write_wav("voiceover.wav", duration_sec=10.0)
    mixed_wav = _write_wav("final_mix.wav", duration_sec=10.0)
    bgm_wav = _write_wav("bgm.wav", duration_sec=15.0)

    voice_res = VoiceSynthesisResult(
        audio_path=str(voice_wav),
        duration_seconds=10.0,
        provider="edge_tts",
        voice_id="hi-IN-MadhurNeural",
        file_size_bytes=voice_wav.stat().st_size,
        is_mock_asset=False,
        cost_usd=0.0,
        boundaries=[
            TimestampBoundary(text="Kya", offset_ms=0, duration_ms=500),
            TimestampBoundary(text="aapko", offset_ms=500, duration_ms=500),
        ],
    )

    mix_res = AudioMixResult(
        mixed_audio_path=str(mixed_wav),
        duration_seconds=10.0,
        voiceover_duration=10.0,
        voiceover_path=str(voice_wav),
        bgm_path=str(bgm_wav),
        is_mock_asset=False,
        lufs_level=-14.0,
    )

    bgm_meta = BGMTrackMetadata(
        track_id="bgm_01",
        title="Ambient Sci-Fi",
        artist="YouTube Audio Library",
        category="ambient",
        license_type="YouTube Audio Library (Free / No Attribution)",
        file_path=str(bgm_wav),
        duration_seconds=15.0,
        is_file_on_disk=True,
    )

    return voice_res, mix_res, bgm_meta


@pytest.fixture
def genuine_image_manifest(sample_storyboard, tmp_path):
    """Create genuine 1080x1920 images on disk with an approved manifest."""
    img_dir = tmp_path / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    metadata_list = []
    for s in sample_storyboard.scenes:
        img_path = img_dir / f"scene_{s.scene_number}.png"
        img = Image.new("RGB", (1080, 1920), color=(30 * s.scene_number, 60, 90))
        img.save(str(img_path))

        meta = GeneratedImageMetadata(
            scene_number=s.scene_number,
            image_path=str(img_path),
            provider="test_provider",
            model_id="test_model",
            prompt_used=s.image_prompt_positive,
            width=1080,
            height=1920,
            is_mock_asset=False,
            cost_usd=0.0,
            status=SceneImageStatus.APPROVED,
            reviewer_notes="Approved for test production",
        )
        metadata_list.append(meta)

    return StoryboardImageManifest(
        storyboard_id=sample_storyboard.storyboard_id,
        total_scenes=len(sample_storyboard.scenes),
        has_mock_assets=False,
        images=metadata_list,
    )


# --- 1. Script & Research Gating Tests ---

def test_gate_a_script_approval_success(sample_script):
    """Approved script passes Gate A without exception."""
    PipelineGatekeeper.validate_gate_a_script(sample_script)


def test_gate_a_script_pending_or_rejected_blocks(sample_script):
    """Pending or rejected scripts must be blocked with ScriptNotApprovedError."""
    sample_script.status = ScriptStatus.PENDING_REVIEW
    with pytest.raises(ScriptNotApprovedError, match="Gate A Violation"):
        PipelineGatekeeper.validate_gate_a_script(sample_script)

    sample_script.status = ScriptStatus.REJECTED
    with pytest.raises(ScriptNotApprovedError, match="Gate A Violation"):
        PipelineGatekeeper.validate_gate_a_script(sample_script)


def test_gate_b_research_verification_success(sample_storyboard, sample_script):
    """Storyboard with verified claims passes Gate B."""
    PipelineGatekeeper.validate_gate_b_research(sample_storyboard, sample_script)


def test_gate_b_research_unverified_claims_blocks(sample_storyboard, sample_script):
    """Storyboard flagged with unverified claims blocks at Gate B."""
    sample_storyboard.has_unverified_claims = True
    with pytest.raises(ScientificClaimUnverifiedError, match="unverified scientific claim"):
        PipelineGatekeeper.validate_gate_b_research(sample_storyboard, sample_script)


def test_gate_b_research_missing_citations_blocks(sample_storyboard, sample_script):
    """Claims without citation URLs or titles block at Gate B."""
    sample_storyboard.scientific_claims[0].url = ""
    with pytest.raises(ScientificClaimUnverifiedError, match="missing citation URL or title"):
        PipelineGatekeeper.validate_gate_b_research(sample_storyboard, sample_script)


# --- 2. Images Gating Tests ---

def test_gate_c_images_valid_manifest(sample_storyboard, genuine_image_manifest):
    """Fully approved real images pass Gate C."""
    PipelineGatekeeper.validate_gate_c_images(sample_storyboard, genuine_image_manifest)


def test_gate_c_images_missing_scene_blocks(sample_storyboard, genuine_image_manifest):
    """Missing a scene image must block at Gate C."""
    genuine_image_manifest.images.pop()
    with pytest.raises(MissingSceneImageError, match="has missing images for scenes"):
        PipelineGatekeeper.validate_gate_c_images(sample_storyboard, genuine_image_manifest)


def test_gate_c_images_mock_asset_quarantined(sample_storyboard, genuine_image_manifest):
    """Mock image asset must be quarantined at Gate C."""
    genuine_image_manifest.images[0].is_mock_asset = True
    genuine_image_manifest.has_mock_assets = True
    with pytest.raises(MockAssetQuarantineError, match="contains MOCK visual assets"):
        PipelineGatekeeper.validate_gate_c_images(sample_storyboard, genuine_image_manifest)


def test_gate_c_images_unapproved_blocks(sample_storyboard, genuine_image_manifest):
    """Unapproved image must block at Gate C with HumanApprovalRequiredError."""
    genuine_image_manifest.images[0].status = SceneImageStatus.PENDING_IMAGE_REVIEW
    with pytest.raises(HumanApprovalRequiredError, match="awaiting human approval"):
        PipelineGatekeeper.validate_gate_c_images(sample_storyboard, genuine_image_manifest)


# --- 3. Audio Gating Tests ---

def test_gate_d_audio_valid(genuine_audio_files):
    """Valid voice and mix results pass Gate D."""
    voice_res, mix_res, bgm_meta = genuine_audio_files
    PipelineGatekeeper.validate_gate_d_audio(voice_res, bgm_track=bgm_meta, require_bgm=True)


def test_gate_d_audio_mock_voice_quarantined(genuine_audio_files):
    """Mock voice audio must be quarantined at Gate D."""
    voice_res, mix_res, bgm_meta = genuine_audio_files
    voice_res.is_mock_asset = True
    with pytest.raises(MockAssetQuarantineError, match="MOCK asset"):
        PipelineGatekeeper.validate_gate_d_audio(voice_res, bgm_track=bgm_meta, require_bgm=True)


def test_gate_d_audio_missing_or_empty_file(genuine_audio_files, tmp_path):
    """Non-existent or zero-byte audio files must be blocked at Gate D."""
    voice_res, mix_res, bgm_meta = genuine_audio_files
    empty_wav = tmp_path / "empty.wav"
    empty_wav.write_bytes(b"")

    voice_res.audio_path = str(empty_wav)
    with pytest.raises(MissingAudioAssetError, match="missing or 0 bytes"):
        PipelineGatekeeper.validate_gate_d_audio(voice_res, bgm_track=bgm_meta, require_bgm=True)


# --- 4. Captions Gating Tests ---

def test_caption_generation_hindi_unicode(tmp_path):
    """SubtitleGenerator creates valid UTF-8 SRT/ASS captions with Hindi unicode."""
    generator = SubtitleGenerator()
    boundaries = [
        TimestampBoundary(text="Kya", offset_ms=0, duration_ms=400),
        TimestampBoundary(text="aapko", offset_ms=450, duration_ms=350),
        TimestampBoundary(text="लगता", offset_ms=850, duration_ms=350),
        TimestampBoundary(text="hai", offset_ms=1250, duration_ms=350),
    ]

    items = generator.build_caption_items(boundaries)
    assert len(items) == 4

    srt_path = tmp_path / "test.srt"
    ass_path = tmp_path / "test.ass"

    generator.export_srt(items, srt_path)
    generator.export_ass(items, ass_path)

    assert srt_path.exists()
    assert ass_path.exists()

    srt_text = srt_path.read_text(encoding="utf-8")
    ass_text = ass_path.read_text(encoding="utf-8")

    assert "लगता" in srt_text
    assert "लगता" in ass_text
    assert "\ufffd" not in srt_text
    assert "\ufffd" not in ass_text


# --- 5. Video Rendering Gating Tests ---

def test_gate_e_video_valid(tmp_path):
    """Valid video file and clean QualityReport pass Gate E."""
    video_path = tmp_path / "output.mp4"
    video_path.write_bytes(b"\x00" * 1024)

    report = QualityReport(
        production_id="test_p1",
        video_path=str(video_path),
        overall_status=QualityStatus.PASS,
        is_upload_eligible=True,
    )

    PipelineGatekeeper.validate_gate_e_video(video_path, report)


def test_gate_e_video_quality_failure_blocks(tmp_path):
    """Quality report with FAIL status must block Gate E."""
    video_path = tmp_path / "output.mp4"
    video_path.write_bytes(b"\x00" * 1024)

    check = QualityCheckResult(
        check_name="test_check",
        category="video",
        status=QualityStatus.FAIL,
        severity=CheckSeverity.CRITICAL,
        message="Critical visual artifact",
    )
    report = QualityReport(
        production_id="test_p1",
        video_path=str(video_path),
        overall_status=QualityStatus.FAIL,
        checks=[check],
        is_upload_eligible=False,
    )

    with pytest.raises(QualityGateError, match="rejected video with 1 failure"):
        PipelineGatekeeper.validate_gate_e_video(video_path, report)


def test_gate_e_video_not_checked_blocks(tmp_path):
    """Quality report with NOT_CHECKED status must block Gate E."""
    video_path = tmp_path / "output.mp4"
    video_path.write_bytes(b"\x00" * 1024)

    check = QualityCheckResult(
        check_name="audio_lufs",
        category="audio",
        status=QualityStatus.NOT_CHECKED,
        severity=CheckSeverity.WARNING,
        message="Skipped check",
    )
    report = QualityReport(
        production_id="test_p1",
        video_path=str(video_path),
        overall_status=QualityStatus.PASS,
        checks=[check],
        is_upload_eligible=False,
    )

    with pytest.raises(QualityGateError, match="Incomplete inspection"):
        PipelineGatekeeper.validate_gate_e_video(video_path, report)


# --- 6. Pre-Upload Human Approval Gating Tests ---

def test_gate_f_upload_approval_valid(tmp_path):
    """Valid cryptographic approval record passes Gate F."""
    video_path = tmp_path / "final.mp4"
    video_path.write_bytes(b"sample video bytes for sha")

    meta = UploadMetadata(
        title="Chronobiology Science",
        description="YouTube-for-All Shorts explanation #shorts #science",
        tags=["chronobiology", "science"],
        privacy_status=PrivacyStatus.PRIVATE,
        made_for_kids=False,
    )
    qr = QualityReport(
        production_id="prod_01",
        video_path=str(video_path),
        overall_status=QualityStatus.PASS,
        is_upload_eligible=True,
    )

    record = UploadApprovalGate.create_approval_record(
        production_id="prod_01",
        video_path=video_path,
        metadata=meta,
        quality_report=qr,
        approver_notes="Approved by Human Reviewer",
        accept_warnings=True,
    )

    PipelineGatekeeper.validate_gate_f_upload_approval(record, video_path=video_path, metadata=meta)


def test_gate_f_upload_approval_tampered_blocks(tmp_path):
    """Approval record with tampered checksum blocks Gate F."""
    video_path = tmp_path / "final.mp4"
    video_path.write_bytes(b"sample video bytes for sha")

    meta = UploadMetadata(
        title="Chronobiology Science",
        description="YouTube-for-All Shorts explanation #shorts #science",
        tags=["chronobiology", "science"],
        privacy_status=PrivacyStatus.PRIVATE,
        made_for_kids=False,
    )
    qr = QualityReport(
        production_id="prod_01",
        video_path=str(video_path),
        overall_status=QualityStatus.PASS,
        is_upload_eligible=True,
    )

    record = UploadApprovalGate.create_approval_record(
        production_id="prod_01",
        video_path=video_path,
        metadata=meta,
        quality_report=qr,
        approver_notes="Approved by Human Reviewer",
        accept_warnings=True,
    )
    record.video_checksum = "bad_tampered_checksum"

    with pytest.raises(HumanApprovalRequiredError, match="Gate F Security Violation"):
        PipelineGatekeeper.validate_gate_f_upload_approval(record, video_path=video_path, metadata=meta)


# --- 7. State Manager & Concurrency Lock Tests ---

def test_pipeline_state_manager_atomic_persistence(tmp_path):
    """StateManager persists and loads state atomically."""
    sm = PipelineStateManager(base_productions_dir=tmp_path / "prods", state_dir=tmp_path / "state")
    state = sm.init_production_state(
        production_id="prod_test_persist",
        script_id="sc_test_01",
        storyboard_id="sb_test_01",
    )

    assert state.current_stage == PipelineStage.SCRIPT_SELECTION
    sm.record_stage_completed(
        production_id="prod_test_persist",
        stage=PipelineStage.SCRIPT_SELECTION,
        notes="Selected successfully",
    )

    loaded = sm.get_state("prod_test_persist")
    assert loaded is not None
    assert loaded.stages[PipelineStage.SCRIPT_SELECTION.value].status == StageStatus.COMPLETED


def test_pipeline_state_manager_concurrency_lock(tmp_path):
    """Concurrent execution of the same production ID is blocked."""
    sm = PipelineStateManager(base_productions_dir=tmp_path / "prods", state_dir=tmp_path / "state")
    sm.acquire_lock("prod_concurrent")

    # Second attempt should raise ConcurrentPipelineExecutionError
    with pytest.raises(ConcurrentPipelineExecutionError, match="is currently running in another process"):
        sm.acquire_lock("prod_concurrent")

    sm.release_lock("prod_concurrent")

    # After release, acquire should succeed
    sm.acquire_lock("prod_concurrent")
    sm.release_lock("prod_concurrent")


# --- 8. Crash Recovery Manager Tests ---

def test_recovery_manager_checkpoint_calculation(tmp_path, sample_storyboard):
    """Recovery manager calculates resume stage from verified disk assets."""
    prods_dir = tmp_path / "prods"
    state_dir = tmp_path / "state"
    sm = PipelineStateManager(base_productions_dir=prods_dir, state_dir=state_dir)
    recovery = PipelineRecoveryManager(state_manager=sm)

    prod_id = "prod_recover_test"
    sb_id = sample_storyboard.storyboard_id
    state = sm.init_production_state(prod_id, "sc_test", sb_id)

    pkg_dir = prods_dir / sb_id / prod_id
    pkg_dir.mkdir(parents=True, exist_ok=True)
    images_dir = pkg_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Put genuine images for scene 1 and 2
    for s in sample_storyboard.scenes:
        img_p = images_dir / f"scene_{s.scene_number}.png"
        img = Image.new("RGB", (1080, 1920), color=(10, 20, 30))
        img.save(str(img_p))

    # Record script selection, validation, research, storyboard, package, image as completed
    sm.record_stage_completed(prod_id, PipelineStage.SCRIPT_SELECTION)
    sm.record_stage_completed(prod_id, PipelineStage.SCRIPT_VALIDATION)
    sm.record_stage_completed(prod_id, PipelineStage.RESEARCH_VERIFICATION)
    sm.record_stage_completed(prod_id, PipelineStage.STORYBOARD_VALIDATION)
    sm.record_stage_completed(prod_id, PipelineStage.PACKAGE_CREATION)
    sm.record_stage_completed(prod_id, PipelineStage.IMAGE_VALIDATION)

    # Next stage should be VOICE_SYNTHESIS
    plan = recovery.calculate_recovery_plan(prod_id, sample_storyboard)
    assert plan["can_resume"] is True
    assert plan["resume_stage"] == PipelineStage.VOICE_SYNTHESIS.value


def test_recovery_manager_invalidates_missing_or_corrupted_asset(tmp_path, sample_storyboard):
    """Corrupted or missing assets invalidate stage in recovery plan."""
    prods_dir = tmp_path / "prods"
    state_dir = tmp_path / "state"
    sm = PipelineStateManager(base_productions_dir=prods_dir, state_dir=state_dir)
    recovery = PipelineRecoveryManager(state_manager=sm)

    prod_id = "prod_corrupt_test"
    sb_id = sample_storyboard.storyboard_id
    sm.init_production_state(prod_id, "sc_test", sb_id)

    pkg_dir = prods_dir / sb_id / prod_id
    pkg_dir.mkdir(parents=True, exist_ok=True)
    images_dir = pkg_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Empty 0-byte image file
    corrupt_img = images_dir / "scene_1.png"
    corrupt_img.write_bytes(b"")

    sm.record_stage_completed(
        prod_id,
        PipelineStage.IMAGE_VALIDATION,
        output_assets={"scene_1": str(corrupt_img)},
    )

    plan = recovery.calculate_recovery_plan(prod_id, sample_storyboard)
    assert PipelineStage.IMAGE_VALIDATION.value in plan["invalidated_stages"]


# --- 9. Pipeline Orchestrator Integration & Upload Gating Tests ---

def test_pipeline_orchestrator_end_to_end_upload_disabled(
    tmp_path,
    sample_script,
    sample_storyboard,
    genuine_audio_files,
    genuine_image_manifest,
):
    """Pipeline runs through video rendering, QA, approval, and stops before YouTube upload."""
    voice_res, mix_res, bgm_meta = genuine_audio_files
    storage_mgr = StorageManager(
        base_productions_dir=tmp_path / "prods",
        manifest_dir=tmp_path / "storage_manifests",
    )
    state_mgr = PipelineStateManager(
        base_productions_dir=tmp_path / "prods",
        state_dir=tmp_path / "state",
    )

    # Mock subsystems
    mock_script_mgr = MagicMock()
    mock_script_mgr.get_approved_scripts.return_value = [sample_script]
    mock_script_mgr.get_script.return_value = sample_script

    mock_res_engine = MagicMock()
    mock_img_engine = MagicMock()
    mock_img_engine.prepare_storyboard_prompts.return_value = genuine_image_manifest
    mock_img_engine.get_manifest.return_value = genuine_image_manifest
    mock_img_engine.inspect_storyboard_images.return_value = MagicMock(is_ready_for_video=True)

    mock_audio_engine = MagicMock()
    mock_audio_engine.synthesize_voiceover.return_value = voice_res
    mock_audio_engine.bgm_manager.get_track_for_mood.return_value = bgm_meta
    mock_audio_engine.mix_storyboard_audio.return_value = mix_res

    mock_caption_gen = MagicMock()
    def fake_export_srt(items, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("1\n00:00:00,000 --> 00:00:01,000\nHello", encoding="utf-8")
        return Path(path)

    def fake_export_ass(items, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("[Script Info]\nTitle: Test", encoding="utf-8")
        return Path(path)

    mock_caption_gen.build_caption_items.return_value = [MagicMock()]
    mock_caption_gen.export_srt.side_effect = fake_export_srt
    mock_caption_gen.export_ass.side_effect = fake_export_ass

    # Mock video editor render result
    fake_video = tmp_path / "final_render.mp4"
    fake_video.write_bytes(b"dummy video content")
    mock_video_editor = MagicMock()
    render_res_obj = VideoRenderResult(
        video_path=str(fake_video),
        duration_seconds=10.0,
        resolution="1080x1920",
        fps=30,
        file_size_bytes=len(fake_video.read_bytes()),
    )
    mock_video_editor.render_short_video.return_value = render_res_obj
    mock_video_editor.render_shorts_video.return_value = render_res_obj

    # Mock quality checker clean report
    mock_quality_checker = MagicMock()
    clean_qr = QualityReport(
        production_id="prod_test",
        video_path=str(fake_video),
        overall_status=QualityStatus.PASS,
        checks=[],
        is_upload_eligible=True,
    )
    mock_quality_checker.run_full_check.return_value = clean_qr
    mock_quality_checker.check_production.return_value = clean_qr

    # Mock YouTube uploader (MUST NEVER BE CALLED)
    mock_uploader = MagicMock()

    orchestrator = PipelineOrchestrator(
        script_manager=mock_script_mgr,
        research_engine=mock_res_engine,
        image_engine=mock_img_engine,
        audio_engine=mock_audio_engine,
        caption_generator=mock_caption_gen,
        video_editor=mock_video_editor,
        quality_checker=mock_quality_checker,
        youtube_uploader=mock_uploader,
        storage_manager=storage_mgr,
        state_manager=state_mgr,
        config=PipelineConfig(
            upload_enabled=False,  # Strict default
            require_human_approval=True,
            allow_synthetic_audio=False,
        ),
    )

    # Save storyboard dossier in storage
    storage_mgr.save_storyboard_dossier(sample_storyboard)

    # Run pipeline with explicit human approval confirmation
    final_state = orchestrator.run_pipeline(
        script_id=sample_script.script_id,
        storyboard=sample_storyboard,
        approver_notes="Human Director approved",
        human_approval_confirmed=True,
    )

    # Verify pipeline completed video production
    assert final_state.current_stage == PipelineStage.UPLOAD_PREPARATION
    assert final_state.overall_status == StageStatus.COMPLETED

    # Verify upload was NOT performed
    assert mock_uploader.upload_video.call_count == 0
    assert final_state.stages[PipelineStage.UPLOAD_PREPARATION.value].status == StageStatus.COMPLETED

    # Verify output video registered in storage
    pkg = storage_mgr.load_production_package(final_state.production_id)
    assert pkg is not None
    video_assets = [a for a in pkg.assets if a.asset_type == ProductionAssetType.FINAL_VIDEO]
    assert len(video_assets) > 0
    assert Path(video_assets[0].file_path).name == Path(fake_video).name
    assert pkg.upload_record.cleanup_status in (CleanupStatus.PRESERVED, CleanupStatus.PENDING)


# --- 10. Pipeline CLI Handlers Tests ---

def test_cli_handlers(tmp_path, sample_script, sample_storyboard, monkeypatch):
    """Test CLI commands: status, list, prepare, validate, report."""
    state_mgr = PipelineStateManager(
        base_productions_dir=tmp_path / "prods",
        state_dir=tmp_path / "state",
    )
    storage_mgr = StorageManager(
        base_productions_dir=tmp_path / "prods",
        manifest_dir=tmp_path / "storage_manifests",
    )

    storage_mgr.save_storyboard_dossier(sample_storyboard)
    prod_id = "prod_cli_test"
    state = state_mgr.init_production_state(prod_id, sample_script.script_id, sample_storyboard.storyboard_id)

    # Patch settings and instances in cli module
    monkeypatch.setattr("src.pipeline.cli.PipelineStateManager", lambda **kw: state_mgr)
    monkeypatch.setattr("src.pipeline.cli.StorageManager", lambda **kw: storage_mgr)

    # 1. status
    class StatusArgs:
        production_id = prod_id
        json = False
    ret = handle_status(StatusArgs())
    assert ret == 0

    # 2. list
    class ListArgs:
        json = False
    ret = handle_list(ListArgs())
    assert ret == 0

    # 3. report
    class ReportArgs:
        production_id = prod_id
    ret = handle_report(ReportArgs())
    assert ret == 0


def test_run_pipeline_without_human_approval_fails_closed(tmp_path, sample_script, sample_storyboard, monkeypatch):
    """Verify that run_pipeline strictly fails closed and NEVER auto-approves passing QA."""
    from unittest.mock import MagicMock
    from src.pipeline.exceptions import HumanApprovalRequiredError

    fake_video = tmp_path / "fake_video.mp4"
    fake_video.write_bytes(b"MP4_DATA" * 500)

    orchestrator = PipelineOrchestrator(
        storage_manager=StorageManager(base_productions_dir=tmp_path / "prods", manifest_dir=tmp_path / "manifests"),
        state_manager=PipelineStateManager(base_productions_dir=tmp_path / "prods", state_dir=tmp_path / "state"),
    )
    orchestrator.storage_manager.save_storyboard_dossier(sample_storyboard)

    # Mock stages 1-12 as passing
    monkeypatch.setattr(orchestrator, "select_and_validate_script", lambda **kw: sample_script)
    monkeypatch.setattr(orchestrator, "verify_research", lambda *a, **kw: True)
    monkeypatch.setattr(orchestrator, "validate_storyboard", lambda *a, **kw: True)
    monkeypatch.setattr(orchestrator, "prepare_and_validate_images", lambda *a, **kw: MagicMock(scenes=[]))
    monkeypatch.setattr(orchestrator, "synthesize_voiceover", lambda *a, **kw: MagicMock(audio_path=str(fake_video), is_mock_asset=False))
    monkeypatch.setattr(orchestrator, "generate_captions", lambda *a, **kw: (tmp_path / "captions.srt", tmp_path / "captions.ass"))
    monkeypatch.setattr(orchestrator, "select_and_mix_audio", lambda *a, **kw: MagicMock(mixed_audio_path=str(fake_video), is_synthetic_mix=False, duration_seconds=30.0, sfx_count=0, bgm_track_id=None))
    monkeypatch.setattr(orchestrator, "render_video", lambda *a, **kw: MagicMock(output_path=fake_video, video_path=fake_video, width=1080, height=1920, fps=30, duration_seconds=30.0, is_mock_asset=False))
    monkeypatch.setattr(orchestrator, "run_quality_checks", lambda *a, **kw: MagicMock(overall_status=QualityStatus.PASS, is_upload_eligible=True, total_failures=0, total_warnings=0))

    # Calling run_pipeline without human_approval_confirmed must fail closed
    with pytest.raises(HumanApprovalRequiredError, match="human approval cannot be issued automatically"):
        orchestrator.run_pipeline(
            script_id=sample_script.script_id,
            storyboard=sample_storyboard,
            human_approval_confirmed=False,
        )


def test_resume_production_without_human_approval_fails_closed(tmp_path, sample_script, sample_storyboard, monkeypatch):
    """Verify that resume_production strictly fails closed when reaching approval without explicit human confirmation."""
    from unittest.mock import MagicMock
    from src.pipeline.exceptions import HumanApprovalRequiredError

    fake_video = tmp_path / "fake_video.mp4"
    fake_video.write_bytes(b"MP4_DATA" * 500)

    orchestrator = PipelineOrchestrator(
        storage_manager=StorageManager(base_productions_dir=tmp_path / "prods", manifest_dir=tmp_path / "manifests"),
        state_manager=PipelineStateManager(base_productions_dir=tmp_path / "prods", state_dir=tmp_path / "state"),
    )
    pkg = orchestrator.storage_manager.create_production_package(
        storyboard_id=sample_storyboard.storyboard_id,
        production_id="prod_resume_test_01",
    )
    orchestrator.storage_manager.save_storyboard_dossier(sample_storyboard)

    # Mock recovery manager to resume at human review or quality check
    st = orchestrator.state_manager.init_production_state(
        production_id="prod_resume_test_01",
        script_id=sample_script.script_id,
        storyboard_id=sample_storyboard.storyboard_id,
    )
    monkeypatch.setattr(
        orchestrator.recovery_manager,
        "recover_production",
        lambda *a, **kw: (st, {"resume_stage": PipelineStage.QUALITY_CHECK.value}),
    )
    monkeypatch.setattr(orchestrator, "prepare_and_validate_images", lambda *a, **kw: MagicMock(scenes=[]))
    monkeypatch.setattr(orchestrator, "synthesize_voiceover", lambda *a, **kw: MagicMock(audio_path=str(fake_video), is_mock_asset=False))
    monkeypatch.setattr(orchestrator, "generate_captions", lambda *a, **kw: (tmp_path / "captions.srt", tmp_path / "captions.ass"))
    monkeypatch.setattr(orchestrator, "render_video", lambda *a, **kw: MagicMock(output_path=fake_video, video_path=fake_video, width=1080, height=1920, fps=30, duration_seconds=30.0, is_mock_asset=False))
    monkeypatch.setattr(orchestrator, "run_quality_checks", lambda *a, **kw: MagicMock(overall_status=QualityStatus.PASS, is_upload_eligible=True, total_failures=0, total_warnings=0))

    # Resuming without human_approval_confirmed must fail closed
    with pytest.raises(HumanApprovalRequiredError, match="human approval cannot be issued automatically during resumption"):
        orchestrator.resume_production(
            production_id="prod_resume_test_01",
            storyboard=sample_storyboard,
            script=sample_script,
            human_approval_confirmed=False,
        )
