"""Unit and integration tests for Video Assembly Engine, FFmpeg Runner, and Filtergraph Builder."""

from datetime import datetime, timezone
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from PIL import Image

from src.audio_engine.models import AudioMixResult, TimestampBoundary, VoiceSynthesisResult
from src.image_engine.exceptions import (
    ImageReviewRequiredError,
    MockAssetProductionBlockedError,
    ProductionEligibilityBlockedError,
)
from src.image_engine.models import GeneratedImageMetadata, SceneImageStatus, StoryboardImageManifest
from src.script_manager.models import ContentCategory, Script, ScriptStatus
from src.storage_manager.models import ProductionAsset, ProductionAssetType, ProductionPackage
from src.research_engine.models import VerificationStatus
from src.storage_manager.security_guard import PathSecurityGuard
from src.storage_manager.service import StorageManager
from src.storyboard_generator.models import (
    CameraMovement,
    ScientificClaimVerification,
    StoryboardDossier,
    StoryboardScene,
    VisualConsistencyProfile,
)
from src.video_editor.exceptions import (
    FFmpegExecutionError,
    FFmpegNotFoundError,
    VideoAssetMissingError,
    VideoCompositionError,
)
from src.video_editor.ffmpeg_runner import FFmpegRunner
from src.video_editor.filtergraph import FiltergraphBuilder, escape_ffmpeg_filter_path
from src.video_editor.models import SceneClipSpec, VideoRenderResult, VideoRenderSettings
from src.video_editor.service import VideoAssemblyEngine


# --- Fixtures ---

@pytest.fixture
def sample_script():
    """Approved Script model fixture."""
    return Script(
        id="sc_test_senku_01",
        title="Senku Time Science",
        category=ContentCategory.ANIME_SCIENCE,
        hook="Opening hook question about Dr. Stone",
        body="Core narrative and scientific explanation of chronometry",
        takeaway="Concluding scientific reflection",
        target_duration_seconds=45.0,
        status=ScriptStatus.APPROVED,
    )


