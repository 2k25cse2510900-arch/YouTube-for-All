"""YouTube Upload & Processing Verifier for cleanup eligibility."""

import re
from typing import Any, Dict, Optional, Tuple

from config.settings import get_settings
from src.common.logger import setup_logger
from src.storage_manager.exceptions import VerificationUncertainError
from src.storage_manager.models import ProcessingStatus

logger = setup_logger("youtube_upload_verifier")

YOUTUBE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{11}$")


class YouTubeUploadVerifier:
    """Verifies that uploaded Shorts are live and successfully processed on YouTube before cleanup."""

    @classmethod
    def validate_id_and_url(cls, video_id: str, video_url: Optional[str] = None) -> bool:
        """Validate syntactic correctness of YouTube video ID and URL."""
        if not video_id or not YOUTUBE_ID_PATTERN.match(video_id.strip()):
            logger.warning("Invalid YouTube video ID format: '%s'", video_id)
            return False

        if video_url:
            clean_url = video_url.strip()
            if video_id not in clean_url:
                logger.warning("Video URL '%s' does not contain video ID '%s'", video_url, video_id)
                return False

        return True

    @classmethod
    def verify_remote_status(
        cls,
        video_id: str,
        video_url: Optional[str] = None,
        youtube_client: Optional[Any] = None,
    ) -> Tuple[bool, ProcessingStatus, Dict[str, Any]]:
        """Query YouTube Data API v3 to confirm video processing state.

        Returns:
            Tuple[is_eligible_for_cleanup, processing_status, details_dict]

        Rules:
        - Must verify video_id syntax.
        - Must query YouTube API.
        - uploadStatus == 'processed' is REQUIRED for cleanup eligibility.
        - uploadStatus == 'uploaded' or 'processing' means transcode is incomplete -> PRESERVE local files.
        - uploadStatus == 'failed' or 'rejected' -> PRESERVE local files for diagnosis.
        - Any network or authentication failure raises VerificationUncertainError -> PRESERVE local files.
        """
        if not cls.validate_id_and_url(video_id, video_url):
            return False, ProcessingStatus.FAILED, {"error": "Invalid video ID or mismatched URL"}

        if youtube_client is None:
            # If no client is provided and we cannot build one, verification is uncertain
            msg = "YouTube client not provided for verification. Verification is uncertain."
            logger.warning(msg)
            raise VerificationUncertainError(msg)

        try:
            response = youtube_client.videos().list(
                part="status,snippet",
                id=video_id,
            ).execute()
        except Exception as err:
            msg = f"Network or API exception querying YouTube video '{video_id}': {err}"
            logger.error(msg)
            raise VerificationUncertainError(msg) from err

        items = response.get("items", [])
        if not items:
            logger.warning("Video ID '%s' not found in YouTube channel.", video_id)
            return False, ProcessingStatus.FAILED, {"error": "Video ID not found on YouTube"}

        video_item = items[0]
        status_data = video_item.get("status", {})
        snippet_data = video_item.get("snippet", {})

        upload_status = status_data.get("uploadStatus", "").lower()
        privacy_status = status_data.get("privacyStatus", "").lower()
        title = snippet_data.get("title", "")

        details = {
            "title": title,
            "upload_status": upload_status,
            "privacy_status": privacy_status,
            "rejection_reason": status_data.get("rejectionReason"),
        }

        # 1. Processing Complete: Safe to clean up
        if upload_status == "processed":
            logger.info("Video '%s' is verified and PROCESSED on YouTube. Eligible for cleanup.", video_id)
            return True, ProcessingStatus.PROCESSED, details

        # 2. Still in progress: Must preserve files
        if upload_status in ["uploaded", "processing"]:
            logger.info("Video '%s' is currently '%s' on YouTube. Cleanup held until complete.", video_id, upload_status)
            return False, ProcessingStatus.PROCESSING, details

        # 3. Failed or Rejected: Must preserve files
        if upload_status in ["failed", "rejected"]:
            logger.warning("Video '%s' failed processing on YouTube (%s). Preserving local files.", video_id, upload_status)
            return False, ProcessingStatus.FAILED, details

        return False, ProcessingStatus.UNKNOWN, details
