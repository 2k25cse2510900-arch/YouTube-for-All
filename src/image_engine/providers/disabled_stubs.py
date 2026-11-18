"""Disabled provider stubs for future local or manually operated cloud generation.

These providers are permanently disabled and inactive until explicitly approved and configured.
"""

from pathlib import Path
from typing import Optional

from src.image_engine.exceptions import DisabledProviderError
from src.image_engine.models import GeneratedImageMetadata
from src.image_engine.providers.base import BaseImageProvider


class DisabledLocalGPUProvider(BaseImageProvider):
    """Dormant architectural stub for future local GPU / ComfyUI inference.

    Remains strictly disabled until hardware suitability is approved and dependencies installed.
    """

    @property
    def provider_name(self) -> str:
        return "disabled_local_gpu"

    @property
    def is_mock(self) -> bool:
        return False

    @property
    def is_paid(self) -> bool:
        return False

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
        raise DisabledProviderError(
            "DisabledLocalGPUProvider is currently INACTIVE. "
            "No local diffusion model weights have been downloaded, and no GPU inference is enabled."
        )


class DisabledPaidProviderStub(BaseImageProvider):
    """Permanently locked stub for external paid APIs to guarantee zero-cost safety."""

    @property
    def provider_name(self) -> str:
        return "disabled_paid_stub"

    @property
    def is_mock(self) -> bool:
        return False

    @property
    def is_paid(self) -> bool:
        return True

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
        raise DisabledProviderError(
            "Paid providers are permanently blocked under the strict ₹0 operating budget."
        )