@pytest.fixture
def sample_storyboard():
    """Fully verified StoryboardDossier fixture with verified scientific claims."""
    vc = VisualConsistencyProfile(
        character_name="Senku Ishigami",
        facial_features="Sharp crimson eyes",
        hairstyle="Spiky green-to-white gradient hair",
        clothing_and_attire="Science tunic",
        color_palette="Emerald green, stone grey",
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
            narration_hinglish="Kya aapko lagta hai ki Senku 3,700 saal tak patthar mein jaag sakta tha?",
            narration_english_meaning="Do you think Senku could stay awake in stone for 3,700 years?",
            camera_angle="eye-level",
            framing="medium-close-up",
            subject_placement="center",
            camera_movement=CameraMovement.SLOW_ZOOM_IN,
            image_prompt_positive="Senku stone face with cracks",
            suggested_duration_seconds=4.0,
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
            suggested_duration_seconds=16.0,
            sound_effect_cue="sfx_electric_hum",
        ),
    ]
    return StoryboardDossier(
        storyboard_id="sb_video_test_senku",
        title="Senku Time Science",
        topic="Time Perception in Dr. Stone",
        target_duration_seconds=22.0,
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
def genuine_images_and_manifest(sample_storyboard, tmp_path):
    """Generates authentic 1080x1920 test images on disk and returns an approved manifest."""
    images_dir = tmp_path / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    metadata_list = []
    for s in sample_storyboard.scenes:
        img_path = images_dir / f"scene_{s.scene_number}.png"
        # Create valid 1080x1920 PNG image
        img = Image.new("RGB", (1080, 1920), color=(20 * s.scene_number, 50, 80))
        img.save(str(img_path))

        meta = GeneratedImageMetadata(
            scene_number=s.scene_number,
            image_path=str(img_path),
            provider="test_genuine_provider",
            model_id="test_model",
            prompt_used=s.image_prompt_positive,
            width=1080,
            height=1920,
            is_mock_asset=False,
            cost_usd=0.0,
            status=SceneImageStatus.APPROVED,
            reviewer_notes="Approved for production",
        )
        metadata_list.append(meta)

    return StoryboardImageManifest(
        storyboard_id=sample_storyboard.storyboard_id,
        total_scenes=len(sample_storyboard.scenes),
        has_mock_assets=False,
        images=metadata_list,
    )


@pytest.fixture
def genuine_voice_result(tmp_path):
    """Authentic voice synthesis result fixture with WAV file on disk."""
    import struct, wave
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    wav_path = audio_dir / "voiceover.wav"

    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        # 1 second dummy audio
        samples = [int(1000 * (i % 20)) for i in range(44100)]
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    return VoiceSynthesisResult(
        audio_path=str(wav_path),
        duration_seconds=20.0,
        voice_id="hi-IN-MadhurNeural",
        provider="edge_tts",
        file_size_bytes=wav_path.stat().st_size,
        boundaries=[
            TimestampBoundary(
                text="Kya aapko lagta hai ki Senku jaag sakta tha?",
                offset_ms=0.0,
                duration_ms=20000.0,
            )
        ],
        cost_usd=0.0,
        is_mock_asset=False,
    )


@pytest.fixture
def storage_manager(tmp_path):
    """StorageManager fixture rooted in tmp_path."""
    return StorageManager(
        base_productions_dir=tmp_path / "output" / "productions",
        manifest_dir=tmp_path / "data" / "processed" / "storage",
    )


@pytest.fixture
def production_package(sample_storyboard, storage_manager):
    """Organized ProductionPackage fixture."""
    return storage_manager.create_production_package(
        storyboard_id=sample_storyboard.storyboard_id,
        production_id="prod_video_test_01",
    )


# --- 1. Production Eligibility Gate Tests ---

def test_rendering_gate_blocks_when_script_is_unapproved(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify video assembly strictly blocks if script dialogue is not approved."""
    engine = VideoAssemblyEngine()
    sample_script.status = ScriptStatus.PENDING_REVIEW

    with pytest.raises(ProductionEligibilityBlockedError, match="Script dialogue must be human-approved"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


def test_rendering_gate_blocks_unverified_scientific_claims(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify video assembly strictly blocks if any scientific claim is unverified."""
    engine = VideoAssemblyEngine()
    sample_storyboard.scientific_claims[0].is_verified = False
    sample_storyboard.has_unverified_claims = True

    with pytest.raises(ProductionEligibilityBlockedError, match="unverified scientific claim"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


def test_rendering_gate_blocks_mock_images(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify video assembly strictly blocks if any image asset is a mock asset."""
    engine = VideoAssemblyEngine()
    genuine_images_and_manifest.images[0].is_mock_asset = True
    genuine_images_and_manifest.has_mock_assets = True

    with pytest.raises(MockAssetProductionBlockedError, match="contains MOCK assets"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


def test_rendering_gate_blocks_unapproved_images(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify video assembly blocks if any scene image lacks explicit human approval."""
    engine = VideoAssemblyEngine()
    genuine_images_and_manifest.images[0].status = SceneImageStatus.PENDING_IMAGE_REVIEW

    with pytest.raises(ImageReviewRequiredError, match="requires explicit human approval"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


def test_rendering_gate_blocks_mock_voiceover(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify video assembly strictly blocks if voiceover is mock generated."""
    engine = VideoAssemblyEngine()
    genuine_voice_result.is_mock_asset = True

    with pytest.raises(MockAssetProductionBlockedError, match="Voice synthesis asset is a MOCK asset"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


def test_rendering_gate_blocks_mock_mixed_audio(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify video assembly blocks if mixed audio is flagged as mock."""
    engine = VideoAssemblyEngine()
    mock_mix = AudioMixResult(
        mixed_audio_path=genuine_voice_result.audio_path,
        duration_seconds=20.0,
        voiceover_duration=20.0,
        is_mock_asset=True,
    )

    with pytest.raises(MockAssetProductionBlockedError, match="Mixed audio asset is flagged as a MOCK asset"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
            mixed_audio_result=mock_mix,
        )


def test_rendering_gate_blocks_mock_asset_in_production_package(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package, tmp_path
):
    """Verify video assembly blocks if production package contains any registered mock asset."""
    engine = VideoAssemblyEngine()
    dummy_mock = tmp_path / "mock_asset.txt"
    dummy_mock.write_text("mock")

    mock_asset = ProductionAsset(
        asset_id="mock_asset_01",
        asset_type=ProductionAssetType.SCENE_IMAGE,
        file_path=str(dummy_mock),
        is_mock_asset=True,
    )
    production_package.add_asset(mock_asset)

    with pytest.raises(MockAssetProductionBlockedError, match="contains MOCK asset"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


# --- 2. Asset Verification & Missing File Tests ---

def test_video_assembly_rejects_missing_image_file(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify VideoAssetMissingError is raised if an approved image does not exist on disk."""
    engine = VideoAssemblyEngine()
    genuine_images_and_manifest.images[0].image_path = "nonexistent_image_123.png"

    with pytest.raises(VideoAssetMissingError, match="image file does not exist on disk"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


def test_video_assembly_rejects_missing_audio_file(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify VideoAssetMissingError is raised if audio file is missing on disk."""
    engine = VideoAssemblyEngine()
    genuine_voice_result.audio_path = "nonexistent_audio_123.wav"

    with pytest.raises(VideoAssetMissingError, match="Primary audio file does not exist on disk"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


def test_video_assembly_rejects_missing_caption_file(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package, tmp_path
):
    """Verify VideoAssetMissingError is raised if provided ASS caption path does not exist."""
    engine = VideoAssemblyEngine()
    missing_ass = tmp_path / "nonexistent.ass"

    with pytest.raises(VideoAssetMissingError, match="ASS caption file does not exist on disk"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
            ass_caption_path=missing_ass,
        )


# --- 3. FFmpeg Runner & Subprocess Tests ---

def test_video_assembly_raises_when_ffmpeg_unavailable(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify FFmpegNotFoundError is raised when FFmpeg executable cannot be found."""
    mock_runner = MagicMock(spec=FFmpegRunner)
    mock_runner.check_ffmpeg_availability.return_value = (False, "Executable 'ffmpeg' not found on PATH")

    engine = VideoAssemblyEngine(ffmpeg_runner=mock_runner)

    with pytest.raises(FFmpegNotFoundError, match="Video assembly blocked: Executable 'ffmpeg' not found on PATH"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


def test_video_assembly_handles_ffmpeg_subprocess_failure(
    sample_script, sample_storyboard, genuine_images_and_manifest, genuine_voice_result, production_package
):
    """Verify FFmpegExecutionError is raised when FFmpeg fails during execution."""
    mock_runner = MagicMock(spec=FFmpegRunner)
    mock_runner.check_ffmpeg_availability.return_value = (True, "ffmpeg version 6.0")
    mock_runner.run_ffmpeg.side_effect = FFmpegExecutionError("FFmpeg error: Invalid pix_fmt")

    engine = VideoAssemblyEngine(ffmpeg_runner=mock_runner)

    with pytest.raises(FFmpegExecutionError, match="FFmpeg error: Invalid pix_fmt"):
        engine.render_short_video(
            storyboard=sample_storyboard,
            manifest=genuine_images_and_manifest,
            script=sample_script,
            voice_result=genuine_voice_result,
            production_package=production_package,
        )


# --- 4. Filtergraph Builder Tests ---

def test_filtergraph_builder_motion_and_dimensions():
    """Verify FiltergraphBuilder correctly structures zoompan and scaling for 1080x1920."""
    settings = VideoRenderSettings(width=1080, height=1920, fps=30)
    builder = FiltergraphBuilder(render_settings=settings)

    # 1. Slow Zoom-in
    spec_zoom = SceneClipSpec(
        scene_number=1,
        image_path="test_img.png",
        duration_seconds=5.0,
        camera_movement="slow-zoom-in",
    )
    filter_zoom = builder.build_scene_filter(0, spec_zoom)
    assert "zoompan=z='min(zoom+0.001,1.12)':d=150:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30" in filter_zoom
    assert "trim=duration=5.000,setpts=PTS-STARTPTS[v0]" in filter_zoom

    # 2. Dynamic Push
    spec_push = SceneClipSpec(
        scene_number=2,
        image_path="test_img.png",
        duration_seconds=3.0,
        camera_movement="dynamic-push",
    )
    filter_push = builder.build_scene_filter(1, spec_push)
    assert "zoompan=z='min(zoom+0.002,1.20)':d=90:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30" in filter_push

    # 3. Static Scale & Center Pad
    spec_static = SceneClipSpec(
        scene_number=3,
        image_path="test_img.png",
        duration_seconds=4.0,
        camera_movement="static",
    )
    filter_static = builder.build_scene_filter(2, spec_static)
    assert "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1" in filter_static


def test_filtergraph_builder_ass_caption_escaping(tmp_path):
    """Verify ASS caption path escaping converts Windows drive paths for FFmpeg filter safety."""
    ass_file = tmp_path / "shorts_subtitles.ass"
    escaped = escape_ffmpeg_filter_path(ass_file)

    # Windows drive letter colon must be escaped
    if len(str(ass_file)) >= 2 and str(ass_file)[1] == ":":
        assert "\\:" in escaped
    # Must use forward slashes
    assert "\\" not in escaped.replace("\\:", "")


def test_filtergraph_builder_full_command_synthesis(tmp_path):
    """Verify full CLI argument structure including concat, audio muxing, and encoder presets."""
    builder = FiltergraphBuilder()
    specs = [
        SceneClipSpec(scene_number=1, image_path=str(tmp_path / "img1.png"), duration_seconds=4.0),
        SceneClipSpec(scene_number=2, image_path=str(tmp_path / "img2.png"), duration_seconds=6.0),
    ]
    audio_p = tmp_path / "voice.wav"
    out_p = tmp_path / "out.mp4"
    ass_p = tmp_path / "subs.ass"
    ass_p.write_text("[Script Info]\nTitle: Test")

    cmd = builder.build_full_command(specs, audio_p, out_p, ass_caption_path=ass_p)

    # Check inputs
    assert "-loop" in cmd
    assert "-i" in cmd
    # Concat
    assert "[v0][v1]concat=n=2:v=1:a=0[vbase]" in cmd[cmd.index("-filter_complex") + 1]
    # Subtitles
    assert "ass=" in cmd[cmd.index("-filter_complex") + 1]
    # Encoders & mapping
    assert "-c:v" in cmd and "libx264" in cmd
    assert "-preset" in cmd and "veryfast" in cmd
    assert "-pix_fmt" in cmd and "yuv420p" in cmd
    assert "-shortest" in cmd


# --- 5. Successful Mocked Render Orchestration ---

def test_successful_mocked_render_orchestration(
    sample_script,
    sample_storyboard,
    genuine_images_and_manifest,
    genuine_voice_result,
    production_package,
    storage_manager,
):
    """Verify end-to-end video assembly orchestration with mocked FFmpeg execution."""
    mock_runner = MagicMock(spec=FFmpegRunner)
    mock_runner.check_ffmpeg_availability.return_value = (True, "ffmpeg version 6.0")

    # Simulate FFmpeg producing the output file on disk
    def fake_run_ffmpeg(args, timeout=None):
        out_file_str = args[-1]
        out_file = Path(out_file_str)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        # Write dummy MP4 bytes
        out_file.write_bytes(b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00")
        proc = MagicMock(spec=subprocess.CompletedProcess)
        proc.returncode = 0
        return proc, 2.45

    mock_runner.run_ffmpeg.side_effect = fake_run_ffmpeg

    engine = VideoAssemblyEngine(ffmpeg_runner=mock_runner, storage_manager=storage_manager)

    result = engine.render_short_video(
        storyboard=sample_storyboard,
        manifest=genuine_images_and_manifest,
        script=sample_script,
        voice_result=genuine_voice_result,
        production_package=production_package,
    )

    assert Path(result.video_path).exists()
    assert result.file_size_bytes > 0
    assert result.is_mock_asset is False
    assert result.cost_usd == 0.0
    assert result.resolution == "1080x1920"
    assert result.duration_seconds == 20.0
    assert result.render_duration_seconds == 2.45

    # Verify registered asset in StorageManager
    pkg = storage_manager.get_package(production_package.production_id, storyboard_id=sample_storyboard.storyboard_id)
    video_asset = next(a for a in pkg.assets if a.asset_type == ProductionAssetType.FINAL_VIDEO)
    assert video_asset is not None
    assert video_asset.is_mock_asset is False
    assert video_asset.metadata["resolution"] == "1080x1920"

    # Security Check: assert file is safe and within package root
    PathSecurityGuard.assert_safe_to_delete(Path(result.video_path), Path(production_package.root_dir))
