"""Unit tests for AgnesVideoFlashProvider, ReplicateMinimaxProvider, and FFprobe validation."""

import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from src.anime_motion.image_to_video_provider import (
    AgnesVideoFlashProvider,
    HuggingFaceZeroGPUVideoProvider,
    ReplicateMinimaxProvider,
    validate_video_with_ffprobe,
)
from src.anime_motion.motion_planner import MotionShotPlan, MotionType


def generate_tiny_test_video(path: Path, duration: float = 1.0) -> Path:
    """Generate a tiny 1-second 1080x1920 test video using FFmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=navy:s=1080x1920:d={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        str(path)
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def make_sample_shot_plan(shot_id: str = "shot_01", duration: float = 3.0, movement: str = "Protagonist hand sign") -> MotionShotPlan:
    """Construct a schema-valid MotionShotPlan."""
    return MotionShotPlan(
        shot_idx=1,
        shot_id=shot_id,
        scene_id="scene_01",
        time_start=0.0,
        time_end=duration,
        duration=duration,
        motion_type=MotionType.GENUINE_AI_ANIMATION,
        environment="Tokyo dark skyline with blue cursed energy",
        camera_trajectory="Slow push-in 5%",
        start_pose="Standing calm with hands in pockets",
        intended_movement=movement,
        end_pose="Fingers raised in Void hand sign",
        lighting="High-contrast theatrical rim lighting in cobalt blue",
        image_prompt="Silver-haired Protagonist anime keyframe",
        motion_prompt="Subtle anime motion, hair shifts and eyes flare",
    )


class TestFFprobeValidator:
    """Test FFprobe video validation."""

    def test_validate_valid_video(self, tmp_path):
        video_path = tmp_path / "valid.mp4"
        generate_tiny_test_video(video_path, duration=1.0)

        info = validate_video_with_ffprobe(video_path)
        assert info["width"] == 1080
        assert info["height"] == 1920
        assert info["resolution"] == "1080x1920"
        assert info["fps"] == 30.0
        assert info["duration"] >= 0.9
        assert info["codec"] in ("h264", "libx264")
        assert info["size_bytes"] > 0

    def test_validate_missing_file_raises_error(self, tmp_path):
        missing = tmp_path / "missing.mp4"
        with pytest.raises(FileNotFoundError):
            validate_video_with_ffprobe(missing)

    def test_validate_empty_file_raises_error(self, tmp_path):
        empty = tmp_path / "empty.mp4"
        empty.write_bytes(b"")
        with pytest.raises(ValueError):
            validate_video_with_ffprobe(empty)


class TestAgnesVideoFlashProvider:
    """Test Agnes AI video provider adapter."""

    def test_provider_attributes_and_defaults(self):
        prov = AgnesVideoFlashProvider(api_key="test_key_123")
        assert prov.provider_name == "agnes_video_flash"
        assert prov.is_paid is False
        assert prov.is_mock is False
        assert prov.is_configured is True

    def test_missing_api_key_fails_closed(self, tmp_path):
        empty_env = tmp_path / ".env.empty"
        empty_env.write_text("", encoding="utf-8")

        prov = AgnesVideoFlashProvider(api_key="", env_file_path=empty_env)
        assert prov.is_configured is False

        shot = make_sample_shot_plan(shot_id="shot_01", duration=3.0, movement="Protagonist fingers move in Void hand sign")
        dummy_img = tmp_path / "start.png"
        dummy_img.write_bytes(b"dummy")

        with pytest.raises(RuntimeError) as exc_info:
            prov.generate_motion_clip(
                shot=shot,
                start_image_path=dummy_img,
                output_clip_path=tmp_path / "out.mp4",
            )
        assert "Agnes AI API Key not configured" in str(exc_info.value)

    @patch("requests.get")
    @patch("requests.post")
    def test_mocked_successful_generation(self, mock_post, mock_get, tmp_path):
        # Create a valid input image
        start_img = tmp_path / "start.png"
        start_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        out_mp4 = tmp_path / "out.mp4"
        real_video_asset = tmp_path / "asset.mp4"
        generate_tiny_test_video(real_video_asset, duration=1.0)
        video_bytes = real_video_asset.read_bytes()

        # Mock POST /videos
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {"id": "agnes_task_001"}
        mock_post.return_value = post_resp

        # Mock GET polling & download
        poll_resp = MagicMock()
        poll_resp.status_code = 200
        poll_resp.json.return_value = {
            "status": "SUCCESS",
            "video_url": "https://cdn.agnes-ai.com/videos/agnes_task_001.mp4",
        }

        dl_resp = MagicMock()
        dl_resp.status_code = 200
        dl_resp.content = video_bytes

        # First get call is poll, second is download
        mock_get.side_effect = [poll_resp, dl_resp]

        prov = AgnesVideoFlashProvider(api_key="mock_key")
        shot = make_sample_shot_plan(shot_id="shot_01", duration=1.0, movement="Spiky white hair shifts in wind draft")

        metadata = prov.generate_motion_clip(
            shot=shot,
            start_image_path=start_img,
            output_clip_path=out_mp4,
        )

        assert out_mp4.exists()
        assert metadata.shot_id == "shot_01"
        assert metadata.provider_used == "agnes_video_flash"
        assert metadata.motion_type == MotionType.GENUINE_AI_ANIMATION
        assert metadata.estimated_cost_usd == 0.0

    @patch("requests.post")
    def test_payment_requirement_fails_closed(self, mock_post, tmp_path):
        start_img = tmp_path / "start.png"
        start_img.write_bytes(b"dummy")

        post_resp = MagicMock()
        post_resp.status_code = 402
        post_resp.text = "Payment required: Insufficient promotional credits."
        mock_post.return_value = post_resp

        prov = AgnesVideoFlashProvider(api_key="mock_key")
        shot = make_sample_shot_plan(shot_id="shot_01", duration=3.0, movement="Fist freeze")

        with pytest.raises(RuntimeError) as exc_info:
            prov.generate_motion_clip(
                shot=shot,
                start_image_path=start_img,
                output_clip_path=tmp_path / "out.mp4",
            )
        assert "COST SAFETY HARD BLOCK" in str(exc_info.value)


class TestReplicateMinimaxProvider:
    """Test Replicate Minimax provider cost gating."""

    def test_provider_attributes(self):
        prov = ReplicateMinimaxProvider(api_token="test_tok")
        assert prov.provider_name == "replicate_minimax_video_01"
        assert prov.is_paid is True
        assert prov.is_mock is False

    def test_replicate_fails_closed(self, tmp_path):
        prov = ReplicateMinimaxProvider(api_token="mock_token")
        shot = make_sample_shot_plan(shot_id="shot_01", duration=3.0, movement="Character turns")
        with pytest.raises(NotImplementedError) as exc_info:
            prov.generate_motion_clip(
                shot=shot,
                start_image_path=tmp_path / "test.png",
                output_clip_path=tmp_path / "out.mp4",
            )
        assert "requires paid prepaid credits" in str(exc_info.value)


class TestHuggingFaceZeroGPUVideoProvider:
    """Test Hugging Face ZeroGPU video provider adapter."""

    def test_provider_attributes_and_defaults(self):
        prov = HuggingFaceZeroGPUVideoProvider()
        assert prov.provider_name == "huggingface_zerogpu_wan2"
        assert prov.is_paid is False
        assert prov.is_mock is False
        assert prov.is_configured is True
        assert prov.default_steps == 6
        assert prov.default_duration == 3.5

    def test_missing_input_image_raises_error(self, tmp_path):
        prov = HuggingFaceZeroGPUVideoProvider()
        shot = make_sample_shot_plan(shot_id="shot_01", duration=3.0)
        missing_img = tmp_path / "missing.png"

        with pytest.raises(FileNotFoundError):
            prov.generate_motion_clip(
                shot=shot,
                start_image_path=missing_img,
                output_clip_path=tmp_path / "out.mp4",
            )

    @patch("src.anime_motion.image_to_video_provider.GradioClient")
    def test_mocked_successful_generation(self, mock_client_cls, tmp_path):
        start_img = tmp_path / "input.png"
        start_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)
        out_mp4 = tmp_path / "generated.mp4"

        # Create valid tiny video fixture to be returned by mock
        mock_raw_video = tmp_path / "raw_generated.mp4"
        generate_tiny_test_video(mock_raw_video, duration=1.0)

        # Mock Gradio client and submit job
        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.return_value = (str(mock_raw_video), 42.0)
        mock_client.submit.return_value = mock_job
        mock_client_cls.return_value = mock_client

        prov = HuggingFaceZeroGPUVideoProvider()
        shot = make_sample_shot_plan(shot_id="shot_01", duration=3.0, movement="Blue energy vortex swirling")

        metadata = prov.generate_motion_clip(
            shot=shot,
            start_image_path=start_img,
            output_clip_path=out_mp4,
        )

        assert out_mp4.exists()
        assert metadata.shot_id == "shot_01"
        assert metadata.provider_used == "huggingface_zerogpu_wan2"
        assert metadata.motion_type == MotionType.GENUINE_AI_ANIMATION
        assert metadata.estimated_cost_usd == 0.0
        assert metadata.fps == 30.0
        assert metadata.resolution == "1080x1920"

    @patch("src.anime_motion.image_to_video_provider.GradioClient")
    def test_quota_exhaustion_fails_closed(self, mock_client_cls, tmp_path):
        start_img = tmp_path / "input.png"
        start_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.side_effect = RuntimeError("ZeroGPU: GPU quota exceeded. You have 0 seconds left today.")
        mock_client.submit.return_value = mock_job
        mock_client_cls.return_value = mock_client

        prov = HuggingFaceZeroGPUVideoProvider()
        shot = make_sample_shot_plan(shot_id="shot_01", duration=3.0)

        with pytest.raises(RuntimeError) as exc_info:
            prov.generate_motion_clip(
                shot=shot,
                start_image_path=start_img,
                output_clip_path=tmp_path / "out.mp4",
            )
        assert "ZeroGPU quota exhausted" in str(exc_info.value)

    @patch("src.anime_motion.image_to_video_provider.GradioClient")
    def test_payment_detected_fails_closed(self, mock_client_cls, tmp_path):
        start_img = tmp_path / "input.png"
        start_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.side_effect = RuntimeError("Payment Required: HTTP 402 Upgrade to PRO plan")
        mock_client.submit.return_value = mock_job
        mock_client_cls.return_value = mock_client

        prov = HuggingFaceZeroGPUVideoProvider()
        shot = make_sample_shot_plan(shot_id="shot_01", duration=3.0)

        with pytest.raises(RuntimeError) as exc_info:
            prov.generate_motion_clip(
                shot=shot,
                start_image_path=start_img,
                output_clip_path=tmp_path / "out.mp4",
            )
        assert "COST SAFETY HARD BLOCK" in str(exc_info.value)

