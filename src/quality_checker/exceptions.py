"""Domain exceptions for Quality Assurance and Media Validation."""


class QualityCheckerError(Exception):
    """Base exception for all quality checker failures."""


class QualityGateFailedError(QualityCheckerError):
    """Raised when a media asset or production fails a critical quality check."""


class InvalidMediaError(QualityCheckerError):
    """Raised when a media file is missing, unreadable, or corrupted."""


class MetadataValidationError(QualityCheckerError):
    """Raised when YouTube publication metadata violates constraints."""
