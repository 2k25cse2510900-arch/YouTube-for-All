"""Pillow-based offline mock image provider for zero-cost structural testing."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time
from typing import Optional

from PIL import Image, ImageDraw

from src.common.logger import setup_logger
from src.image_engine.cost_guard import CostSafetyGuard
from src.image_engine.models import GeneratedImageMetadata, SceneImageStatus
from src.image_engine.providers.base import BaseImageProvider

logger = setup_logger("mock_image_provider")


class PillowMockImageProvider(BaseImageProvider):
    """Generates structured 9:16 vertical image plates using local Pillow.

    CRITICAL RULES:
    1. Zero cost ($0.00), 100% offline, zero network access.
    2. Renders a prominent visual [MOCK ASSET] watermark across every image.
    3. Sets is_mock_asset=True on all metadata to prevent entering video production.
    """

    @property
    def provider_name(self) -> str:
        return "mock_pillow"

    @property
    def is_mock(self) -> bool:
        return True

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
        """Render a vertical 1080x1920 mock testing plate with visible watermarking."""
        start_time = time.perf_counter()

        # Enforce zero-cost guard before generation
        CostSafetyGuard.assert_zero_cost_provider(self.provider_name)

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Create vertical 9:16 canvas (Dark slate aesthetic)
        img = Image.new("RGB", (width, height), color=(17, 24, 39))  # Slate dark #111827
        draw = ImageDraw.Draw(img)

        # 2. Draw safe vertical mobile viewport guidelines
        margin_x = int(width * 0.08)
        margin_y = int(height * 0.12)
        draw.rectangle(
            [margin_x, margin_y, width - margin_x, height - margin_y],
            outline=(55, 65, 81),  # Border #374151
            width=4,
        )

        # 3. Draw Header
        draw.text(
            (margin_x + 30, margin_y + 40),
            f"A LESSON WITH AI | SCENE {scene_number:02d}",
            fill=(59, 130, 246),  # Blue #3B82F6
        )
        draw.text(
            (margin_x + 30, margin_y + 90),
            f"Resolution: {width}x{height} (Vertical 9:16 Mobile)",
            fill=(156, 163, 175),  # Gray
        )

        # 4. Draw Prominent MOCK WATERMARK BANNER across the center
        banner_top = int(height * 0.42)
        banner_bottom = int(height * 0.54)
        draw.rectangle(
            [0, banner_top, width, banner_bottom],
            fill=(185, 28, 28),  # Crimson Red #B91C1C
        )
        draw.text(
            (int(width * 0.10), banner_top + 40),
            "*** MOCK TESTING ASSET ***",
            fill=(254, 240, 138),  # Bright Yellow #FEF08A
        )
        draw.text(
            (int(width * 0.10), banner_top + 100),
            "STRICTLY FORBIDDEN IN FINAL VIDEO PRODUCTION",
            fill=(255, 255, 255),
        )
        draw.text(
            (int(width * 0.10), banner_top + 150),
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            fill=(254, 240, 138),
        )

        # 5. Draw prompt excerpt in the lower section
        draw.text(
            (margin_x + 30, banner_bottom + 60),
            "Synthesized Prompt Excerpt:",
            fill=(209, 213, 219),
        )
        # Word wrap prompt snippet
        words = positive_prompt.split()
        snippet_lines = []
        cur_line = []
        for w in words:
            cur_line.append(w)
            if len(" ".join(cur_line)) > 45:
                snippet_lines.append(" ".join(cur_line))
                cur_line = []
            if len(snippet_lines) >= 8:
                break
        if cur_line and len(snippet_lines) < 8:
            snippet_lines.append(" ".join(cur_line))

        y_offset = banner_bottom + 110
        for line in snippet_lines:
            draw.text((margin_x + 30, y_offset), line, fill=(156, 163, 175))
            y_offset += 35

        # 6. Save primary image
        img.save(output_path, format="PNG")
        duration = round(time.perf_counter() - start_time, 3)

        # 7. Generate lightweight thumbnail if requested
        thumb_str = None
        if thumbnail_path:
            thumbnail_path = Path(thumbnail_path)
            thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
            thumb = img.resize((270, 480), Image.Resampling.LANCZOS)
            thumb.save(thumbnail_path, format="JPEG", quality=80)
            thumb_str = str(thumbnail_path)

        # 8. Compute checksum and file size
        with open(output_path, "rb") as f:
            checksum = hashlib.sha256(f.read()).hexdigest()

        file_size = output_path.stat().st_size

        logger.info(
            "Mock plate for Scene %d successfully rendered to '%s' (Size: %d bytes, Time: %.3fs)",
            scene_number, output_path.name, file_size, duration
        )

        return GeneratedImageMetadata(
            scene_number=scene_number,
            image_path=str(output_path),
            thumbnail_path=thumb_str,
            provider=self.provider_name,
            model_id="pillow_mock_v1",
            prompt_used=positive_prompt,
            negative_prompt_used=negative_prompt,
            width=width,
            height=height,
            aspect_ratio="9:16",
            file_hash=checksum,
            file_size_bytes=file_size,
            is_mock_asset=True,  # CRITICAL: Always True for Mock provider
            cost_usd=0.0,  # Enforces ₹0
            status=SceneImageStatus.PENDING_IMAGE_REVIEW,
            generation_duration_seconds=duration,
            generated_at=datetime.now(timezone.utc),
        )
