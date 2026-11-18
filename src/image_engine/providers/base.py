"""Abstract Base Provider for Image Generation Engine."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from src.image_engine.models import GeneratedImageMetadata


class BaseImageProvider(ABC):
    """Abstract interface for all image generation providers.

    Guarantees provider independence, zero-cost compliance, and consistent metadata tracking.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier for this provider."""
        pass

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        """True if provider creates mock testing assets rather than real AI visuals."""
        pass

    @property
    @abstractmethod
    def is_paid(self) -> bool:
        """True if provider requires paid credits or external API billing."""
        pass

    @property
    def supports_reference_image(self) -> bool:
        """Whether this provider accepts a character reference image input."""
        return False

    @abstractmethod
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
        """Generate a vertical 9:16 image for the specified scene."""
        pass
