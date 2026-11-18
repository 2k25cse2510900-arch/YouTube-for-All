"""Formatting and diagnostic reporting for Pipeline Orchestration."""

from typing import Any, Dict, List, Optional

from src.pipeline.models import PipelineProductionState, PipelineStage, SceneImageInspectionReport, StageStatus
from src.quality_checker.models import QualityReport, QualityStatus


class PipelineReporter:
    """Generates human-readable terminal and markdown reports for pipeline operations."""

    @classmethod
    def format_production_status(cls, state: PipelineProductionState) -> str:
        """Format stage-by-stage status table for a production run."""
        lines = [
            f"# Pipeline Production Report: `{state.production_id}`",
            f"**Script ID:** `{state.script_id}` | **Storyboard ID:** `{state.storyboard_id}`",
            f"**Current Stage:** `{state.current_stage.value}` | **Overall Status:** **{state.overall_status.value.upper()}**",
            f"**Upload Enabled:** `{state.upload_enabled}` | **Recovered:** `{state.is_recovered}`",
            "",
            "| Stage | Status | Assets Generated | Notes / Diagnostic |",
            "| :--- | :---: | :--- | :--- |",
        ]

        stage_order = [
            PipelineStage.SCRIPT_SELECTION,
            PipelineStage.SCRIPT_VALIDATION,
            PipelineStage.RESEARCH_VERIFICATION,
            PipelineStage.STORYBOARD_VALIDATION,
            PipelineStage.PACKAGE_CREATION,
            PipelineStage.IMAGE_VALIDATION,
            PipelineStage.VOICE_SYNTHESIS,
            PipelineStage.CAPTION_GENERATION,
            PipelineStage.AUDIO_MIXING,
            PipelineStage.VIDEO_RENDERING,
            PipelineStage.QUALITY_CHECK,
            PipelineStage.HUMAN_REVIEW,
            PipelineStage.UPLOAD_PREPARATION,
            PipelineStage.YOUTUBE_UPLOAD,
            PipelineStage.STORAGE_CLEANUP,
        ]

        for stg in stage_order:
            rec = state.stages.get(stg.value)
            if not rec:
                lines.append(f"| `{stg.value}` | PENDING | - | - |")
                continue

            status_str = rec.status.value.upper()
            if rec.status == StageStatus.COMPLETED:
                status_icon = f"**{status_str}**"
            elif rec.status == StageStatus.RUNNING:
                status_icon = f"*{status_str}*"
            elif rec.status in [StageStatus.FAILED, StageStatus.BLOCKED]:
                status_icon = f"**{status_str}**"
            else:
                status_icon = status_str

            assets_summary = ", ".join(rec.output_assets.keys()) if rec.output_assets else "-"
            notes = rec.error_message or rec.notes or "-"
            if len(notes) > 60:
                notes = notes[:57] + "..."

            lines.append(f"| `{stg.value}` | {status_icon} | {assets_summary} | {notes} |")

        if state.error_message:
            lines.extend(["", f"> [!WARNING] **Error Details:** {state.error_message}"])

        return "\n".join(lines)

    @classmethod
    def format_scene_images_report(cls, report: SceneImageInspectionReport) -> str:
        """Format visual asset status per scene."""
        lines = [
            f"### Visual Asset Readiness: `{report.storyboard_id}`",
            f"Total Scenes: {report.total_scenes} | Ready for Video: **{'YES' if report.is_ready_for_video else 'NO'}**",
            "",
        ]
        for sn, status in sorted(report.scene_statuses.items()):
            indicator = "PASS" if status == "approved" else "FAIL"
            lines.append(f"- Scene {sn:02d}: [{indicator}] {status}")

        if report.missing_scenes:
            lines.append(f"\nMissing Images ({len(report.missing_scenes)}): Scenes {report.missing_scenes}")
        if report.unapproved_scenes:
            lines.append(f"Pending Approval ({len(report.unapproved_scenes)}): Scenes {report.unapproved_scenes}")
        if report.mock_scenes:
            lines.append(f"Mock Quarantined ({len(report.mock_scenes)}): Scenes {report.mock_scenes}")

        return "\n".join(lines)

    @classmethod
    def format_quality_summary(cls, report: QualityReport) -> str:
        """Format clean quality check summary for video, audio, captions, and metadata."""
        lines = [
            f"### Quality Gate Report: `{report.production_id}`",
            f"Overall Status: **{report.overall_status.value}** | Upload Eligible: **{'YES' if report.is_upload_eligible else 'NO'}**",
            f"Total Failures: {report.total_failures} | Total Not Checked: {report.total_not_checked} | Total Warnings: {report.total_warnings}",
            "",
        ]

        categories = ["video", "audio", "captions", "metadata"]
        for cat in categories:
            cat_checks = [c for c in report.checks if c.category == cat]
            if not cat_checks:
                lines.append(f"{cat.upper()}: No checks recorded")
                continue

            failures = sum(1 for c in cat_checks if c.status == QualityStatus.FAIL)
            warnings = sum(1 for c in cat_checks if c.status == QualityStatus.WARNING)
            not_checked = sum(1 for c in cat_checks if c.status == QualityStatus.NOT_CHECKED)

            if failures > 0:
                cat_status = "FAIL"
            elif not_checked > 0:
                cat_status = "NOT_CHECKED"
            elif warnings > 0:
                cat_status = "WARNING"
            else:
                cat_status = "PASS"

            lines.append(f"{cat.upper()}: [{cat_status}] ({len(cat_checks)} checks, {failures} fail, {warnings} warn, {not_checked} unchecked)")
            for c in cat_checks:
                if c.status in [QualityStatus.FAIL, QualityStatus.WARNING, QualityStatus.NOT_CHECKED]:
                    lines.append(f"  - [{c.status.value}] {c.check_name}: {c.message}")

        return "\n".join(lines)

    @classmethod
    def format_recovery_report(cls, plan: Dict[str, Any]) -> str:
        """Format crash recovery diagnostic report."""
        lines = [
            f"### Crash Recovery Report: `{plan['production_id']}`",
            f"Script ID: `{plan['script_id']}` | Storyboard ID: `{plan['storyboard_id']}`",
            f"Last Intact Checkpoint: `{plan['last_intact_stage'] or 'None'}`",
            f"Next Resumption Stage: **`{plan['resume_stage']}`**",
            f"Verified Assets on Disk: {plan['verified_assets_count']} file(s)",
            f"Invalidated Stages: {plan['invalidated_stages'] or 'None'}",
            f"Can Resume: **{'YES' if plan['can_resume'] else 'NO'}**",
        ]
        return "\n".join(lines)
