"""Automated tests for CloudflareFluxImageProvider, FluxPromptAdapter, and zero-cost safety."""

import base64
import io
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from PIL import Image

from src.image_engine.cost_guard import CostSafetyGuard
from src.image_engine.exceptions import CostSafetyViolationError, ImageEngineError
from src.image_engine.flux_adapter import FluxPromptAdapter
from src.image_engine.models import GeneratedImageMetadata, SceneImageStatus
from src.image_engine.providers.cloudflare_flux import CloudflareFluxImageProvider


def create_dummy_png_bytes(width: int = 512, height: int = 512, color=(0, 100, 200)) -> bytes:
    """Create raw PNG image bytes in-memory."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestFluxPromptAdapter:
    """Test FLUX natural language prompt adaptation."""

    def test_prompt_adaptation_includes_style_and_character(self):
        raw = "Protagonist stands motionless while cursed fists freeze in mid-air"
        adapted = FluxPromptAdapter.adapt_prompt(raw, character_name="Silver-haired Protagonist", is_vertical_short=True)

        assert "Japanese anime keyframe illustration" in adapted
        assert "Silver-haired Protagonist" in adapted
        assert "snow-white hair" in adapted
        assert "blindfold" in adapted
        assert "Vertical portrait orientation" in adapted
        assert "Protagonist stands motionless" in adapted
        assert "dark navy blue background" in adapted

    def test_prompt_adaptation_length_capped(self):
        long_text = "test " * 1000
        adapted = FluxPromptAdapter.adapt_prompt(long_text)
        assert len(adapted) <= 2000


class TestCloudflareFluxImageProvider:
    """Test Cloudflare FLUX image provider lifecycle and error handling."""

    def test_provider_attributes_and_zero_cost(self):
        provider = CloudflareFluxImageProvider(
            account_id="test_acc_123",
            api_token="test_tok_456",
        )
        assert provider.provider_name == "cloudflare_flux"
        assert provider.is_mock is False
        assert provider.is_paid is False
        assert provider.is_configured is True
        # Cost guard check
        CostSafetyGuard.assert_zero_cost_provider(provider.provider_name)

    def test_missing_credentials_raises_clean_error(self, tmp_path):
        empty_env = tmp_path / ".env.empty"
        empty_env.write_text("", encoding="utf-8")

        provider = CloudflareFluxImageProvider(
            account_id="",
            api_token="",
            env_file_path=empty_env,
        )
        assert provider.is_configured is False

        with pytest.raises(ImageEngineError) as exc_info:
            provider.generate_scene_image(
                scene_number=1,
                positive_prompt="Silver-haired Protagonist test",
                output_path=tmp_path / "test.png",
            )
        assert "Cloudflare credentials are not configured" in str(exc_info.value)
        # Verify no secret is printed
        assert "test_tok" not in str(exc_info.value)

    @patch("requests.post")
    def test_successful_generation_with_mocked_api(self, mock_post, tmp_path):
        dummy_png = create_dummy_png_bytes(512, 512, (20, 40, 80))
        b64_str = base64.b64encode(dummy_png).decode("utf-8")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {"image": b64_str},
            "success": True,
        }
        mock_post.return_value = mock_response

        provider = CloudflareFluxImageProvider(
            account_id="mock_acc_123",
            api_token="mock_tok_456",
        )

        out_img = tmp_path / "scene_01.png"
        out_thumb = tmp_path / "scene_01_thumb.jpg"

        metadata = provider.generate_scene_image(
            scene_number=1,
            positive_prompt="Protagonist Infinity activation",
            output_path=out_img,
            thumbnail_path=out_thumb,
            width=1080,
            height=1920,
        )

        assert out_img.exists()
        assert out_thumb.exists()
        assert metadata.scene_number == 1
        assert metadata.provider == "cloudflare_flux"
        assert metadata.model_id == "@cf/black-forest-labs/flux-1-schnell"
        assert metadata.cost_usd == 0.00
        assert metadata.is_mock_asset is False
        assert metadata.status == SceneImageStatus.PENDING_IMAGE_REVIEW
        assert metadata.width == 1080
        assert metadata.height == 1920
        assert len(metadata.file_hash) == 64  # SHA-256

        # Check request call payload
        call_kwargs = mock_post.call_args[1]
        assert "https://api.cloudflare.com/client/v4/accounts/mock_acc_123/ai/run/@cf/black-forest-labs/flux-1-schnell" in mock_post.call_args[0][0]
        assert "Bearer mock_tok_456" in call_kwargs["headers"]["Authorization"]
        assert call_kwargs["json"]["steps"] == 4

    @patch("requests.post")
    def test_quota_exhausted_429_handling(self, mock_post, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Daily free quota limit reached: 10000 Neurons exhausted"
        mock_post.return_value = mock_response

        provider = CloudflareFluxImageProvider(
            account_id="mock_acc_123",
            api_token="mock_tok_456",
        )

        with pytest.raises(ImageEngineError) as exc_info:
            provider.generate_scene_image(
                scene_number=1,
                positive_prompt="Protagonist test",
                output_path=tmp_path / "test.png",
            )
        assert "Daily Free Neurons Exceeded" in str(exc_info.value) or "429" in str(exc_info.value)

    @patch("requests.post")
    def test_auth_error_401_handling(self, mock_post, tmp_path):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized: Invalid API Token"
        mock_post.return_value = mock_response

        provider = CloudflareFluxImageProvider(
            account_id="mock_acc_123",
            api_token="mock_tok_456",
        )

        with pytest.raises(ImageEngineError) as exc_info:
            provider.generate_scene_image(
                scene_number=1,
                positive_prompt="Protagonist test",
                output_path=tmp_path / "test.png",
            )
        assert "Authentication failed" in str(exc_info.value)
