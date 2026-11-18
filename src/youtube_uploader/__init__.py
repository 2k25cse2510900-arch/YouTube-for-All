"""YouTube Uploader Module for A Lesson With AI.

Provides secure OAuth 2.0 client authentication, chunked resumable upload streaming,
strict human-approval validation, and automated YouTube processing verification.
"""

from src.youtube_uploader.approval import UploadApprovalGate
from src.youtube_uploader.client import YouTubeClientFactory
from src.youtube_uploader.exceptions import (
    ApprovalRequiredError,
    AuthenticationError,
    DuplicateUploadError,
    QuotaExceededError,
    UploadIntegrityError,
    VerificationTimeoutError,
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
from src.youtube_uploader.upload_service import YouTubeUploader
from src.youtube_uploader.verification import RemoteProcessingVerifier

__all__ = [
    "ApprovalRequiredError",
    "AuthenticationError",
    "DuplicateUploadError",
    "MetadataBuilder",
    "PrivacyStatus",
    "QuotaExceededError",
    "RemoteProcessingVerifier",
    "UploadApprovalGate",
    "UploadApprovalRecord",
    "UploadIntegrityError",
    "UploadMetadata",
    "UploadProgress",
    "UploadResponse",
    "VerificationTimeoutError",
    "YouTubeClientFactory",
    "YouTubeUploadError",
    "YouTubeUploader",
]
