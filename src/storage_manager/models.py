"""Data models for Storage Management, Asset Tracking, and Cleanup Manifests."""

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UploadStatus(str, Enum):
    """Lifecycle upload state of a YouTube Shorts production."""

    PENDING = "pending"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    VERIFIED = "verified"  # Successfully uploaded and processing confirmed on YouTube
    FAILED = "failed"
    ABANDONED = "abandoned"
    UNCERTAIN = "uncertain"  # Network interrupted mid-upload; YouTube status unknown


class ProcessingStatus(str, Enum):
    """YouTube server-side processing states."""

    UNKNOWN = "unknown"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    PROCESSED = "processed"  # YouTube has finished transcode; ready for public viewing
    FAILED = "failed"
    REJECTED = "rejected"


class CleanupStatus(str, Enum):
    """Storage cleanup status of local production assets."""

    PENDING = "pending"
    ELIGIBLE = "eligible"  # Verified on YouTube; safe to delete local temporary files
    CLEANED = "cleaned"  # Temporary files safely deleted
    FAILED = "failed"
    PRESERVED = "preserved"  # Retained due to upload failure, uncertainty, or error


class ProductionAssetType(str, Enum):
    """Types of temporary assets generated during Shorts production."""

    SCENE_IMAGE = "scene_image"
    VOICEOVER_AUDIO = "voiceover_audio"
    BGM_COPY = "bgm_copy"
    SFX_AUDIO = "sfx_audio"
    CAPTIONS = "captions"
    INTERMEDIATE_RENDER = "intermediate_render"
    FINAL_VIDEO = "final_video"


class ProductionAsset(BaseModel):
    """Represents a temporary asset generated for a Short."""

    asset_id: str = Field(..., description="Unique asset identifier")
    asset_type: ProductionAssetType = Field(...)
    file_path: str = Field(..., description="Absolute path to file on disk")
    file_size_bytes: int = Field(default=0, ge=0)
    file_hash: str = Field(default="", description="SHA-256 checksum")
    is_temporary: bool = Field(default=True, description="Always True for production assets")
    is_mock_asset: bool = Field(
        default=False,
        description="True if this asset is a mock/placeholder. Mock assets are strictly barred from video production.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary metadata such as provider, duration, etc.",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RetainedMetadata(BaseModel):
    """Permanent record retained after temporary production assets are cleaned up.

    CRITICAL RULE:
    This metadata must NEVER be deleted. It preserves the verifiable history of what was created
    and published without consuming storage on disk for raw video/images.
    """

    storyboard_id: str
    production_id: str
    title: str
    topic: str
    youtube_video_id: str
    youtube_url: str
    uploaded_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    cleaned_at: Optional[datetime] = None
    scientific_claims_count: int = 0
    human_reviewer_notes: Optional[str] = None
    privacy_status: str = "private"
    tags: List[str] = Field(default_factory=list)
    bgm_title: Optional[str] = None
    bgm_artist: Optional[str] = None
    bgm_source: Optional[str] = None
    bgm_license: Optional[str] = None
    bgm_attribution_text: Optional[str] = None
    retained_notes: str = Field(
        default="Local temporary production assets cleaned following verified YouTube publication."
    )


class UploadRecord(BaseModel):
    """Manifest tracking upload attempts, verification, and cleanup decisions."""

    production_id: str = Field(..., min_length=1)
    storyboard_id: str = Field(..., min_length=1)
    youtube_video_id: Optional[str] = None
    youtube_url: Optional[str] = None
    resumable_session_uri: Optional[str] = None
    upload_initiated_at: Optional[datetime] = None

    upload_status: UploadStatus = Field(default=UploadStatus.PENDING)
    processing_status: ProcessingStatus = Field(default=ProcessingStatus.UNKNOWN)
    cleanup_status: CleanupStatus = Field(default=CleanupStatus.PENDING)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    uploaded_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None
    cleaned_at: Optional[datetime] = None

    error_message: Optional[str] = None
    retained_metadata: Optional[RetainedMetadata] = None


class ProductionPackage(BaseModel):
    """Package tracking all generated assets and upload status for a single production run."""

    production_id: str = Field(..., min_length=1)
    storyboard_id: str = Field(..., min_length=1)
    root_dir: str = Field(..., description="Dedicated folder for this production")
    assets: List[ProductionAsset] = Field(default_factory=list)
    upload_record: UploadRecord

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_asset(self, asset_id: str) -> Optional[ProductionAsset]:
        for a in self.assets:
            if a.asset_id == asset_id:
                return a
        return None

    def add_asset(self, asset: ProductionAsset) -> None:
        self.assets = [a for a in self.assets if a.asset_id != asset.asset_id]
        self.assets.append(asset)
        self.updated_at = datetime.now(timezone.utc)

    @property
    def total_bytes(self) -> int:
        return sum(a.file_size_bytes for a in self.assets)


class CleanupReport(BaseModel):
    """Audit report generated during dry-run or actual asset cleanup."""

    production_id: str
    storyboard_id: str
    dry_run: bool = False
    eligible: bool = False
    status: CleanupStatus

    files_targeted: List[str] = Field(default_factory=list)
    files_deleted: List[str] = Field(default_factory=list)
    protected_files_preserved: List[str] = Field(default_factory=list)
    bytes_reclaimed: int = 0
    retained_metadata_path: Optional[str] = None
    reason: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
