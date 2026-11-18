"""Retry and error handling policies for YouTube API network calls."""

import random
import time
from typing import Callable, TypeVar

from googleapiclient.errors import HttpError

from src.common.logger import setup_logger
from src.youtube_uploader.exceptions import (
    AuthenticationError,
    QuotaExceededError,
    YouTubeUploadError,
)

logger = setup_logger("youtube_retry")

T = TypeVar("T")

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def is_quota_exceeded_error(err: HttpError) -> bool:
    """Detect if an HttpError represents YouTube API daily quota exhaustion."""
    if err.resp.status == 403:
        content = str(err.content or "").lower()
        if "quotaexceeded" in content or "daily limit exceeded" in content:
            return True
    return False


def execute_with_retry(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    operation_name: str = "YouTube API operation",
) -> T:
    """Execute a network callable with bounded exponential backoff and jitter.

    Permanent errors (400, quotaExceeded, etc.) fail immediately without retrying.
    """
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except HttpError as http_err:
            status = http_err.resp.status

            # Permanent failure: Unauthenticated (HTTP 401: token invalid/expired/revoked)
            if status == 401:
                msg = f"{operation_name} failed: YouTube API authentication error (HTTP 401). OAuth token expired or revoked."
                logger.critical(msg)
                raise AuthenticationError(msg) from http_err

            # Permanent failure: Quota exhausted
            if is_quota_exceeded_error(http_err):
                msg = f"{operation_name} failed: YouTube API daily quota exceeded."
                logger.critical(msg)
                raise QuotaExceededError(msg) from http_err

            # Check if retryable
            if status in RETRYABLE_STATUS_CODES and attempt < max_retries:
                # Add jitter
                jitter = random.uniform(0.1, 0.5)
                wait_time = delay + jitter
                logger.warning(
                    "%s encountered HTTP %d on attempt %d/%d. Retrying in %.2fs...",
                    operation_name,
                    status,
                    attempt,
                    max_retries,
                    wait_time,
                )
                time.sleep(wait_time)
                delay *= backoff_factor
            else:
                msg = f"{operation_name} failed with HTTP {status}: {http_err}"
                logger.error(msg)
                raise YouTubeUploadError(msg) from http_err

        except (ConnectionError, TimeoutError, OSError) as net_err:
            if attempt < max_retries:
                jitter = random.uniform(0.1, 0.5)
                wait_time = delay + jitter
                logger.warning(
                    "%s encountered connection error (%s) on attempt %d/%d. Retrying in %.2fs...",
                    operation_name,
                    type(net_err).__name__,
                    attempt,
                    max_retries,
                    wait_time,
                )
                time.sleep(wait_time)
                delay *= backoff_factor
            else:
                msg = f"{operation_name} failed after {max_retries} network attempts: {net_err}"
                logger.error(msg)
                raise YouTubeUploadError(msg) from net_err

    raise YouTubeUploadError(f"{operation_name} exhausted all {max_retries} attempts.")
