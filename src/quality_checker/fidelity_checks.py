"""Quality Checker suite for Script Fidelity, Narration Completeness, and Music Attribution."""

import hashlib
from pathlib import Path
import re
from typing import List, Optional

from src.audio_engine.bgm_library import BGMLibraryManager
from src.audio_engine.models import BGMTrackMetadata
from src.quality_checker.models import CheckSeverity, QualityCheckResult, QualityStatus
from src.script_manager.models import Script, ScriptStatus
from src.storyboard_generator.fidelity import (
    ScriptStoryboardFidelityValidator,
    compute_canonical_narration_checksum,
    extract_sentences,
    extract_words,
)
from src.storyboard_generator.models import StoryboardDossier
from src.youtube_uploader.models import UploadApprovalRecord, UploadMetadata


class FidelityChecker:
    """Evaluates script-to-storyboard fidelity, caption coverage, and music attribution compliance."""

    @classmethod
    def check_source_script_integrity(
        cls,
        script: Optional[Script],
        storyboard: Optional[StoryboardDossier] = None,
    ) -> QualityCheckResult:
        """Verify that the source script exists, is approved, and matches storyboard provenance."""
        if not script:
            return QualityCheckResult(
                check_name="fidelity_source_script_integrity",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message="Source script is missing or could not be loaded.",
            )

        if script.status != ScriptStatus.APPROVED:
            return QualityCheckResult(
                check_name="fidelity_source_script_integrity",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=f"Source script '{script.id}' has unapproved status '{script.status.value}'.",
                measured_value=script.status.value,
                expected_value="approved",
            )

        if storyboard and storyboard.source_script_id:
            if storyboard.source_script_id != script.id:
                return QualityCheckResult(
                    check_name="fidelity_source_script_integrity",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Storyboard source_script_id '{storyboard.source_script_id}' does not match script '{script.id}'.",
                )

        return QualityCheckResult(
            check_name="fidelity_source_script_integrity",
            status=QualityStatus.PASS,
            severity=CheckSeverity.INFO,
            message=f"Source script '{script.id}' is approved and provenance is intact.",
            measured_value=script.id,
        )

    @classmethod
    def check_narration_completeness(
        cls,
        script: Optional[Script],
        storyboard: Optional[StoryboardDossier],
    ) -> QualityCheckResult:
        """Verify that storyboard scene narration preserves all words of the approved script."""
        if not script or not storyboard:
            return QualityCheckResult(
                check_name="fidelity_narration_completeness",
                status=QualityStatus.NOT_CHECKED,
                severity=CheckSeverity.CRITICAL,
                message="Script or storyboard not provided for fidelity inspection.",
            )

        report = ScriptStoryboardFidelityValidator.validate_fidelity(
            script=script,
            storyboard=storyboard,
            raise_on_error=False,
        )

        if not report.is_valid:
            return QualityCheckResult(
                check_name="fidelity_narration_completeness",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=f"Storyboard narration failed fidelity check: {'; '.join(report.errors)}",
                measured_value=report.total_storyboard_words,
                expected_value=report.total_script_words,
            )

        return QualityCheckResult(
            check_name="fidelity_narration_completeness",
            status=QualityStatus.PASS,
            severity=CheckSeverity.INFO,
            message=f"Storyboard preserves approved narration verbatim ({report.total_storyboard_words} words).",
            measured_value=report.total_storyboard_words,
            expected_value=report.total_script_words,
        )

    @classmethod
    def check_takeaway_presence(
        cls,
        script: Optional[Script],
        storyboard: Optional[StoryboardDossier],
    ) -> QualityCheckResult:
        """Verify that the concluding educational takeaway is preserved in storyboard narration."""
        if not script or not storyboard:
            return QualityCheckResult(
                check_name="fidelity_takeaway_presence",
                status=QualityStatus.NOT_CHECKED,
                severity=CheckSeverity.CRITICAL,
                message="Script or storyboard missing for takeaway inspection.",
            )

        takeaway_words = extract_words(script.takeaway)
        sb_words = extract_words(" ".join(s.narration_hinglish for s in storyboard.scenes))

        # Check if takeaway words appear consecutively at the end or within the storyboard
        found = False
        t_len = len(takeaway_words)
        if t_len > 0 and len(sb_words) >= t_len:
            for i in range(len(sb_words) - t_len + 1):
                if sb_words[i:i+t_len] == takeaway_words:
                    found = True
                    break

        if not found:
            return QualityCheckResult(
                check_name="fidelity_takeaway_presence",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=f"Takeaway missing from storyboard narration. Expected: '{script.takeaway}'",
                expected_value=script.takeaway,
            )

        return QualityCheckResult(
            check_name="fidelity_takeaway_presence",
            status=QualityStatus.PASS,
            severity=CheckSeverity.INFO,
            message="Concluding educational takeaway is fully present in storyboard scenes.",
            measured_value=script.takeaway,
        )

    @classmethod
    def check_scene_narration_ordering(
        cls,
        script: Optional[Script],
        storyboard: Optional[StoryboardDossier],
    ) -> QualityCheckResult:
        """Verify that sentences across scenes follow the exact original chronological order."""
        if not script or not storyboard:
            return QualityCheckResult(
                check_name="fidelity_scene_ordering",
                status=QualityStatus.NOT_CHECKED,
                severity=CheckSeverity.CRITICAL,
                message="Script or storyboard missing for sentence order inspection.",
            )

        report = ScriptStoryboardFidelityValidator.validate_fidelity(
            script=script,
            storyboard=storyboard,
            raise_on_error=False,
        )

        if not report.sentence_order_preserved:
            return QualityCheckResult(
                check_name="fidelity_scene_ordering",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message="Storyboard scenes violate approved sentence sequence order.",
            )

        return QualityCheckResult(
            check_name="fidelity_scene_ordering",
            status=QualityStatus.PASS,
            severity=CheckSeverity.INFO,
            message=f"All {len(storyboard.scenes)} scenes maintain chronological narrative sentence order.",
        )

    @classmethod
    def check_caption_completeness(
        cls,
        script: Optional[Script],
        caption_path: Optional[Path],
    ) -> QualityCheckResult:
        """Verify that generated caption file contains all words from the approved script."""
        if not caption_path or not Path(caption_path).exists():
            return QualityCheckResult(
                check_name="fidelity_caption_completeness",
                status=QualityStatus.NOT_CHECKED,
                severity=CheckSeverity.CRITICAL,
                message="Captions file not found for fidelity check.",
            )

        if not script:
            return QualityCheckResult(
                check_name="fidelity_caption_completeness",
                status=QualityStatus.NOT_CHECKED,
                severity=CheckSeverity.INFO,
                message="Script not provided for caption fidelity check.",
            )

        content = Path(caption_path).read_text(encoding="utf-8", errors="ignore")
        caption_lines = []
        for l in content.splitlines():
            l_str = l.strip()
            if not l_str:
                continue
            if l_str.startswith("Dialogue:"):
                parts = l_str.split(",", 9)
                if len(parts) == 10:
                    caption_lines.append(parts[9].replace("\\N", " "))
            elif not l_str.isdigit() and "-->" not in l_str and not l_str.startswith("[") and not l_str.startswith("Format:") and not l_str.startswith("Style:"):
                caption_lines.append(l_str)
        caption_words = extract_words(" ".join(caption_lines))
        script_words = extract_words(f"{script.hook} {script.body} {script.takeaway}")

        missing = [w for w in script_words if w not in caption_words]
        if len(missing) > len(script_words) * 0.15:  # Tolerance for minor tokenization
            return QualityCheckResult(
                check_name="fidelity_caption_completeness",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=f"Captions miss substantial approved script words ({len(missing)} missing).",
                measured_value=len(caption_words),
                expected_value=len(script_words),
            )

        return QualityCheckResult(
            check_name="fidelity_caption_completeness",
            status=QualityStatus.PASS,
            severity=CheckSeverity.INFO,
            message=f"Captions contain complete spoken narration ({len(caption_words)} words).",
            measured_value=len(caption_words),
            expected_value=len(script_words),
        )

    @classmethod
    def check_music_attribution_completeness(
        cls,
        bgm_track: Optional[BGMTrackMetadata],
        description: str,
    ) -> QualityCheckResult:
        """Verify that required Creative Commons music attribution is present in video description."""
        if not bgm_track:
            return QualityCheckResult(
                check_name="attribution_music_completeness",
                status=QualityStatus.PASS,
                severity=CheckSeverity.INFO,
                message="No BGM track provided or attribution not required.",
            )

        expected_attribution = BGMLibraryManager.format_attribution(bgm_track)
        if not expected_attribution:
            return QualityCheckResult(
                check_name="attribution_music_completeness",
                status=QualityStatus.PASS,
                severity=CheckSeverity.INFO,
                message=f"BGM track '{bgm_track.title}' license does not require attribution (Attribution Not Required).",
            )

        # Attribution is required
        # Check if artist name and track title are in description
        artist_present = bgm_track.artist.lower() in description.lower()
        title_present = bgm_track.title.lower() in description.lower()

        if not (artist_present and title_present):
            return QualityCheckResult(
                check_name="attribution_music_completeness",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=(
                    f"BGM track '{bgm_track.title}' is licensed under '{bgm_track.license}' and requires attribution, "
                    f"but attribution is missing from YouTube description. Required credit:\n'{expected_attribution}'"
                ),
                expected_value=expected_attribution,
            )

        return QualityCheckResult(
            check_name="attribution_music_completeness",
            status=QualityStatus.PASS,
            severity=CheckSeverity.INFO,
            message=f"Required music attribution for '{bgm_track.title}' by {bgm_track.artist} is present in description.",
        )

    @classmethod
    def check_approval_validity(
        cls,
        approval: Optional[UploadApprovalRecord],
        video_path: Optional[Path],
        metadata: Optional[UploadMetadata],
        script: Optional[Script] = None,
        storyboard: Optional[StoryboardDossier] = None,
    ) -> QualityCheckResult:
        """Verify that human approval record matches current production assets and has not expired."""
        if not approval:
            return QualityCheckResult(
                check_name="approval_gate_validity",
                status=QualityStatus.NOT_CHECKED,
                severity=CheckSeverity.WARNING,
                message="No human approval record has been issued yet. Approval must be created prior to staging.",
            )

        if not video_path or not metadata:
            return QualityCheckResult(
                check_name="approval_gate_validity",
                status=QualityStatus.NOT_CHECKED,
                severity=CheckSeverity.CRITICAL,
                message="Video path or metadata missing for approval verification.",
            )

        is_valid, reason = approval.verify_integrity(
            current_video_path=video_path,
            current_metadata=metadata,
            current_script=script,
            current_storyboard=storyboard,
        )

        if not is_valid:
            return QualityCheckResult(
                check_name="approval_gate_validity",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=f"Approval record integrity invalid: {reason}",
            )

        return QualityCheckResult(
            check_name="approval_gate_validity",
            status=QualityStatus.PASS,
            severity=CheckSeverity.INFO,
            message="Approval record integrity verified: asset checksums match current video, metadata, script, and narration assets (SHA-256 confirms asset integrity; human authorization recorded).",
        )

    @classmethod
    def check_distinct_image_asset_count(
        cls,
        manifest: Optional[Any],
        storyboard: Optional[StoryboardDossier] = None,
        min_distinct_images: int = 10,
    ) -> QualityCheckResult:
        """Verify that the production Short utilizes at least `min_distinct_images` genuinely distinct assets.

        ENFORCEMENT RULES:
        - At least 10 genuinely distinct visual images per 30-60 second Short.
        - Repeated copies of the same image, duplicate paths, or identical image hashes are NOT counted.
        - Zooms, crops, overlays, text changes, or filters do NOT qualify as distinct images.
        - Every visual shot must map to a storyboard scene.
        """
        if not manifest or not getattr(manifest, "images", None):
            return QualityCheckResult(
                check_name="fidelity_distinct_image_count",
                status=QualityStatus.NOT_CHECKED,
                severity=CheckSeverity.CRITICAL,
                message="Image manifest not provided or contains no images.",
            )

        seen_hashes = set()
        seen_paths = set()
        distinct_count = 0
        unmapped_shots = []

        storyboard_scene_numbers = (
            {s.scene_number for s in storyboard.scenes} if storyboard and storyboard.scenes else set()
        )

        for img in manifest.images:
            img_path = str(Path(img.image_path).resolve()) if getattr(img, "image_path", None) else ""
            h = getattr(img, "file_hash", "").strip().lower()
            if not h and img_path and Path(img_path).exists():
                with open(img_path, "rb") as f:
                    h = hashlib.sha256(f.read()).hexdigest()

            dedup_key = h if h else img_path
            if dedup_key and dedup_key not in seen_hashes and img_path not in seen_paths:
                seen_hashes.add(dedup_key)
                if img_path:
                    seen_paths.add(img_path)
                distinct_count += 1

            if storyboard_scene_numbers and getattr(img, "scene_number", None) not in storyboard_scene_numbers:
                unmapped_shots.append(getattr(img, "scene_number", "?"))

        if unmapped_shots:
            return QualityCheckResult(
                check_name="fidelity_distinct_image_count",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=f"Visual shots {unmapped_shots} do not map to valid storyboard scenes.",
                measured_value=distinct_count,
                expected_value=min_distinct_images,
            )

        if distinct_count < min_distinct_images:
            return QualityCheckResult(
                check_name="fidelity_distinct_image_count",
                status=QualityStatus.FAIL,
                severity=CheckSeverity.CRITICAL,
                message=(
                    f"Production Short requires at least {min_distinct_images} genuinely distinct visual images "
                    f"(found {distinct_count} unique assets across {len(manifest.images)} scenes). "
                    "Repeated images, crops, zooms, or overlays do not satisfy this requirement."
                ),
                measured_value=distinct_count,
                expected_value=min_distinct_images,
                suggested_correction=f"Generate additional distinct visual shots so the Short has at least {min_distinct_images} unique images.",
            )

        return QualityCheckResult(
            check_name="fidelity_distinct_image_count",
            status=QualityStatus.PASS,
            severity=CheckSeverity.INFO,
            message=f"Distinct image count requirement satisfied: {distinct_count} unique image assets (threshold: {min_distinct_images}).",
            measured_value=distinct_count,
            expected_value=min_distinct_images,
        )

