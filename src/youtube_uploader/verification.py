"""Remote YouTube video processing status verification."""

import time
from typing import Any, Dict, Optional, Tuple

from src.common.logger import setup_logger
from src.storage_manager.exceptions import VerificationUncertainError
from src.storage_manager.models import ProcessingStatus
from src.storage_manager.verifier import YouTubeUploadVerifier
from src.youtube_uploader.exceptions import VerificationTimeoutError

logger = setup_logger("youtube_verification")


class RemoteProcessingVerifier:
    """Verifies that an uploaded video finishes transcode and processing on YouTube."""

    def __init__(
        self,
        verifier: Optional[YouTubeUploadVerifier] = None,
        poll_interval_seconds: float = 5.0,
        max_timeout_seconds: float = 120.0,
    ):
        self.verifier = verifier or YouTubeUploadVerifier()
        self.poll_interval = poll_interval_seconds
        self.max_timeout = max_timeout_seconds

    def wait_until_processed(
        self,
        video_id: str,
        youtube_client: Any,
        video_url: Optional[str] = None,
    ) -> Tuple[bool, ProcessingStatus, Dict[str, Any]]:
        """Poll YouTube Data API v3 until video reaches 'processed', 'failed', or times out.

        Returns:
            Tuple[is_processed, processing_status, details]
        """
        start_time = time.time()
        attempt = 1

        logger.info(
            "Beginning processing verification for video '%s' (Timeout: %.1fs, Poll Interval: %.1fs)",
            video_id,
            self.max_timeout,
            self.poll_interval,
        )

        while (time.time() - start_time) < self.max_timeout:
            try:
                eligible, status, details = self.verifier.verify_remote_status(
                    video_id=video_id,
                    video_url=video_url,
                    youtube_client=youtube_client,
                )
            except VerificationUncertainError as vu_err:
                logger.warning("Transient verification uncertainty for '%s': %s", video_id, vu_err)
                status = ProcessingStatus.UNKNOWN
                details = {"error": str(vu_err)}

            if status == ProcessingStatus.PROCESSED:
                elapsed = round(time.time() - start_time, 2)
                logger.info("Video '%s' reached PROCESSED state on YouTube in %.2fs (attempt %d).", video_id, elapsed, attempt)
                return True, ProcessingStatus.PROCESSED, details

            if status in [ProcessingStatus.FAILED, ProcessingStatus.REJECTED]:
                elapsed = round(time.time() - start_time, 2)
                logger.error("Video '%s' entered FAILED state on YouTube in %.2fs: %s", video_id, elapsed, details)
                return False, status, details

            # Still in transcode ('uploaded' or 'processing' or 'unknown')
            time.sleep(self.poll_interval)
            attempt += 1

        elapsed = round(time.time() - start_time, 2)
        msg = f"Timed out waiting for video '{video_id}' to reach PROCESSED state on YouTube after {elapsed:.1f}s."
        logger.warning(msg)
        return False, ProcessingStatus.PROCESSING, {"error": "Verification timeout", "elapsed_seconds": elapsed}
