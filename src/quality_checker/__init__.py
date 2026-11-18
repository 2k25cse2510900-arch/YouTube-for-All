"""Quality Assurance & Validation Module for A Lesson With AI.

Validates rendered media, audio loudness, caption synchronicity, and YouTube publication metadata.
"""

from src.quality_checker.exceptions import (
    InvalidMediaError,
    MetadataValidationError,
    QualityCheckerError,
    QualityGateFailedError,
)
from src.quality_checker.models import (
    CheckSeverity,
    QualityCheckResult,
    QualityReport,
    QualityStatus,
    QualityThresholds,
)
from src.quality_checker.service import QualityChecker

__all__ = [
    "CheckSeverity",
    "InvalidMediaError",
    "MetadataValidationError",
    "QualityChecker",
    "QualityCheckerError",
    "QualityCheckResult",
    "QualityGateFailedError",
    "QualityReport",
    "QualityStatus",
    "QualityThresholds",
]
