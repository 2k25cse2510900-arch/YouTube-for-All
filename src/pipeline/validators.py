"""Validation engines enforcing Human Approval and Safety Gates A through F."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.audio_engine.models import BGMTrackMetadata, VoiceSynthesisResult
from src.image_engine.models import GeneratedImageMetadata, SceneImageStatus, StoryboardImageManifest
from src.pipeline.exceptions import (
    HumanApprovalRequiredError,
    MissingAudioAssetError,
    MissingSceneImageError,
    MockAssetQuarantineError,
    QualityGateError,
    ScientificClaimUnverifiedError,
    ScriptNotApprovedError,
    StoryboardValidationError,
)
from src.pipeline.models import SceneImageInspectionReport
from src.quality_checker.models import QualityReport
from src.script_manager.models import ContentCategory, Script, ScriptStatus
from src.storyboard_generator.models import StoryboardDossier
from src.youtube_uploader.models import UploadApprovalRecord, UploadMetadata


class PipelineGatekeeper:
    """Central authority enforcing non-negotiable human approval and scientific verification gates."""

    @classmethod
    def validate_gate_a_script(cls, script: Script) -> None:
        """Gate A: Script must exist, have valid category, and be explicitly approved by human."""
        if not script or not script.id:
            raise ScriptNotApprovedError("Gate A Violation: Script is missing or has empty identifier.")

        if script.category not in [ContentCategory.ANIME_SCIENCE, ContentCategory.MOTIVATIONAL_STORY]:
            raise ScriptNotApprovedError(f"Gate A Violation: Unknown or unsupported content category '{script.category}'.")

        if script.status != ScriptStatus.APPROVED:
            msg = (
                f"Gate A Violation: Script '{script.id}' cannot enter production with status '{script.status.value}'. "
                f"Only scripts with status '{ScriptStatus.APPROVED.value}' signed off by human review are eligible. "
                "The pipeline will NEVER automatically approve scripts."
            )
            raise ScriptNotApprovedError(msg)

        if not script.hook.strip() or not script.body.strip() or not script.takeaway.strip():
            raise ScriptNotApprovedError(f"Gate A Violation: Script '{script.id}' has missing hook, body, or takeaway segments.")

    @classmethod
    def validate_script_fidelity(cls, storyboard: StoryboardDossier, script: Script) -> None:
        """Gate A.5: Verify that storyboard scene narration preserves approved script verbatim."""
        from src.storyboard_generator.fidelity import ScriptStoryboardFidelityValidator
        ScriptStoryboardFidelityValidator.validate_fidelity(script=script, storyboard=storyboard, raise_on_error=True)


    @classmethod
    def validate_gate_b_research(cls, storyboard: StoryboardDossier, script: Optional[Script] = None) -> None:
        """Gate B: For anime science, all empirical claims must be independently human-verified."""
        if not storyboard:
            raise StoryboardValidationError("Gate B Violation: Storyboard dossier is missing.")

        # Check unverified claims in storyboard
        if storyboard.has_unverified_claims or storyboard.claims_pending_verification:
            unverified_list = storyboard.claims_pending_verification or [
                c.claim for c in storyboard.scientific_claims if not c.is_verified
            ]
            msg = (
                f"Gate B Violation: Storyboard '{storyboard.storyboard_id}' contains {len(unverified_list)} "
                f"unverified scientific claim(s): {unverified_list}. "
                "Fictional anime canon must never be presented as empirical science without verified primary evidence. "
                "Human review must explicitly verify every claim before production."
            )
            raise ScientificClaimUnverifiedError(msg)

        # Check citations and verification on each scientific claim
        for c in storyboard.scientific_claims:
            if not c.is_verified:
                raise ScientificClaimUnverifiedError(f"Gate B Violation: Claim '{c.claim}' is not verified.")
            if not (c.url and c.url.strip()) or not (c.source_title and c.source_title.strip()):
                raise ScientificClaimUnverifiedError(
                    f"Gate B Violation: Claim '{c.claim}' is missing citation URL or title."
                )

        # Cross-check references in script if provided
        if script and script.category == ContentCategory.ANIME_SCIENCE:
            for ref in script.research_references:
                if not ref.is_verified:
                    raise ScientificClaimUnverifiedError(
                        f"Gate B Violation: Script '{script.id}' reference '{ref.claim}' is not verified."
                    )
                if getattr(ref, "confidence_score", 1.0) < 0.8:
                    raise ScientificClaimUnverifiedError(
                        f"Gate B Violation: Script '{script.id}' reference '{ref.claim}' has confidence score < 0.8."
                    )
                s_url = getattr(ref, "source_url", None) or getattr(ref, "source", None)
                s_title = getattr(ref, "source_title", None) or getattr(ref, "claim", None)
                if not (s_url and str(s_url).strip()) or not (s_title and str(s_title).strip()):
                    raise ScientificClaimUnverifiedError(
                        f"Gate B Violation: Script '{script.id}' reference '{ref.claim}' is missing citation URL or title."
                    )

    @classmethod
    def inspect_images(
        cls,
        storyboard: StoryboardDossier,
        manifest: Optional[StoryboardImageManifest] = None,
    ) -> SceneImageInspectionReport:
        """Inspect visual asset readiness and produce a detailed scene-by-scene report."""
        total_scenes = len(storyboard.scenes)
        scene_statuses: Dict[int, str] = {}
        missing: List[int] = []
        unapproved: List[int] = []
        mocks: List[int] = []

        manifest_images: Dict[int, GeneratedImageMetadata] = {}
        if manifest and manifest.images:
            manifest_images = {img.scene_number: img for img in manifest.images}

        for scene in storyboard.scenes:
            sn = scene.scene_number
            img = manifest_images.get(sn)
            if not img or not img.image_path or not Path(img.image_path).exists():
                scene_statuses[sn] = "missing"
                missing.append(sn)
            elif img.is_mock_asset:
                scene_statuses[sn] = "mock_asset (barriers active)"
                mocks.append(sn)
            elif img.status == SceneImageStatus.APPROVED:
                scene_statuses[sn] = "approved"
            else:
                scene_statuses[sn] = f"pending_review ({img.status.value})"
                unapproved.append(sn)

        is_ready = len(missing) == 0 and len(unapproved) == 0 and len(mocks) == 0

        detail_lines = [f"Scene {sn}: {status}" for sn, status in sorted(scene_statuses.items())]
        details = "\n".join(detail_lines)

        return SceneImageInspectionReport(
            storyboard_id=storyboard.storyboard_id,
            total_scenes=total_scenes,
            scene_statuses=scene_statuses,
            missing_scenes=missing,
            unapproved_scenes=unapproved,
            mock_scenes=mocks,
            is_ready_for_video=is_ready,
            details=details,
        )

    @classmethod
    def validate_gate_c_images(
        cls,
        storyboard: StoryboardDossier,
        manifest: Optional[StoryboardImageManifest] = None,
    ) -> SceneImageInspectionReport:
        """Gate C: All scenes must have valid, non-mock, human-approved 9:16 production images."""
        report = cls.inspect_images(storyboard, manifest=manifest)

        if report.mock_scenes:
            raise MockAssetQuarantineError(
                f"Gate C Violation: Storyboard '{storyboard.storyboard_id}' contains MOCK visual assets in scenes: "
                f"{report.mock_scenes}. Mock assets are strictly quarantined and barred from final video assembly."
            )

        if report.missing_scenes:
            raise MissingSceneImageError(
                f"Gate C Violation: Storyboard '{storyboard.storyboard_id}' has missing images for scenes: "
                f"{report.missing_scenes}.\nScene Status Report:\n{report.details}\n"
                "Please import real 1080x1920 images using ImageGenerationEngine.import_storyboard_images()."
            )

        if report.unapproved_scenes:
            raise HumanApprovalRequiredError(
                f"Gate C Violation: Storyboard '{storyboard.storyboard_id}' has images awaiting human approval in scenes: "
                f"{report.unapproved_scenes}. All images must be reviewed and approved prior to video rendering."
            )

        return report

    @classmethod
    def validate_gate_d_audio(
        cls,
        voice_result: Optional[VoiceSynthesisResult],
        bgm_track: Optional[BGMTrackMetadata] = None,
        require_bgm: bool = True,
        allow_synthetic_audio: bool = False,
    ) -> None:
        """Gate D: Voiceover must exist and be non-mock. BGM must be licensed and present on disk."""
        if not voice_result:
            raise MissingAudioAssetError("Gate D Violation: Voiceover synthesis result is missing.")

        voice_path = Path(voice_result.audio_path)
        if not voice_path.exists() or voice_path.stat().st_size == 0:
            raise MissingAudioAssetError(f"Gate D Violation: Voiceover audio file missing or 0 bytes: {voice_path}")

        if voice_result.is_mock_asset and not allow_synthetic_audio:
            raise MockAssetQuarantineError(
                "Gate D Violation: Voiceover is flagged as a MOCK asset. "
                "Mock audio is strictly barred from final video rendering."
            )

        if voice_result.duration_seconds <= 0.0:
            raise MissingAudioAssetError("Gate D Violation: Voiceover duration is 0 seconds.")

        if require_bgm:
            if not bgm_track:
                raise MissingAudioAssetError(
                    "Gate D Violation: Required Background Music (BGM) track is not specified. "
                    "A verified YouTube Audio Library track must be selected."
                )
            if not bgm_track.is_file_on_disk and not allow_synthetic_audio:
                raise MissingAudioAssetError(
                    f"Gate D Violation: BGM file for track '{bgm_track.title}' is not found on disk at '{bgm_track.file_path}'. "
                    "Synthetic sine wave substitution is barred in production. Please import the physical audio track."
                )

    @classmethod
    def validate_gate_e_video(cls, video_path: Path, quality_report: QualityReport) -> None:
        """Gate E: Rendered video must pass all quality inspections without failures or unchecked domains."""
        v_path = Path(video_path).resolve()
        if not v_path.exists() or v_path.stat().st_size == 0:
            raise QualityGateError(f"Gate E Violation: Video file missing or 0 bytes at '{v_path}'.")

        if not quality_report:
            raise QualityGateError("Gate E Violation: No quality check report provided for video.")

        if quality_report.total_failures > 0:
            failed_checks = [c.message for c in quality_report.checks if c.status.value == "FAIL"]
            raise QualityGateError(
                f"Gate E Violation: Quality checker rejected video with {quality_report.total_failures} failure(s): "
                f"{failed_checks}. All defects must be resolved before proceeding."
            )

        if quality_report.total_not_checked > 0:
            unchecked = [c.check_name for c in quality_report.checks if c.status.value == "NOT_CHECKED"]
            raise QualityGateError(
                f"Gate E Violation: Incomplete inspection. {quality_report.total_not_checked} check(s) were NOT_CHECKED: "
                f"{unchecked}. Every domain must be thoroughly inspected before upload eligibility is granted."
            )

        if not quality_report.is_upload_eligible:
            raise QualityGateError("Gate E Violation: Quality report status does not satisfy is_upload_eligible.")

    @classmethod
    def validate_gate_f_upload_approval(
        cls,
        approval: Optional[UploadApprovalRecord],
        video_path: Path,
        metadata: UploadMetadata,
        script: Optional[Script] = None,
        storyboard: Optional[StoryboardDossier] = None,
    ) -> None:
        """Gate F: Explicit, unexpired human approval with verified cryptographic checksums."""
        if not approval:
            raise HumanApprovalRequiredError("Gate F Violation: No human approval record provided.")

        if not approval.human_approved or not approval.approved_at:
            raise HumanApprovalRequiredError(
                f"Gate F Violation: Approval record for '{approval.production_id}' is not signed by a human approver."
            )

        is_valid, reason = approval.verify_integrity(
            current_video_path=video_path,
            current_metadata=metadata,
            current_script=script,
            current_storyboard=storyboard,
        )
        if not is_valid:
            raise HumanApprovalRequiredError(f"Gate F Security Violation: {reason}")

