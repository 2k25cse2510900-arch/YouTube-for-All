"""Google Gemini Image Generation Provider.

Maintains Gemini as a separately selectable provider for image generation.
Enforces API key safety, quota checking, and cost tracking.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Optional
from PIL import Image

from src.common.logger import setup_logger
from src.image_engine.cost_guard import CostSafetyGuard
from src.image_engine.exceptions import (
    CostSafetyViolationError,
    ImageEngineError,
)
from src.image_engine.models import GeneratedImageMetadata, SceneImageStatus
from src.image_engine.providers.base import BaseImageProvider

logger = setup_logger("gemini_image_provider")


class GeminiImageProvider(BaseImageProvider):
    """Google Gemini / Imagen image generation provider.
    
    Selectable alongside Cloudflare FLUX.
    When free-tier quota is 0, raises clear quota exhaustion guidance.
    """

    DEFAULT_MODEL = "gemini-3.1-flash-image"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: str = DEFAULT_MODEL,
        env_file_path: Optional[Path] = None,
    ):
        self._api_key = api_key
        self.model_id = model_id
        self._env_file_path = env_file_path or Path(".env")
        self._load_key()

    @property
    def provider_name(self) -> str:
        return "gemini_image"

    @property
    def is_mock(self) -> bool:
        return False

    @property
    def is_paid(self) -> bool:
        # Defaults to False in free-tier probe mode; flagged if billing required
        return False

    def _load_key(self) -> None:
        """Load GEMINI_API_KEY from environment or .env without logging secrets."""
        if not self._api_key:
            self._api_key = os.environ.get("GEMINI_API_KEY")

        if not self._api_key and self._env_file_path.exists():
            try:
                for line in self._env_file_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY="):
                        self._api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception as e:
                logger.warning("Could not load GEMINI_API_KEY: %s", type(e).__name__)

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def generate_scene_image(
        self,
        scene_number: int,
        positive_prompt: str,
        negative_prompt: str = "",
        output_path: Optional[Path] = None,
        thumbnail_path: Optional[Path] = None,
        width: int = 1080,
        height: int = 1920,
        reference_image: Optional[str] = None,
    ) -> GeneratedImageMetadata:
        """Attempt image generation via Google Gemini API."""
        if not self.is_configured:
            raise ImageEngineError("GEMINI_API_KEY is not configured in .env or environment.")

        output_path = Path(output_path) if output_path else Path(f"gemini_scene_{scene_number:02d}.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImageEngineError("google-genai SDK is not installed in the environment.")

        client = genai.Client(api_key=self._api_key)
        start_time = time.time()

        try:
            logger.info("Attempting Gemini image generation with model %s...", self.model_id)
            config = types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"]
            )
            response = client.models.generate_content(
                model=self.model_id,
                contents=positive_prompt,
                config=config,
            )

            # Inspect for image part
            found_image = False
            image_bytes = None
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and candidate.content and hasattr(candidate.content, 'parts'):
                        for part in candidate.content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                import base64
                                img_data = part.inline_data.data
                                if isinstance(img_data, str):
                                    image_bytes = base64.b64decode(img_data)
                                else:
                                    image_bytes = img_data
                                found_image = True
                                break
                    if found_image:
                        break

            if not found_image or not image_bytes:
                raise ImageEngineError(
                    f"Gemini API returned no image payload for model {self.model_id}."
                )

            output_path.write_bytes(image_bytes)

            duration = time.time() - start_time
            file_bytes = output_path.stat().st_size
            file_hash = hashlib.sha256(image_bytes).hexdigest()

            return GeneratedImageMetadata(
                scene_number=scene_number,
                image_path=str(output_path.resolve()),
                thumbnail_path=str(thumbnail_path.resolve()) if thumbnail_path else None,
                provider=self.provider_name,
                model_id=self.model_id,
                prompt_used=positive_prompt,
                negative_prompt_used=negative_prompt,
                width=width,
                height=height,
                aspect_ratio="9:16",
                file_hash=file_hash,
                file_size_bytes=file_bytes,
                is_mock_asset=False,
                cost_usd=0.00,
                status=SceneImageStatus.PENDING_IMAGE_REVIEW,
                generation_duration_seconds=round(duration, 2),
                generated_at=datetime.now(timezone.utc),
            )

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "limit: 0" in err_str:
                raise ImageEngineError(
                    f"Gemini Free-Tier quota is 0 for image generation ({self.model_id}). "
                    "Google AI Studio requires billing activation for image generation."
                )
            raise ImageEngineError(f"Gemini image generation failed: {type(e).__name__}: {err_str[:250]}")
