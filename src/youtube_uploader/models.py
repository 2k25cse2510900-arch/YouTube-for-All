"""Data models for YouTube Uploader, Metadata, and Approval Records."""

from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, model_validator


class PrivacyStatus(str, Enum):
    """Supported YouTube publication privacy levels."""

    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class UploadMetadata(BaseModel):
    """Normalized metadata for a YouTube Shorts upload."""

    title: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: List[str] = Field(default_factory=list)
    category_id: str = Field(default="27", description="YouTube category (27=Education, 28=Science & Tech)")
    default_language: str = Field(default="hi")
    default_audio_language: str = Field(default="hi")
    privacy_status: PrivacyStatus = Field(
        default=PrivacyStatus.PRIVATE,
        description="Must default to PRIVATE. Public uploads require explicit configuration.",
    )
    made_for_kids: bool = Field(
        ...,
        description="Mandatory explicit setting; never None or guessed.",
    )

    def compute_checksum(self) -> str:
        """Calculate deterministic SHA-256 checksum of metadata fields."""
        payload = {
            "title": self.title,
            "description": self.description,
            "tags": sorted(self.tags),
            "category_id": self.category_id,
            "default_language": self.default_language,
            "default_audio_language": self.default_audio_language,
            "privacy_status": self.privacy_status.value,
            "made_for_kids": self.made_for_kids,
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class UploadProgress(BaseModel):
    """Real-time upload tracking state for resumable uploads."""

    bytes_uploaded: int = 0
    total_bytes: int = 0
    chunk_index: int = 0
    resumable_uri: Optional[str] = None

    @property
    def percentage(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return round((self.bytes_uploaded / self.total_bytes) * 100.0, 2)


class UploadResponse(BaseModel):
    """Structured response received upon successful upload."""

    video_id: str
    video_url: str
    upload_status: str
    privacy_status: str
    title: str
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_response: Dict[str, Any] = Field(default_factory=dict)


class UploadApprovalRecord(BaseModel):
    """Explicit human approval record gating YouTube upload with SHA-256 asset integrity verification.

    IMPORTANT SAFETY PRINCIPLE:
    - SHA-256 checksums provide content integrity verification (confirming that video, metadata, script,
      and narration have not mutated since approval was granted).
    - SHA-256 hashes do NOT prove human identity. Proof of human authorization comes from explicit
      human sign-off via CLI/orchestrator with documented reviewer notes, human_approved=True, and
      creator identity attestation.
    """

    production_id: str = Field(..., min_length=1)
    video_path: str = Field(..., min_length=1)
    video_checksum: str = Field(..., description="SHA-256 of the approved MP4 file")
    metadata_checksum: str = Field(..., description="SHA-256 of the approved metadata")

    # Content Integrity & Provenance Bindings (Asset integrity verification, not human identity)
    script_id: Optional[str] = Field(default=None, description="Bound Script ID")
    script_checksum: Optional[str] = Field(default=None, description="SHA-256 of the approved source script content")
    storyboard_id: Optional[str] = Field(default=None, description="Bound Storyboard ID")
    narration_checksum: Optional[str] = Field(default=None, description="SHA-256 of the approved spoken narration")

    quality_report_status: str = Field(default="PASS")
    requested_privacy: PrivacyStatus = Field(default=PrivacyStatus.PRIVATE)
    human_approved: bool = Field(default=False)
    approver_identity: str = Field(default="creator", description="Explicit identity or handle of the human approver.")
    human_approver_notes: Optional[str] = Field(default=None)
    approved_at: Optional[datetime] = None
    accepted_warnings: List[str] = Field(
        default_factory=list,
        description="Explicit list of QA warnings acknowledged by the human approver.",
    )
    approval_ttl_hours: int = Field(
        default=168,
        description="Validity window of human approval in hours (default: 7 days / 168 hours).",
    )

    def verify_integrity(
        self,
        current_video_path: Path,
        current_metadata: UploadMetadata,
        current_script: Optional[Any] = None,
        current_storyboard: Optional[Any] = None,
    ) -> Tuple[bool, str]:
        """Confirm that neither video, metadata, script, nor narration was modified after approval.

        Returns:
            Tuple[is_valid, failure_reason]
        """
        if not self.human_approved or not self.approved_at:
            return False, "Approval record has not received explicit human authorization."

        # TTL Expiration Check
        approval_age = datetime.now(timezone.utc) - self.approved_at
        if approval_age > timedelta(hours=self.approval_ttl_hours):
            return False, (
                f"Approval record has expired ({approval_age.total_seconds() / 3600:.1f} hours old, "
                f"TTL is {self.approval_ttl_hours} hours). Re-approval is required."
            )

        # Privacy Status Check
        if self.requested_privacy != current_metadata.privacy_status:
            return False, (
                f"Privacy status was modified after approval. "
                f"Approved '{self.requested_privacy.value}', current '{current_metadata.privacy_status.value}'."
            )

        video_file = Path(current_video_path).resolve()
        if not video_file.exists():
            return False, f"Approved video file not found at '{video_file}'."

        with open(video_file, "rb") as f:
            current_video_hash = hashlib.sha256(f.read()).hexdigest()

        if current_video_hash != self.video_checksum:
            return False, (
                f"Video file was modified after approval. "
                f"Approved hash '{self.video_checksum[:12]}...', current hash '{current_video_hash[:12]}...'."
            )

        current_meta_hash = current_metadata.compute_checksum()
        if current_meta_hash != self.metadata_checksum:
            return False, (
                f"Upload metadata was modified after approval. "
                f"Approved hash '{self.metadata_checksum[:12]}...', current hash '{current_meta_hash[:12]}...'."
            )

        # Script Content Check (if bound)
        if self.script_checksum and current_script:
            curr_script_hash = getattr(current_script, "content_hash", None)
            if curr_script_hash and curr_script_hash != self.script_checksum:
                return False, (
                    f"Source script was modified after approval. "
                    f"Approved checksum '{self.script_checksum[:12]}...', current checksum '{curr_script_hash[:12]}...'."
                )

        # Storyboard Narration Check (if bound)
        if self.narration_checksum and current_storyboard:
            curr_sb_narration_hash = getattr(current_storyboard, "storyboard_narration_checksum", None)
            if not curr_sb_narration_hash and hasattr(current_storyboard, "compute_narration_checksum"):
                curr_sb_narration_hash = current_storyboard.compute_narration_checksum()
            if curr_sb_narration_hash and curr_sb_narration_hash != self.narration_checksum:
                return False, (
                    f"Storyboard narration was modified after approval. "
                    f"Approved checksum '{self.narration_checksum[:12]}...', current checksum '{curr_sb_narration_hash[:12]}...'."
                )

        return True, "Integrity verified. Approval is intact and valid."

