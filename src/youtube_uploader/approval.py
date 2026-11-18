"""Human Approval Gatekeeper for YouTube Shorts Uploads."""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Optional

from src.common.logger import setup_logger
from src.quality_checker.models import QualityReport, QualityStatus
from src.youtube_uploader.exceptions import ApprovalRequiredError, UploadIntegrityError
from src.youtube_uploader.models import PrivacyStatus, UploadApprovalRecord, UploadMetadata

logger = setup_logger("upload_approval_gate")


class UploadApprovalGate:
    """Manages creation, verification, and integrity enforcement of human upload approvals."""

    @classmethod
    def create_approval_record(
        cls,
        production_id: str,
        video_path: Path,
        metadata: UploadMetadata,
        quality_report: QualityReport,
        approver_notes: str,
        requested_privacy: PrivacyStatus = PrivacyStatus.PRIVATE,
        accept_warnings: bool = False,
        approval_ttl_hours: int = 168,
        script: Optional[Any] = None,
        storyboard: Optional[Any] = None,
        approver_identity: str = "creator",
    ) -> UploadApprovalRecord:
        """Issue an explicit human upload approval record for a verified production.

        Enforces:
        - Mandatory non-empty reviewer notes providing explicit human authorization.
        - Zero critical QA failures.
        - Explicit acknowledgment of any warnings (accept_warnings=True).
        - SHA-256 bindings for video, metadata, script, and storyboard to detect post-approval mutation.
          (NOTE: SHA-256 provides asset integrity checking, not human identity verification).
        """
        if not approver_notes or not approver_notes.strip():
            raise ApprovalRequiredError(
                "Cannot create approval record: Mandatory human reviewer notes are missing. "
                "Human authorization requires documented review comments."
            )

        target_video = Path(video_path).resolve()
        if not target_video.exists():
            raise FileNotFoundError(f"Cannot approve missing video file: {target_video}")

        # Ensure Quality Report has no failures
        if not quality_report.is_upload_eligible:
            raise ApprovalRequiredError(
                f"Cannot create approval record: Quality report for '{production_id}' contains failures. "
                "All critical defects must be resolved before human sign-off."
            )

        # Warning acceptance requirement
        warnings_list = [c.message for c in quality_report.checks if c.status == QualityStatus.WARNING]
        if warnings_list and not accept_warnings:
            raise ApprovalRequiredError(
                f"Cannot create approval record: Quality report for '{production_id}' contains {len(warnings_list)} "
                "unacknowledged warning(s). The human approver must explicitly accept warnings with accept_warnings=True."
            )

        with open(target_video, "rb") as f:
            video_hash = hashlib.sha256(f.read()).hexdigest()

        meta_hash = metadata.compute_checksum()

        # Extract provenance from script and storyboard
        s_id = getattr(script, "id", None)
        s_hash = getattr(script, "content_hash", None)
        sb_id = getattr(storyboard, "storyboard_id", None)
        sb_hash = getattr(storyboard, "storyboard_narration_checksum", None)
        if not sb_hash and hasattr(storyboard, "compute_narration_checksum"):
            sb_hash = storyboard.compute_narration_checksum()

        record = UploadApprovalRecord(
            production_id=production_id,
            video_path=str(target_video),
            video_checksum=video_hash,
            metadata_checksum=meta_hash,
            script_id=s_id,
            script_checksum=s_hash,
            storyboard_id=sb_id,
            narration_checksum=sb_hash,
            quality_report_status=quality_report.overall_status.value,
            requested_privacy=requested_privacy,
            human_approved=True,
            approver_identity=approver_identity,
            human_approver_notes=approver_notes,
            approved_at=datetime.now(timezone.utc),
            accepted_warnings=warnings_list if accept_warnings else [],
            approval_ttl_hours=approval_ttl_hours,
        )

        logger.info(
            "Created human approval record for '%s' (Video SHA256: %s, Meta SHA256: %s, Script: %s)",
            production_id,
            video_hash[:12],
            meta_hash[:12],
            s_id or "none",
        )
        return record

    @classmethod
    def validate_approval(
        cls,
        approval: Optional[UploadApprovalRecord],
        current_video_path: Path,
        current_metadata: UploadMetadata,
        current_script: Optional[Any] = None,
        current_storyboard: Optional[Any] = None,
    ) -> None:
        """Enforce approval validity before permitting upload execution.

        Raises:
            ApprovalRequiredError: If record is missing or human_approved is False.
            UploadIntegrityError: If video file, metadata, script, or narration has mutated since approval.
        """
        if not approval:
            msg = "Upload rejected: No human approval record provided. Human authorization is mandatory."
            logger.error(msg)
            raise ApprovalRequiredError(msg)

        if not approval.human_approved or not approval.approved_at:
            msg = f"Upload rejected: Approval record for '{approval.production_id}' is not signed off by a human."
            logger.error(msg)
            raise ApprovalRequiredError(msg)

        is_valid, reason = approval.verify_integrity(
            current_video_path=current_video_path,
            current_metadata=current_metadata,
            current_script=current_script,
            current_storyboard=current_storyboard,
        )

        if not is_valid:
            logger.critical("Upload integrity failure for '%s': %s", approval.production_id, reason)
            raise UploadIntegrityError(f"Security violation: {reason}")

        logger.info("Upload approval verified successfully for production '%s'.", approval.production_id)

