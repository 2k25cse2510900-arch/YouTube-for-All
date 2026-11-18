"""Domain exceptions for YouTube Upload Engine."""


class YouTubeUploadError(Exception):
    """Base exception for YouTube upload failures."""


class AuthenticationError(YouTubeUploadError):
    """Raised when OAuth credentials cannot be loaded, refreshed, or authenticated."""


class QuotaExceededError(YouTubeUploadError):
    """Raised when YouTube Data API v3 daily quota has been exhausted (HTTP 403 quotaExceeded)."""


class ApprovalRequiredError(YouTubeUploadError):
    """Raised when upload is attempted without valid human approval or if integrity checks fail."""


class UploadIntegrityError(YouTubeUploadError):
    """Raised when video file or metadata has mutated after human approval."""


class VerificationTimeoutError(YouTubeUploadError):
    """Raised when remote processing status checks on YouTube exceed timeout bounds."""


class DuplicateUploadError(YouTubeUploadError):
    """Raised when an identical upload is already active or published."""
