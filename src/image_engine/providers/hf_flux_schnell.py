"""Hugging Face ZeroGPU FLUX.1 Schnell Image Generation Provider.

Connects to the official Black Forest Labs FLUX.1-schnell Space:
https://huggingface.co/spaces/black-forest-labs/FLUX.1-schnell

Model: black-forest-labs/FLUX.1-schnell (12B parameter distilled flow transformer)
Hosting: Hugging Face ZeroGPU Community Pool
License: Model is Apache 2.0; Space is MIT
Cost: 100% Free / $0.00
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from typing import Any, Dict, Optional
from PIL import Image

try:
    from gradio_client import Client as GradioClient
    HAS_GRADIO_CLIENT = True
except ImportError:
    HAS_GRADIO_CLIENT = False
    GradioClient = None

from src.common.logger import setup_logger
from src.image_engine.models import GeneratedImageMetadata, SceneImageStatus
from src.image_engine.providers.base import BaseImageProvider

logger = setup_logger("hf_flux_schnell_provider")


class HuggingFaceFluxSchnellProvider(BaseImageProvider):
    """Hugging Face ZeroGPU hosted provider for FLUX.1 Schnell.
    
    Model: black-forest-labs/FLUX.1-schnell
    Space: black-forest-labs/FLUX.1-schnell
    Architecture: 12B parameter distilled rectified flow transformer by Black Forest Labs.
    Pricing: 100% Free / $0.00 (ZeroGPU community pool quota).
    """

    DEFAULT_SPACE = "black-forest-labs/FLUX.1-schnell"
    MODEL_ID = "black-forest-labs/FLUX.1-schnell"
    DEFAULT_STEPS = 4
    DEFAULT_WIDTH = 768
    DEFAULT_HEIGHT = 1344

    def __init__(
        self,
        space_repo_id: str = DEFAULT_SPACE,
        hf_token: Optional[str] = None,
        default_steps: int = DEFAULT_STEPS,
        env_file_path: Optional[Path] = None,
        timeout_seconds: float = 180.0,
    ):
        self.space_repo_id = space_repo_id
        self._hf_token = hf_token
        self.default_steps = default_steps
        self.timeout_seconds = timeout_seconds
        self._env_file_path = env_file_path or Path(".env")
        self._load_credentials()

    @property
    def provider_name(self) -> str:
        return "huggingface_flux_schnell"

    @property
    def model_id(self) -> str:
        return self.MODEL_ID

    @property
    def is_mock(self) -> bool:
        return False

    @property
    def is_paid(self) -> bool:
        return False

    @property
    def is_configured(self) -> bool:
        return HAS_GRADIO_CLIENT

    def _load_credentials(self) -> None:
        """Load HF_TOKEN if available, preserving zero token exposure."""
        if not self._hf_token:
            self._hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if not self._hf_token and self._env_file_path.exists():
            try:
                for line in self._env_file_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("HF_TOKEN=") or line.startswith("HUGGINGFACE_TOKEN="):
                        self._hf_token = line.split("=", 1)[1].strip().strip('"').strip("'")
            except Exception as e:
                logger.warning("Could not read HF token from .env: %s", type(e).__name__)

    @staticmethod
    def _snap_to_multiple_of_32(value: int, min_val: int = 256, max_val: int = 2048) -> int:
        """Snap dimension to the nearest multiple of 32 accepted by FLUX Space."""
        snapped = round(value / 32) * 32
        return max(min_val, min(max_val, snapped))

    def generate_scene_image(
        self,
        scene_number: int,
        positive_prompt: str,
        negative_prompt: str,
        output_path: Path,
        thumbnail_path: Optional[Path] = None,
        width: int = 1080,
        height: int = 1920,
        reference_image: Optional[str] = None,
    ) -> GeneratedImageMetadata:
        """Generate a vertical anime image using FLUX.1 Schnell on Hugging Face ZeroGPU."""
        if not HAS_GRADIO_CLIENT:
            raise RuntimeError(
                "gradio_client is not installed in the environment. Install via 'pip install gradio_client'."
            )

        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # For 9:16 vertical generation, use supported dimensions (multiples of 32)
        # If standard 1080x1920 is passed, use 768x1344 (aspect ratio 0.5714 ~ 9:16) or snapped 1088x1920
        if width == 1080 and height == 1920:
            req_w = self.DEFAULT_WIDTH
            req_h = self.DEFAULT_HEIGHT
        else:
            req_w = self._snap_to_multiple_of_32(width)
            req_h = self._snap_to_multiple_of_32(height)

        steps = float(self.default_steps)

        logger.info(
            "Connecting to Hugging Face Space '%s' for scene %d (%dx%d, steps=%.0f)...",
            self.space_repo_id, scene_number, req_w, req_h, steps
        )

        try:
            client = GradioClient(self.space_repo_id, token=self._hf_token)
        except Exception as e:
            raise RuntimeError(f"Failed to connect to Hugging Face Space '{self.space_repo_id}': {e}") from e

        start_time = time.time()

        try:
            # Single bounded request (0 retries on failure)
            job = client.submit(
                prompt=positive_prompt,
                seed=0,
                randomize_seed=True,
                width=int(req_w),
                height=int(req_h),
                num_inference_steps=int(steps),
                api_name="/infer",
            )
            result = job.result(timeout=self.timeout_seconds)
        except Exception as e:
            err_str = str(e)
            if "quota" in err_str.lower() or "gpu" in err_str.lower():
                raise RuntimeError(
                    f"ZeroGPU quota exhausted or unavailable for Space '{self.space_repo_id}': {err_str}"
                ) from e
            if "payment" in err_str.lower() or "billing" in err_str.lower() or "402" in err_str:
                raise RuntimeError(
                    f"COST SAFETY HARD BLOCK: Hugging Face space returned payment requirement: {err_str}"
                ) from e
            raise RuntimeError(f"Hugging Face FLUX generation failed: {err_str}") from e

        elapsed = time.time() - start_time

        # Result format: (result_image_filepath, seed)
        raw_image_path = None
        seed_used = 0
        if isinstance(result, (list, tuple)):
            raw_image_path = result[0]
            if len(result) > 1:
                seed_used = int(result[1])
        elif isinstance(result, dict):
            raw_image_path = result.get("path") or result.get("url")
        else:
            raw_image_path = str(result)

        if not raw_image_path or not Path(raw_image_path).exists():
            raise FileNotFoundError(f"FLUX Space did not return a valid image file: {result}")

        # Save to destination path, converting to true PNG if requested
        with Image.open(raw_image_path) as img:
            real_w, real_h = img.size
            if out_path.suffix.lower() == ".png":
                img.save(out_path, format="PNG")
            else:
                shutil.copy2(raw_image_path, out_path)
        logger.info("Saved FLUX image to %s (%dx%d) in %.2fs", out_path, real_w, real_h, elapsed)

        # Create thumbnail if requested
        thumb_str = None
        if thumbnail_path:
            t_path = Path(thumbnail_path)
            t_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(out_path) as img:
                img.thumbnail((360, 640), Image.LANCZOS)
                img.save(t_path, quality=85)
            thumb_str = str(t_path)

        # Calculate file metrics
        img_bytes = out_path.read_bytes()
        file_hash = hashlib.sha256(img_bytes).hexdigest()
        file_size = len(img_bytes)

        return GeneratedImageMetadata(
            scene_number=scene_number,
            image_path=str(out_path),
            thumbnail_path=thumb_str,
            provider=self.provider_name,
            model_id=self.MODEL_ID,
            prompt_used=positive_prompt,
            negative_prompt_used=negative_prompt,
            width=real_w,
            height=real_h,
            aspect_ratio=f"{real_w}:{real_h}",
            file_hash=file_hash,
            file_size_bytes=file_size,
            is_mock_asset=False,
            cost_usd=0.0,
            status=SceneImageStatus.PENDING_IMAGE_REVIEW,
            generation_duration_seconds=round(elapsed, 2),
            generated_at=datetime.now(timezone.utc),
            metadata={
                "space_repo_id": self.space_repo_id,
                "seed": seed_used,
                "steps": int(steps),
                "is_authenticated": bool(self._hf_token),
                "cost_verified_usd": 0.0,
            },
        )
