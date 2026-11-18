"""Resumable YouTube Video Uploader and Storage Integration Service."""

import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from googleapiclient.http import MediaFileUpload

from config.settings import get_settings
from src.common.logger import setup_logger
from src.quality_checker.models import QualityReport
from src.storage_manager.models import ProcessingStatus, UploadStatus
from src.storage_manager.service import StorageManager
from src.youtube_uploader.approval import UploadApprovalGate
from src.youtube_uploader.client import YouTubeClientFactory
from src.youtube_uploader.exceptions import (
    ApprovalRequiredError,
    AuthenticationError,
    DuplicateUploadError,
    QuotaExceededError,
    UploadIntegrityError,
    YouTubeUploadError,
)
from src.youtube_uploader.metadata import MetadataBuilder
from src.youtube_uploader.models import (
    PrivacyStatus,
    UploadApprovalRecord,
    UploadMetadata,
    UploadProgress,
    UploadResponse,
)
from src.youtube_uploader.retry import execute_with_retry
from src.youtube_uploader.verification import RemoteProcessingVerifier

logger = setup_logger("youtube_upload_service")

# 1MB chunk size: low memory footprint optimized for 8 GB RAM laptops
DEFAULT_CHUNK_SIZE = 1024 * 1024


class YouTubeUploader:
    """Manages secure, chunked, resumable YouTube Shorts uploads with mandatory approval gating."""

    def __init__(
        self,
        youtube_client: Optional[Any] = None,
        storage_manager: Optional[StorageManager] = None,
        processing_verifier: Optional[RemoteProcessingVerifier] = None,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        self.client = youtube_client
        self.storage_manager = storage_manager or StorageManager()
        self.verifier = processing_verifier or RemoteProcessingVerifier()
        self.chunk_size = chunk_size

    def get_client(self) -> Any:
        """Lazily initialize authenticated YouTube client if not injected."""
        if self.client is None:
            self.client = YouTubeClientFactory.get_authenticated_service()
        return self.client

    def upload_short(
        self,
        production_id: str,
        video_path: Path,
        metadata: UploadMetadata,
        approval: UploadApprovalRecord,
        quality_report: Optional[QualityReport] = None,
        on_progress: Optional[Callable[[UploadProgress], None]] = None,
        allow_public: bool = False,
        wait_for_processing: bool = False,
    ) -> UploadResponse:
        """Upload an approved Short to YouTube with full integrity and safety enforcement.

        Workflow:
        1. Step 0 Human Approval Gate: Validate cryptographic checksums of video and metadata.
        2. Quality Gate: Ensure quality report has zero critical failures.
        3. Prevent Duplicate Upload: Check storage manager state.
        4. Resource Construction: Build snippet and status with default PRIVATE privacy.
        5. Resumable Chunked Upload: Stream to YouTube without memory bloat.
        6. Storage Registration: Update StorageManager with video ID and URL.
        7. Optional Processing Verification: Poll until video transcode finishes.
        """
        video_file = Path(video_path).resolve()
        if not video_file.exists():
            raise FileNotFoundError(f"Video file to upload does not exist: {video_file}")

        file_size = video_file.stat().st_size
        if file_size == 0:
            raise YouTubeUploadError(f"Cannot upload empty file (0 bytes): {video_file}")

        # =========================================================================
        # 1. Human Approval Gate Enforcement
        # =========================================================================
        UploadApprovalGate.validate_approval(
            approval=approval,
            current_video_path=video_file,
            current_metadata=metadata,
        )

        # =========================================================================
        # 2. Quality Report Gate
        # =========================================================================
        if quality_report and not quality_report.is_upload_eligible:
            raise YouTubeUploadError(
                f"Upload blocked: Quality report for '{production_id}' contains unresolved failures."
            )

        # =========================================================================
        # 3. Duplicate Upload Prevention & Initiation Registration
        # =========================================================================
        package = self.storage_manager.get_package(production_id)
        if not package:
            # Initialize production package if not already registered
            self.storage_manager.create_production_package(
                storyboard_id=production_id,
                production_id=production_id,
            )

        # Atomically transition to UPLOADING and guard against concurrent or duplicate uploads
        try:
            self.storage_manager.record_upload_initiating(production_id)
        except Exception as dup_err:
            if "DuplicateUploadError" in type(dup_err).__name__:
                raise DuplicateUploadError(str(dup_err)) from dup_err
            raise

        # =========================================================================
        # 4. Construct API Payload
        # =========================================================================
        resource_body = MetadataBuilder.build_resource_payload(metadata, allow_public=allow_public)

        client = self.get_client()

        # =========================================================================
        # 5. Execute Resumable Chunked Upload
        # =========================================================================
        media = MediaFileUpload(
            str(video_file),
            mimetype="video/mp4",
            chunksize=self.chunk_size,
            resumable=True,
        )

        request = client.videos().insert(
            part="snippet,status",
            body=resource_body,
            media_body=media,
        )

        logger.info(
            "Starting resumable upload for '%s' (%d bytes, chunk size %d)",
            production_id,
            file_size,
            self.chunk_size,
        )

        progress_tracker = UploadProgress(bytes_uploaded=0, total_bytes=file_size, chunk_index=0)
        response_dict: Optional[Dict[str, Any]] = None

        try:
            while response_dict is None:
                def _send_chunk():
                    return request.next_chunk()

                status, response_dict = execute_with_retry(
                    _send_chunk,
                    max_retries=3,
                    operation_name=f"Upload chunk #{progress_tracker.chunk_index + 1}",
                )

                if status:
                    progress_tracker.bytes_uploaded = status.resumable_progress
                    progress_tracker.chunk_index += 1
                    raw_resumable_uri = getattr(request, "resumable_uri", None)
                    if isinstance(raw_resumable_uri, str) and raw_resumable_uri.strip():
                        progress_tracker.resumable_uri = raw_resumable_uri
                    logger.debug(
                        "Upload progress for '%s': %.1f%% (%d/%d bytes)",
                        production_id,
                        progress_tracker.percentage,
                        progress_tracker.bytes_uploaded,
                        file_size,
                    )
                    if on_progress:
                        on_progress(progress_tracker)

        except Exception as err:
            logger.error("Upload failed for production '%s': %s", production_id, err)
            is_uncertain = (
                isinstance(err, (ConnectionError, TimeoutError, OSError))
                or "timeout" in str(err).lower()
                or "connection" in str(err).lower()
                or progress_tracker.chunk_index > 0
            ) and not isinstance(err, (QuotaExceededError, AuthenticationError))

            res_uri = progress_tracker.resumable_uri or getattr(request, "resumable_uri", None)
            valid_session_uri = res_uri if isinstance(res_uri, str) and res_uri.strip() else None
            if is_uncertain:
                self.storage_manager.record_upload_uncertain(
                    production_id=production_id,
                    error_message=f"Upload outcome uncertain due to network interruption: {err}",
                    resumable_session_uri=valid_session_uri,
                )
            else:
                self.storage_manager.record_upload_failed(
                    production_id=production_id,
                    error_message=str(err),
                )
            raise

        if not response_dict or "id" not in response_dict:
            msg = f"YouTube API returned incomplete response without video ID: {response_dict}"
            logger.critical(msg)
            self.storage_manager.record_upload_failed(production_id, msg)
            raise YouTubeUploadError(msg)

        video_id = response_dict["id"]
        video_url = f"https://youtu.be/{video_id}"
        snippet = response_dict.get("snippet", {})
        status_info = response_dict.get("status", {})

        logger.info("Upload successful! Production '%s' assigned YouTube ID '%s' (%s)", production_id, video_id, video_url)

        # =========================================================================
        # 6. Record Upload in StorageManager
        # =========================================================================
        self.storage_manager.record_upload_started(
            production_id=production_id,
            video_id=video_id,
            video_url=video_url,
        )

        upload_response = UploadResponse(
            video_id=video_id,
            video_url=video_url,
            upload_status=status_info.get("uploadStatus", "uploaded"),
            privacy_status=status_info.get("privacyStatus", metadata.privacy_status.value),
            title=snippet.get("title", metadata.title),
            raw_response=response_dict,
        )

        # =========================================================================
        # 7. Optional Remote Processing Verification
        # =========================================================================
        if wait_for_processing:
            is_processed, proc_status, details = self.verifier.wait_until_processed(
                video_id=video_id,
                youtube_client=client,
                video_url=video_url,
            )
            if is_processed:
                logger.info("Remote processing confirmed for '%s'. Marking verified.", video_id)
                pkg = self.storage_manager.get_package(production_id)
                if pkg:
                    pkg.upload_record.upload_status = UploadStatus.VERIFIED
                    pkg.upload_record.processing_status = ProcessingStatus.PROCESSED
                    self.storage_manager._save_package(pkg)
            else:
                logger.warning("Remote processing not yet complete for '%s' (Status: %s)", video_id, proc_status.value)

        return upload_response
