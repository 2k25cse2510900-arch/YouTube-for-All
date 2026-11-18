"""Unit tests for HuggingFaceFluxSchnellProvider."""

from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest

from src.image_engine.models import SceneImageStatus
from src.image_engine.providers.hf_flux_schnell import HuggingFaceFluxSchnellProvider


def create_dummy_png(path: Path, width: int = 768, height: int = 1344) -> Path:
    """Create a minimal RGB PNG test image."""
    img = Image.new("RGB", (width, height), color=(11, 19, 43))
    img.save(path, format="PNG")
    return path


class TestHuggingFaceFluxSchnellProvider:
    """Test suite for Hugging Face FLUX.1 Schnell image provider."""

    def test_provider_attributes_and_defaults(self):
        prov = HuggingFaceFluxSchnellProvider()
        assert prov.provider_name == "huggingface_flux_schnell"
        assert prov.model_id == "black-forest-labs/FLUX.1-schnell"
        assert prov.is_paid is False
        assert prov.is_mock is False
        assert prov.is_configured is True
        assert prov.default_steps == 4

    def test_snap_to_multiple_of_32(self):
        assert HuggingFaceFluxSchnellProvider._snap_to_multiple_of_32(576) == 576
        assert HuggingFaceFluxSchnellProvider._snap_to_multiple_of_32(768) == 768
        assert HuggingFaceFluxSchnellProvider._snap_to_multiple_of_32(1080) == 1088
        assert HuggingFaceFluxSchnellProvider._snap_to_multiple_of_32(1920) == 1920
        assert HuggingFaceFluxSchnellProvider._snap_to_multiple_of_32(100) == 256  # min bound
        assert HuggingFaceFluxSchnellProvider._snap_to_multiple_of_32(2500) == 2048  # max bound

    @patch("src.image_engine.providers.hf_flux_schnell.GradioClient")
    def test_mocked_successful_generation(self, mock_client_cls, tmp_path):
        out_img = tmp_path / "scene_01.png"
        out_thumb = tmp_path / "scene_01_thumb.png"

        # Create dummy source image
        raw_source = tmp_path / "gradio_temp.png"
        create_dummy_png(raw_source, width=768, height=1344)

        # Mock Gradio client and submit
        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.return_value = (str(raw_source), 42.0)
        mock_client.submit.return_value = mock_job
        mock_client_cls.return_value = mock_client

        prov = HuggingFaceFluxSchnellProvider()
        meta = prov.generate_scene_image(
            scene_number=1,
            positive_prompt="Silver-haired Protagonist anime keyframe",
            negative_prompt="blurry, distorted",
            output_path=out_img,
            thumbnail_path=out_thumb,
            width=1080,
            height=1920,
        )

        assert out_img.exists()
        assert out_thumb.exists()
        assert meta.scene_number == 1
        assert meta.provider == "huggingface_flux_schnell"
        assert meta.cost_usd == 0.0
        assert meta.is_mock_asset is False
        assert meta.status == SceneImageStatus.PENDING_IMAGE_REVIEW
        assert meta.file_size_bytes > 0
        assert len(meta.file_hash) == 64

    @patch("src.image_engine.providers.hf_flux_schnell.GradioClient")
    def test_quota_exhaustion_fails_closed(self, mock_client_cls, tmp_path):
        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.side_effect = RuntimeError("ZeroGPU: GPU quota exceeded. You have 0 seconds left today.")
        mock_client.submit.return_value = mock_job
        mock_client_cls.return_value = mock_client

        prov = HuggingFaceFluxSchnellProvider()
        with pytest.raises(RuntimeError) as exc_info:
            prov.generate_scene_image(
                scene_number=1,
                positive_prompt="Protagonist",
                negative_prompt="",
                output_path=tmp_path / "out.png",
            )
        assert "ZeroGPU quota exhausted" in str(exc_info.value)

    @patch("src.image_engine.providers.hf_flux_schnell.GradioClient")
    def test_payment_requirement_fails_closed(self, mock_client_cls, tmp_path):
        mock_client = MagicMock()
        mock_job = MagicMock()
        mock_job.result.side_effect = RuntimeError("Payment Required: HTTP 402 Upgrade to PRO plan")
        mock_client.submit.return_value = mock_job
        mock_client_cls.return_value = mock_client

        prov = HuggingFaceFluxSchnellProvider()
        with pytest.raises(RuntimeError) as exc_info:
            prov.generate_scene_image(
                scene_number=1,
                positive_prompt="Protagonist",
                negative_prompt="",
                output_path=tmp_path / "out.png",
            )
        assert "COST SAFETY HARD BLOCK" in str(exc_info.value)
