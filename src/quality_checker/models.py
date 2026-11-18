"""Data models for Quality Checker and Pre-Upload Media Validation."""

from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QualityStatus(str, Enum):
    """Overall outcome of an individual check or entire inspection suite."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NOT_CHECKED = "NOT_CHECKED"


class CheckSeverity(str, Enum):
    """Impact level of a detected discrepancy."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class QualityThresholds(BaseModel):
    """Configurable boundaries and tolerances for YouTube Shorts validation."""

    expected_width: int = 1080
    expected_height: int = 1920
    expected_aspect_ratio: str = "9:16"
    min_fps: float = 23.97
    max_fps: float = 60.0
    min_duration_seconds: float = 20.0
    max_duration_seconds: float = 60.0  # Strict YouTube Shorts ceiling
    max_av_sync_drift_seconds: float = 0.50
    max_consecutive_silence_seconds: float = 3.5
    max_total_silence_ratio: float = 0.70  # Silence > 70% of video duration is considered defective
    min_audible_mean_volume_db: float = -50.0  # Mean volume below -50 dB is unusually quiet
    absolute_silence_threshold_db: float = -60.0  # Mean volume below -60 dB is considered completely silent
    clipping_peak_db: float = -0.10
    max_title_length: int = 100
    max_description_length: int = 5000
    max_total_tags_length: int = 500
    max_single_tag_length: int = 100


class QualityCheckResult(BaseModel):
    """Result of an individual quality check."""

    check_name: str = Field(..., description="Short canonical identifier for the check")
    status: QualityStatus = Field(..., description="PASS, WARNING, or FAIL")
    severity: CheckSeverity = Field(..., description="Severity category")
    message: str = Field(..., description="Explanation of finding or confirmation of pass")
    file_path: Optional[str] = Field(default=None, description="Path to evaluated asset")
    measured_value: Optional[Any] = Field(default=None, description="Observed parameter value")
    expected_value: Optional[Any] = Field(default=None, description="Configured requirement or range")
    suggested_correction: Optional[str] = Field(default=None, description="Actionable recommendation")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class QualityReport(BaseModel):
    """Structured QA audit summary for rendered Shorts productions."""

    production_id: str
    overall_status: QualityStatus
    checks: List[QualityCheckResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_passed(self) -> int:
        return sum(1 for c in self.checks if c.status == QualityStatus.PASS)

    @property
    def total_warnings(self) -> int:
        return sum(1 for c in self.checks if c.status == QualityStatus.WARNING)

    @property
    def total_failures(self) -> int:
        return sum(1 for c in self.checks if c.status == QualityStatus.FAIL)

    @property
    def total_not_checked(self) -> int:
        return sum(1 for c in self.checks if c.status == QualityStatus.NOT_CHECKED)

    @property
    def is_upload_eligible(self) -> bool:
        """Upload is blocked if ANY check returned FAIL or NOT_CHECKED. Warnings require explicit human acceptance."""
        return self.total_failures == 0 and self.total_not_checked == 0

    def to_summary_markdown(self) -> str:
        """Render a clean, human-readable markdown report."""
        lines = [
            f"# Quality Check Report: `{self.production_id}`",
            f"**Overall Status:** `{self.overall_status.value}`",
            f"**Generated:** {self.created_at.isoformat()}",
            f"**Checks Passed:** {self.total_passed} | **Warnings:** {self.total_warnings} | **Failures:** {self.total_failures} | **Not Checked:** {self.total_not_checked}",
            f"**Upload Eligible:** {'YES' if self.is_upload_eligible else 'NO (Blocked by Failures or Incomplete Checks)'}",
            "",
            "| Check Name | Status | Severity | Finding | Suggested Correction |",
            "|---|---|---|---|---|",
        ]
        for c in self.checks:
            corr = c.suggested_correction or "None"
            lines.append(f"| {c.check_name} | {c.status.value} | {c.severity.value} | {c.message} | {corr} |")
        return "\n".join(lines)

    def to_json_file(self, destination: Path) -> Path:
        """Write structured JSON report to disk."""
        dest = Path(destination).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(self.model_dump(mode="json"), f, indent=2)
        return dest
