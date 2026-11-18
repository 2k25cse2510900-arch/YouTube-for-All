"""Quality Assurance Service coordinating video, audio, caption, and metadata checks."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.common.logger import setup_logger
from src.quality_checker.audio_checks import AudioChecker
from src.quality_checker.caption_checks import CaptionChecker
from src.quality_checker.exceptions import QualityGateFailedError
from src.quality_checker.fidelity_checks import FidelityChecker
from src.quality_checker.metadata_checks import MetadataChecker

from src.quality_checker.models import (
    CheckSeverity,
    QualityCheckResult,
    QualityReport,
    QualityStatus,
    QualityThresholds,
)
from src.quality_checker.video_checks import VideoChecker
from src.video_editor.ffmpeg_runner import FFmpegRunner

logger = setup_logger("quality_checker_service")


class QualityChecker:
    """Master Quality Assurance inspector for rendered YouTube Shorts productions."""

    def __init__(
        self,
        thresholds: Optional[QualityThresholds] = None,
        runner: Optional[FFmpegRunner] = None,
    ):
        self.thresholds = thresholds or QualityThresholds()
        self.runner = runner or FFmpegRunner()
        self.video_checker = VideoChecker(runner=self.runner, thresholds=self.thresholds)
        self.audio_checker = AudioChecker(runner=self.runner, thresholds=self.thresholds)
        self.caption_checker = CaptionChecker(thresholds=self.thresholds)
        self.metadata_checker = MetadataChecker(thresholds=self.thresholds)

    def check_production(
        self,
        production_id: str,
        video_path: Path,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        category_id: str = "27",
        default_language: str = "hi",
        privacy_status: str = "private",
        made_for_kids: Optional[bool] = False,
        caption_path: Optional[Path] = None,
        is_burned_in_captions: bool = False,
        allow_no_captions: bool = False,
        confirmed_burned_in_visually: bool = False,
        is_mock_asset: bool = False,
        output_report_path: Optional[Path] = None,
        skip_video_checks: bool = False,
        skip_audio_checks: bool = False,
        skip_caption_checks: bool = False,
        skip_metadata_checks: bool = False,
        skip_fidelity_checks: bool = False,
        script: Optional[Any] = None,
        storyboard: Optional[Any] = None,
        manifest: Optional[Any] = None,
        min_distinct_images: Optional[int] = None,
        bgm_track: Optional[Any] = None,
        approval: Optional[Any] = None,
    ) -> QualityReport:

        """Run full QA test suite across video, audio, captions, and metadata."""
        logger.info("Initiating Quality Check inspection for production '%s'", production_id)
        all_checks: List[QualityCheckResult] = []

        # 1. Video stream checks
        video_duration: Optional[float] = None
        if skip_video_checks:
            all_checks.append(
                QualityCheckResult(
                    check_name="video_inspection_suite",
                    status=QualityStatus.NOT_CHECKED,
                    severity=CheckSeverity.CRITICAL,
                    message="Video stream validation was skipped.",
                )
            )
        else:
            video_results = self.video_checker.run_checks(
                video_path=video_path,
                is_mock_asset=is_mock_asset,
            )
            all_checks.extend(video_results)

            # Extract video duration for dependent caption & audio sync checks
            for res in video_results:
                if res.check_name == "video_duration_valid" and isinstance(res.measured_value, (int, float)):
                    video_duration = float(res.measured_value)

        # 2. Audio checks
        if skip_audio_checks:
            all_checks.append(
                QualityCheckResult(
                    check_name="audio_inspection_suite",
                    status=QualityStatus.NOT_CHECKED,
                    severity=CheckSeverity.CRITICAL,
                    message="Audio stream validation was skipped.",
                )
            )
        else:
            audio_results = self.audio_checker.run_checks(
                media_path=video_path,
                expected_duration=video_duration,
            )
            all_checks.extend(audio_results)

        # 3. Caption checks
        if skip_caption_checks:
            all_checks.append(
                QualityCheckResult(
                    check_name="caption_inspection_suite",
                    status=QualityStatus.NOT_CHECKED,
                    severity=CheckSeverity.CRITICAL,
                    message="Caption validation was skipped.",
                )
            )
        else:
            caption_results = self.caption_checker.run_checks(
                caption_path=caption_path,
                video_duration=video_duration,
                is_burned_in=is_burned_in_captions,
                allow_no_captions=allow_no_captions,
                confirmed_burned_in_visually=confirmed_burned_in_visually,
            )
            all_checks.extend(caption_results)

        # 4. Metadata checks
        if skip_metadata_checks:
            all_checks.append(
                QualityCheckResult(
                    check_name="metadata_inspection_suite",
                    status=QualityStatus.NOT_CHECKED,
                    severity=CheckSeverity.CRITICAL,
                    message="Metadata validation was skipped.",
                )
            )
        else:
            metadata_results = self.metadata_checker.run_checks(
                title=title,
                description=description,
                tags=tags,
                category_id=category_id,
                default_language=default_language,
                privacy_status=privacy_status,
                made_for_kids=made_for_kids,
            )
            all_checks.extend(metadata_results)

        # 5. Script Fidelity, Narration Completeness & Music Attribution checks
        if not skip_fidelity_checks:
            if script:
                all_checks.append(FidelityChecker.check_source_script_integrity(script=script, storyboard=storyboard))
            if script and storyboard:
                all_checks.append(FidelityChecker.check_narration_completeness(script=script, storyboard=storyboard))
                all_checks.append(FidelityChecker.check_takeaway_presence(script=script, storyboard=storyboard))
                all_checks.append(FidelityChecker.check_scene_narration_ordering(script=script, storyboard=storyboard))
            if caption_path and script:
                all_checks.append(FidelityChecker.check_caption_completeness(script=script, caption_path=caption_path))
            if manifest:
                all_checks.append(
                    FidelityChecker.check_distinct_image_asset_count(
                        manifest=manifest,
                        storyboard=storyboard,
                        min_distinct_images=min_distinct_images or 10,
                    )
                )
            if bgm_track:
                all_checks.append(FidelityChecker.check_music_attribution_completeness(bgm_track=bgm_track, description=description))
            if approval:
                from src.youtube_uploader.models import UploadMetadata, PrivacyStatus
                try:
                    p_stat = PrivacyStatus(privacy_status)
                except ValueError:
                    p_stat = PrivacyStatus.PRIVATE
                u_meta = UploadMetadata(
                    title=title,
                    description=description,
                    tags=tags or [],
                    category_id=category_id,
                    default_language=default_language,
                    default_audio_language=default_language,
                    privacy_status=p_stat,
                    made_for_kids=made_for_kids or False,
                )
                all_checks.append(
                    FidelityChecker.check_approval_validity(
                        approval=approval,
                        video_path=video_path,
                        metadata=u_meta,
                        script=script,
                        storyboard=storyboard,
                    )
                )

        # Determine overall report status
        has_failures = any(c.status == QualityStatus.FAIL for c in all_checks)
        has_not_checked = any(c.status == QualityStatus.NOT_CHECKED for c in all_checks)
        has_warnings = any(c.status == QualityStatus.WARNING for c in all_checks)

        if has_failures:
            overall_status = QualityStatus.FAIL
        elif has_not_checked:
            overall_status = QualityStatus.NOT_CHECKED
        elif has_warnings:
            overall_status = QualityStatus.WARNING
        else:
            overall_status = QualityStatus.PASS

        report = QualityReport(
            production_id=production_id,
            overall_status=overall_status,
            checks=all_checks,
            created_at=datetime.now(timezone.utc),
        )

        # Persist report if destination specified
        if output_report_path:
            report.to_json_file(output_report_path)

        logger.info(
            "QA check complete for '%s': Status=%s (Passed: %d, Warnings: %d, Failures: %d)",
            production_id,
            overall_status.value,
            report.total_passed,
            report.total_warnings,
            report.total_failures,
        )
        return report

    def assert_upload_eligible(self, report: QualityReport) -> None:
        """Validate that a quality report has no critical failures blocking upload.

        Raises:
            QualityGateFailedError: If any check returned FAIL.
        """
        if not report.is_upload_eligible:
            failures = [f"{c.check_name}: {c.message}" for c in report.checks if c.status == QualityStatus.FAIL]
            not_checked = [f"{c.check_name}: {c.message}" for c in report.checks if c.status == QualityStatus.NOT_CHECKED]
            issues = failures + not_checked
            issues_preview = "; ".join(issues[:5])
            msg = (
                f"Quality gate rejected upload for production '{report.production_id}'. "
                f"{report.total_failures} failure(s) and {report.total_not_checked} incomplete inspection(s) detected: {issues_preview}"
            )
            logger.error(msg)
            raise QualityGateFailedError(msg)
