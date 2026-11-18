"""Voice Quality Evaluator for validating speech naturalness, cadence, clipping, and gap metrics."""

from dataclasses import dataclass, field
from enum import Enum
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from src.audio_engine.continuity import AudioContinuityProcessor, AudioMetrics
from src.audio_engine.models import TimestampBoundary
from src.common.logger import setup_logger

logger = setup_logger("voice_quality_evaluator")


class QualityStatus(str, Enum):
    """Evaluation status for voice quality checks."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


class VoiceLifecycleStatus(str, Enum):
    """Rigorous multi-stage lifecycle states for voice narration approval.

    CRITICAL RULE:
    A voice must NEVER be marked PRODUCTION_READY based solely on acoustic measurements,
    WAV formatting, or automated test passage. Production readiness strictly requires
    explicit human-listening review and approval.
    """

    TECHNICALLY_VALID = "TECHNICALLY_VALID"
    HINDI_PRONUNCIATION_VALIDATED = "HINDI_PRONUNCIATION_VALIDATED"
    HUMAN_LISTENING_REVIEW_PENDING = "HUMAN_LISTENING_REVIEW_PENDING"
    HUMAN_LISTENING_APPROVED = "HUMAN_LISTENING_APPROVED"
    HUMAN_LISTENING_FAILED = "HUMAN_LISTENING_FAILED"
    PRODUCTION_READY = "PRODUCTION_READY"


@dataclass
class QualityMetricCheck:
    """Individual quality check result with measurement and verdict."""

    name: str
    status: QualityStatus
    measured_value: Any
    threshold: str
    message: str


@dataclass
class VoiceQualityReport:
    """Comprehensive voiceover quality evaluation report."""

    audio_path: str
    overall_status: QualityStatus
    duration_seconds: float
    word_count: int
    speech_rate_wpm: float
    peak_dbfs: float
    rms_dbfs: float
    clipped_samples: int
    clipping_ratio: float
    max_silence_gap_seconds: float
    leading_silence_seconds: float
    trailing_silence_seconds: float
    checks: List[QualityMetricCheck] = field(default_factory=list)
    passed: bool = True
    summary: str = ""
    lifecycle_status: VoiceLifecycleStatus = VoiceLifecycleStatus.TECHNICALLY_VALID
    human_listening_score: Optional[float] = None
    human_listening_notes: Optional[str] = None
    is_production_ready: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "audio_path": self.audio_path,
            "overall_status": self.overall_status.value,
            "lifecycle_status": self.lifecycle_status.value,
            "is_production_ready": self.is_production_ready,
            "human_listening_score": self.human_listening_score,
            "human_listening_notes": self.human_listening_notes,
            "duration_seconds": self.duration_seconds,
            "word_count": self.word_count,
            "speech_rate_wpm": self.speech_rate_wpm,
            "peak_dbfs": self.peak_dbfs,
            "rms_dbfs": self.rms_dbfs,
            "clipped_samples": self.clipped_samples,
            "clipping_ratio": self.clipping_ratio,
            "max_silence_gap_seconds": self.max_silence_gap_seconds,
            "leading_silence_seconds": self.leading_silence_seconds,
            "trailing_silence_seconds": self.trailing_silence_seconds,
            "passed": self.passed,
            "summary": self.summary,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "measured": str(c.measured_value),
                    "threshold": c.threshold,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


class VoiceQualityChecker:
    """Automated voice evaluation suite verifying human-like cadence, audio clarity, and pacing."""

    def __init__(self, continuity_processor: Optional[AudioContinuityProcessor] = None):
        self.continuity = continuity_processor or AudioContinuityProcessor()

    def evaluate_audio(
        self,
        audio_path: Path,
        script_text: str,
        boundaries: Optional[List[TimestampBoundary]] = None,
        is_hindi_validated: bool = True,
        human_score: Optional[float] = None,
        human_approved: bool = False,
        human_notes: Optional[str] = None,
    ) -> VoiceQualityReport:
        """Perform comprehensive automated QA on synthesized voice audio."""
        p = Path(audio_path)
        if not p.is_file():
            raise FileNotFoundError(f"Audio file to evaluate does not exist: {p}")

        metrics = self.continuity.analyze_wav(p)
        words = re.findall(r"[\w\u0900-\u097F]+", script_text)
        word_count = len(words)

        duration = metrics.duration_seconds
        wpm = round((word_count / max(duration, 0.01)) * 60.0, 1) if duration > 0 else 0.0

        checks: List[QualityMetricCheck] = []

        # 1. Speech Rate (Target: 115 - 170 WPM for engaging Shorts narration)
        if 115.0 <= wpm <= 170.0:
            checks.append(
                QualityMetricCheck(
                    name="Speech Rate (WPM)",
                    status=QualityStatus.PASS,
                    measured_value=f"{wpm} WPM",
                    threshold="115 - 170 WPM",
                    message="Speech rate is in the optimal human conversational sweet spot.",
                )
            )
        elif 85.0 <= wpm < 115.0 or 170.0 < wpm <= 195.0:
            checks.append(
                QualityMetricCheck(
                    name="Speech Rate (WPM)",
                    status=QualityStatus.WARNING,
                    measured_value=f"{wpm} WPM",
                    threshold="115 - 170 WPM",
                    message="Speech rate is slightly outside optimal target but acceptable.",
                )
            )
        else:
            checks.append(
                QualityMetricCheck(
                    name="Speech Rate (WPM)",
                    status=QualityStatus.FAIL,
                    measured_value=f"{wpm} WPM",
                    threshold="95 - 190 WPM",
                    message="Speech rate is either unnaturally sluggish or rushed.",
                )
            )

        # 2. Excessive Silence Gaps (Target: <= 0.80s max internal pause)
        if metrics.max_silence_gap_seconds <= 0.80:
            checks.append(
                QualityMetricCheck(
                    name="Internal Pause Continuity",
                    status=QualityStatus.PASS,
                    measured_value=f"{metrics.max_silence_gap_seconds:.2f}s",
                    threshold="<= 0.80s",
                    message="No unnatural dead air gaps detected between phrases.",
                )
            )
        elif metrics.max_silence_gap_seconds <= 1.20:
            checks.append(
                QualityMetricCheck(
                    name="Internal Pause Continuity",
                    status=QualityStatus.WARNING,
                    measured_value=f"{metrics.max_silence_gap_seconds:.2f}s",
                    threshold="<= 0.80s",
                    message="Noticeable pause detected between clauses; verify pacing.",
                )
            )
        else:
            checks.append(
                QualityMetricCheck(
                    name="Internal Pause Continuity",
                    status=QualityStatus.FAIL,
                    measured_value=f"{metrics.max_silence_gap_seconds:.2f}s",
                    threshold="<= 1.20s",
                    message="Excessive dead air gap exceeds acceptable threshold.",
                )
            )

        # 3. Audio Clipping & Distortion (Target: clipping ratio < 0.0001)
        if metrics.clipping_ratio == 0.0:
            checks.append(
                QualityMetricCheck(
                    name="Digital Clipping",
                    status=QualityStatus.PASS,
                    measured_value=f"{metrics.clipped_samples} samples ({metrics.clipping_ratio:.4%})",
                    threshold="0 clipped samples",
                    message="Zero digital clipping detected; clean acoustic headroom.",
                )
            )
        elif metrics.clipping_ratio < 0.001:
            checks.append(
                QualityMetricCheck(
                    name="Digital Clipping",
                    status=QualityStatus.WARNING,
                    measured_value=f"{metrics.clipped_samples} samples ({metrics.clipping_ratio:.4%})",
                    threshold="< 0.1% clipping",
                    message="Minor transient peaks near full scale detected.",
                )
            )
        else:
            checks.append(
                QualityMetricCheck(
                    name="Digital Clipping",
                    status=QualityStatus.FAIL,
                    measured_value=f"{metrics.clipped_samples} samples ({metrics.clipping_ratio:.4%})",
                    threshold="< 0.1% clipping",
                    message="Severe digital clipping detected; audio may sound distorted.",
                )
            )

        # 4. Loudness Level Consistency (Target: RMS between -28 dBFS and -14 dBFS)
        if -28.0 <= metrics.rms_dbfs <= -14.0:
            checks.append(
                QualityMetricCheck(
                    name="RMS Loudness",
                    status=QualityStatus.PASS,
                    measured_value=f"{metrics.rms_dbfs:.1f} dBFS",
                    threshold="-28 to -14 dBFS",
                    message="Voice energy level is well-balanced for YouTube audio mixing.",
                )
            )
        elif -35.0 <= metrics.rms_dbfs < -28.0 or -14.0 < metrics.rms_dbfs <= -10.0:
            checks.append(
                QualityMetricCheck(
                    name="RMS Loudness",
                    status=QualityStatus.WARNING,
                    measured_value=f"{metrics.rms_dbfs:.1f} dBFS",
                    threshold="-28 to -14 dBFS",
                    message="Voice level is slightly low or high; ducking/mixing adjustments advised.",
                )
            )
        else:
            checks.append(
                QualityMetricCheck(
                    name="RMS Loudness",
                    status=QualityStatus.FAIL,
                    measured_value=f"{metrics.rms_dbfs:.1f} dBFS",
                    threshold="-35 to -10 dBFS",
                    message="Audio is inaudibly quiet or severely over-amplified.",
                )
            )

        # 5. Boundary Timestamp Fidelity (if boundaries provided)
        if boundaries:
            b_count = len(boundaries)
            if b_count >= int(word_count * 0.7):
                checks.append(
                    QualityMetricCheck(
                        name="Timestamp Coverage",
                        status=QualityStatus.PASS,
                        measured_value=f"{b_count} boundaries for {word_count} words",
                        threshold=">= 70% word coverage",
                        message="Fine-grained boundary timestamps successfully aligned.",
                    )
                )
            else:
                checks.append(
                    QualityMetricCheck(
                        name="Timestamp Coverage",
                        status=QualityStatus.WARNING,
                        measured_value=f"{b_count} boundaries for {word_count} words",
                        threshold=">= 70% word coverage",
                        message="Sparse boundary timestamps; subtitles may have sentence-level granularity.",
                    )
                )

        # Determine overall verdict
        has_fail = any(c.status == QualityStatus.FAIL for c in checks)
        has_warning = any(c.status == QualityStatus.WARNING for c in checks)

        if has_fail:
            overall = QualityStatus.FAIL
            passed = False
            summary = "Voice quality checks failed critical thresholds. Review errors above."
        elif has_warning:
            overall = QualityStatus.WARNING
            passed = True
            summary = "Voice quality passed with minor acoustic warnings."
        else:
            overall = QualityStatus.PASS
            passed = True
            summary = "All voice quality metrics passed optimal acoustic thresholds."

        # Determine multi-stage lifecycle status (Strict Quality Gate)
        if not passed:
            lifecycle = VoiceLifecycleStatus.TECHNICALLY_VALID
            is_prod_ready = False
        elif not is_hindi_validated:
            lifecycle = VoiceLifecycleStatus.TECHNICALLY_VALID
            is_prod_ready = False
        elif human_score is None:
            lifecycle = VoiceLifecycleStatus.HUMAN_LISTENING_REVIEW_PENDING
            is_prod_ready = False
            summary = f"{summary} Human listening review pending; not yet approved for production."
        elif human_approved and human_score >= 8.0:
            lifecycle = VoiceLifecycleStatus.PRODUCTION_READY
            is_prod_ready = True
            summary = f"{summary} Human listening approved ({human_score}/10). PRODUCTION READY."
        else:
            lifecycle = VoiceLifecycleStatus.HUMAN_LISTENING_FAILED
            is_prod_ready = False
            summary = f"{summary} Human listening evaluation FAILED ({human_score}/10): {human_notes or 'Artificial speech characteristics detected.'}"

        return VoiceQualityReport(
            audio_path=str(p),
            overall_status=overall,
            lifecycle_status=lifecycle,
            is_production_ready=is_prod_ready,
            human_listening_score=human_score,
            human_listening_notes=human_notes,
            duration_seconds=metrics.duration_seconds,
            word_count=word_count,
            speech_rate_wpm=wpm,
            peak_dbfs=metrics.peak_dbfs,
            rms_dbfs=metrics.rms_dbfs,
            clipped_samples=metrics.clipped_samples,
            clipping_ratio=metrics.clipping_ratio,
            max_silence_gap_seconds=metrics.max_silence_gap_seconds,
            leading_silence_seconds=metrics.leading_silence_seconds,
            trailing_silence_seconds=metrics.trailing_silence_seconds,
            checks=checks,
            passed=passed,
            summary=summary,
        )

    def record_human_listening_evaluation(
        self,
        report: VoiceQualityReport,
        score: float,
        approved: bool,
        notes: str,
    ) -> VoiceQualityReport:
        """Record formal human-listening evaluation result against a voice report."""
        report.human_listening_score = score
        report.human_listening_notes = notes

        if approved and score >= 8.0 and report.passed:
            report.lifecycle_status = VoiceLifecycleStatus.PRODUCTION_READY
            report.is_production_ready = True
            report.summary = f"Human listening evaluation APPROVED ({score}/10). Production ready."
        else:
            report.lifecycle_status = VoiceLifecycleStatus.HUMAN_LISTENING_FAILED
            report.is_production_ready = False
            report.summary = f"Human listening evaluation FAILED ({score}/10): {notes}"
        return report
