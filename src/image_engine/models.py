"""Data models for Image Generation Engine and Manifest tracking."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class SceneImageStatus(str, Enum):
    """Lifecycle review states of an individual scene image."""

    PENDING = "pending"
    GENERATING = "generating"
    PENDING_IMAGE_REVIEW = "pending_image_review"  # Newly generated, awaiting human review
    APPROVED = "approved"  # Human approved for video composition
    REJECTED = "rejected"  # Human rejected, requires regeneration
    FAILED = "failed"


class ImageResolution(BaseModel):
    """Vertical mobile 9:16 rendering dimensions."""

    width: int = Field(default=1080, ge=360, le=3840)
    height: int = Field(default=1920, ge=640, le=3840)
    aspect_ratio: str = Field(default="9:16")

    @model_validator(mode="after")
    def validate_aspect_ratio(self) -> "ImageResolution":
        """Verify vertical 9:16 aspect ratio."""
        if self.height <= self.width:
            raise ValueError(f"Height ({self.height}) must be greater than width ({self.width}) for 9:16 vertical video.")
        return self


class GeneratedImageMetadata(BaseModel):
    """Metadata tracking a single generated scene image asset."""

    scene_number: int = Field(ge=1, description="Sequential scene index starting at 1")
    image_path: str = Field(..., min_length=1, description="Absolute or relative path to primary image file")
    thumbnail_path: Optional[str] = Field(default=None, description="Path to lightweight preview thumbnail")
    provider: str = Field(..., min_length=1, description="Provider used (e.g. 'mock_pillow')")
    model_id: str = Field(default="local_mock", description="Specific model ID or pipeline variant")

    prompt_used: str = Field(..., min_length=1, description="Full synthesized positive prompt")
    negative_prompt_used: str = Field(default="", description="Full synthesized negative prompt")

    width: int = Field(default=1080)
    height: int = Field(default=1920)
    aspect_ratio: str = Field(default="9:16")
    file_hash: str = Field(default="", description="SHA-256 checksum of image file")
    file_size_bytes: int = Field(default=0, ge=0)

    # CRITICAL SAFEGUARDS:
    is_mock_asset: bool = Field(
        default=False,
        description="True for Mock/Placeholder assets. Mock assets are permanently forbidden in video production.",
    )
    cost_usd: float = Field(
        default=0.0,
        le=0.0,
        description="Cost incurred. Enforces ₹0 budget ceiling.",
    )

    status: SceneImageStatus = Field(default=SceneImageStatus.PENDING_IMAGE_REVIEW)
    reviewer_notes: Optional[str] = None
    rejection_reason: Optional[str] = None

    generation_duration_seconds: float = Field(default=0.0, ge=0.0)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def mark_approved(self, notes: Optional[str] = None) -> None:
        """Mark image as approved by human reviewer."""
        self.status = SceneImageStatus.APPROVED
        self.reviewer_notes = notes
        self.approved_at = datetime.now(timezone.utc)

    def mark_rejected(self, reason: str) -> None:
        """Mark image as rejected, requesting regeneration."""
        self.status = SceneImageStatus.REJECTED
        self.rejection_reason = reason


class StoryboardImageManifest(BaseModel):
    """Manifest tracking all scene images, review statuses, and production readiness for a storyboard."""

    storyboard_id: str = Field(..., min_length=1, description="Identifier of associated StoryboardDossier")
    provider: str = Field(default="mock_pillow")
    total_scenes: int = Field(ge=1, description="Expected total scenes from storyboard")
    images: List[GeneratedImageMetadata] = Field(default_factory=list)

    all_approved: bool = Field(
        default=False,
        description="True ONLY when all scenes have generated assets and every scene is marked APPROVED.",
    )
    has_mock_assets: bool = Field(
        default=False,
        description="True if any scene uses a mock asset. Prevents video production entry.",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def sync_manifest_state(self) -> "StoryboardImageManifest":
        """Compute aggregated readiness flags."""
        if not self.images:
            self.all_approved = False
            self.has_mock_assets = False
            return self

        self.has_mock_assets = any(img.is_mock_asset for img in self.images)

        # All scenes must exist and be APPROVED to satisfy all_approved
        has_all_scenes = len(self.images) == self.total_scenes
        all_status_approved = all(img.status == SceneImageStatus.APPROVED for img in self.images)
        self.all_approved = has_all_scenes and all_status_approved
        return self

    def get_image(self, scene_number: int) -> Optional[GeneratedImageMetadata]:
        """Retrieve metadata for a specific scene."""
        for img in self.images:
            if img.scene_number == scene_number:
                return img
        return None

    def upsert_image(self, image: GeneratedImageMetadata) -> None:
        """Add or update an image for a specific scene."""
        self.images = [img for img in self.images if img.scene_number != image.scene_number]
        self.images.append(image)
        self.images.sort(key=lambda x: x.scene_number)
        self.updated_at = datetime.now(timezone.utc)
        self.sync_manifest_state()

    def approve_scene(self, scene_number: int, notes: Optional[str] = None) -> GeneratedImageMetadata:
        """Approve an individual scene's image."""
        img = self.get_image(scene_number)
        if not img:
            raise KeyError(f"No image found for scene {scene_number} in manifest.")
        img.mark_approved(notes=notes)
        self.updated_at = datetime.now(timezone.utc)
        self.sync_manifest_state()
        return img

    def reject_scene(self, scene_number: int, reason: str) -> GeneratedImageMetadata:
        """Reject an individual scene's image."""
        img = self.get_image(scene_number)
        if not img:
            raise KeyError(f"No image found for scene {scene_number} in manifest.")
        img.mark_rejected(reason=reason)
        self.updated_at = datetime.now(timezone.utc)
        self.sync_manifest_state()
        return img

    def approve_all(self, notes: Optional[str] = None) -> None:
        """Approve all currently generated images."""
        for img in self.images:
            img.mark_approved(notes=notes)
        self.updated_at = datetime.now(timezone.utc)
        self.sync_manifest_state()
