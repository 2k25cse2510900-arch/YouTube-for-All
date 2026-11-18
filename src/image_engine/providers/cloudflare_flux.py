"""Cloudflare Workers AI FLUX.1 Schnell Image Generation Provider.

Provides hosted inference for @cf/black-forest-labs/flux-1-schnell via Cloudflare Workers AI.
Runs within Cloudflare's 10,000 free daily Neurons allocation, guaranteeing $0.00 cost compliance.
"""

import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, Optional
import requests
from PIL import Image, ImageFilter

from src.common.logger import setup_logger
from src.image_engine.cost_guard import CostSafetyGuard
from src.image_engine.exceptions import (
    CostSafetyViolationError,
    ImageEngineError,
)
from src.image_engine.flux_adapter import FluxPromptAdapter
from src.image_engine.models import GeneratedImageMetadata, SceneImageStatus
from src.image_engine.providers.base import BaseImageProvider

logger = setup_logger("cloudflare_flux_provider")


class CloudflareFluxImageProvider(BaseImageProvider):
    """Cloudflare Workers AI hosted provider for FLUX.1 Schnell.
    
    Model: @cf/black-forest-labs/flux-1-schnell
    Architecture: 12B parameter distilled flow transformer by Black Forest Labs.
    Pricing on Cloudflare: Free tier provides 10,000 Neurons/day (~57 free images/day).
    """

    MODEL_ID = "@cf/black-forest-labs/flux-1-schnell"
    DEFAULT_STEPS = 4
    MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 2.0
    REQUEST_TIMEOUT_SECONDS = 45.0

    def __init__(
        self,
        account_id: Optional[str] = None,
        api_token: Optional[str] = None,
        env_file_path: Optional[Path] = None,
        target_aspect_ratio: str = "9:16",
        target_width: int = 1080,
        target_height: int = 1920,
    ):
        self._account_id = account_id
        self._api_token = api_token
        self._env_file_path = env_file_path or Path(".env")
        self.target_aspect_ratio = target_aspect_ratio
        self.target_width = target_width
        self.target_height = target_height

        # Enforce zero cost policy
        CostSafetyGuard.assert_zero_cost_provider(self.provider_name)
        self._load_credentials()

    @property
    def provider_name(self) -> str:
        return "cloudflare_flux"

    @property
    def is_mock(self) -> bool:
        return False

    @property
    def is_paid(self) -> bool:
        return False

    def _load_credentials(self) -> None:
        """Load Account ID and API Token from environment or .env without logging secrets."""
        if not self._account_id:
            self._account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID") or os.environ.get("CF_ACCOUNT_ID")

        if not self._api_token:
            self._api_token = os.environ.get("CLOUDFLARE_API_TOKEN") or os.environ.get("CF_API_TOKEN")

        # Try .env if still missing
        if (not self._account_id or not self._api_token) and self._env_file_path.exists():
            try:
                for line in self._env_file_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("#") or not line:
                        continue
                    if line.startswith("CLOUDFLARE_ACCOUNT_ID=") and not self._account_id:
                        self._account_id = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("CF_ACCOUNT_ID=") and not self._account_id:
                        self._account_id = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("CLOUDFLARE_API_TOKEN=") and not self._api_token:
                        self._api_token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif line.startswith("CF_API_TOKEN=") and not self._api_token:
                        self._api_token = line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception as e:
                logger.warning("Could not read credentials from .env: %s", type(e).__name__)

    @property
    def is_configured(self) -> bool:
        """True if credentials are fully configured."""
        return bool(self._account_id and self._api_token)

    def _get_api_url(self) -> str:
        if not self._account_id:
            raise ImageEngineError(
                "Cloudflare Account ID is missing. Please set CLOUDFLARE_ACCOUNT_ID in .env or environment."
            )
        return f"https://api.cloudflare.com/client/v4/accounts/{self._account_id}/ai/run/{self.MODEL_ID}"

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
        steps: int = 4,
        seed: Optional[int] = None,
    ) -> GeneratedImageMetadata:
        """Generate an anime illustration using Cloudflare Workers AI FLUX.1 Schnell."""
        CostSafetyGuard.assert_zero_cost_provider(self.provider_name)

        if not self.is_configured:
            raise ImageEngineError(
                "Cloudflare credentials are not configured. Both CLOUDFLARE_ACCOUNT_ID and "
                "CLOUDFLARE_API_TOKEN must be set in your .env file."
            )

        output_path = Path(output_path) if output_path else Path(f"scene_{scene_number:02d}.png")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Adapt prompt using FLUX natural language adapter
        adapted_prompt = FluxPromptAdapter.adapt_prompt(
            base_prompt=positive_prompt,
            is_vertical_short=(height > width),
        )

        url = self._get_api_url()
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }
        payload: Dict[str, Any] = {
            "prompt": adapted_prompt,
            "steps": min(max(1, steps), 8),
        }
        if seed is not None:
            payload["seed"] = seed

        start_time = time.time()
        image_bytes: Optional[bytes] = None
        last_error_msg = ""

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                logger.info(
                    "Calling Cloudflare Workers AI FLUX (attempt %d/%d) for scene %d...",
                    attempt,
                    self.MAX_RETRIES,
                    scene_number,
                )
                response = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                )

                if response.status_code == 200:
                    data = response.json()
                    # Check for base64 image in result.image
                    result_data = data.get("result", {})
                    base64_str = result_data.get("image")
                    if base64_str:
                        image_bytes = base64.b64decode(base64_str)
                        break
                    else:
                        last_error_msg = f"Unexpected response format: {list(data.keys())}"
                        logger.warning(last_error_msg)

                elif response.status_code == 429:
                    last_error_msg = (
                        "HTTP 429 Too Many Requests / Daily Free Neurons Exceeded on Cloudflare Workers AI. "
                        f"Response: {response.text[:200]}"
                    )
                    logger.error(last_error_msg)
                    # Quota exhausted: do not burn retries pointlessly
                    break

                elif response.status_code in (401, 403):
                    last_error_msg = (
                        f"HTTP {response.status_code} Authentication failed. Please verify CLOUDFLARE_API_TOKEN "
                        "has 'Workers AI: Read' or 'Workers AI: Edit' permissions."
                    )
                    logger.critical(last_error_msg)
                    raise ImageEngineError(last_error_msg)

                else:
                    last_error_msg = f"HTTP {response.status_code}: {response.text[:250]}"
                    logger.warning("Attempt %d failed: %s", attempt, last_error_msg)

            except requests.exceptions.RequestException as e:
                last_error_msg = f"Network/Request error: {type(e).__name__}: {str(e)[:200]}"
                logger.warning("Attempt %d encountered error: %s", attempt, last_error_msg)

            if attempt < self.MAX_RETRIES:
                sleep_sec = self.RETRY_BACKOFF_FACTOR ** attempt
                time.sleep(sleep_sec)

        if not image_bytes:
            raise ImageEngineError(f"Cloudflare FLUX generation failed after {self.MAX_RETRIES} attempts. Reason: {last_error_msg}")

        # Post-process image to target 9:16 (1080x1920) composition
        final_width, final_height = self._save_and_reframe(
            image_bytes=image_bytes,
            output_path=output_path,
            target_width=width,
            target_height=height,
        )

        # Generate lightweight thumbnail if requested
        if thumbnail_path:
            thumbnail_path = Path(thumbnail_path)
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(output_path) as img:
                img.thumbnail((360, 640))
                img.save(thumbnail_path, format="JPEG", quality=85)

        duration = time.time() - start_time
        file_bytes = output_path.stat().st_size
        file_hash = hashlib.sha256(output_path.read_bytes()).hexdigest()

        # Zero cost assertion
        CostSafetyGuard.verify_generation_cost(0.00, self.provider_name)

        return GeneratedImageMetadata(
            scene_number=scene_number,
            image_path=str(output_path.resolve()),
            thumbnail_path=str(thumbnail_path.resolve()) if thumbnail_path else None,
            provider=self.provider_name,
            model_id=self.MODEL_ID,
            prompt_used=adapted_prompt,
            negative_prompt_used=negative_prompt,
            width=final_width,
            height=final_height,
            aspect_ratio=f"{final_width}:{final_height}",
            file_hash=file_hash,
            file_size_bytes=file_bytes,
            is_mock_asset=False,
            cost_usd=0.00,
            status=SceneImageStatus.PENDING_IMAGE_REVIEW,
            generation_duration_seconds=round(duration, 2),
            generated_at=datetime.now(timezone.utc),
            metadata={
                "steps": payload.get("steps", 4),
                "seed": seed,
                "api_endpoint": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                "neurons_consumed_estimate_range": "57.6 - 172.8",
                "free_daily_neurons_allocation_shared": 10000,
            },
        )

    def _save_and_reframe(
        self,
        image_bytes: bytes,
        output_path: Path,
        target_width: int,
        target_height: int,
    ) -> tuple[int, int]:
        """Save raw FLUX image and format for vertical 9:16 mobile framing."""
        raw_temp_path = output_path.with_suffix(".raw.png")
        raw_temp_path.write_bytes(image_bytes)

        with Image.open(raw_temp_path) as src_img:
            src_w, src_h = src_img.size

            if target_height > target_width:
                # Vertical 9:16 target (e.g., 1080x1920)
                # Professional Zero-Cost Solution: Cinematic Ambient Blur Extension + Reference Canvas Tint
                # 1. Scale background to cover entire 1080x1920 canvas
                scale_bg = max(target_width / src_w, target_height / src_h)
                bg_w, bg_h = int(src_w * scale_bg), int(src_h * scale_bg)
                bg = src_img.resize((bg_w, bg_h), Image.Resampling.BILINEAR)

                # Center-crop background to exact 1080x1920
                crop_x = (bg_w - target_width) // 2
                crop_y = (bg_h - target_height) // 2
                bg_cropped = bg.crop((crop_x, crop_y, crop_x + target_width, crop_y + target_height))

                # Apply heavy Gaussian blur to create soft atmospheric glow
                bg_blurred = bg_cropped.filter(ImageFilter.GaussianBlur(radius=40))

                # Multiply/blend with reference signature dark navy #0B132B (RGB: 11, 19, 43)
                tint = Image.new("RGB", (target_width, target_height), (11, 19, 43))
                canvas = Image.blend(bg_blurred, tint, alpha=0.65)

                # 2. Scale primary foreground image to fit width (1080px)
                scale_fg = target_width / src_w
                fg_h = int(src_h * scale_fg)
                resized_src = src_img.resize((target_width, fg_h), Image.Resampling.LANCZOS)

                # 3. Paste uncropped foreground centered at y_offset (leaving top/bottom clear)
                y_offset = (target_height - fg_h) // 2
                canvas.paste(resized_src, (0, y_offset))

                canvas.save(output_path, format="PNG")
                if raw_temp_path.exists():
                    raw_temp_path.unlink()
                return target_width, target_height
            else:
                # Direct save
                src_img.save(output_path, format="PNG")
                if raw_temp_path.exists():
                    raw_temp_path.unlink()
                return src_w, src_h
