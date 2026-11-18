"""Metadata validation checks for YouTube Shorts publications."""

from typing import Any, Dict, List, Optional
from src.common.logger import setup_logger
from src.quality_checker.models import (
    CheckSeverity,
    QualityCheckResult,
    QualityStatus,
    QualityThresholds,
)

logger = setup_logger("quality_checker_metadata")

VALID_YOUTUBE_CATEGORIES = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",  # Primary for A Lesson With AI
    "28": "Science & Technology",  # Primary for Anime Science
}

PLACEHOLDER_SUBSTRINGS = [
    "todo",
    "lorem ipsum",
    "sample title",
    "placeholder",
    "insert title here",
    "draft title",
    "test video",
    "[insert",
    "mock asset",
]


class MetadataChecker:
    """Validates YouTube publication snippets and status before upload."""

    def __init__(self, thresholds: Optional[QualityThresholds] = None):
        self.thresholds = thresholds or QualityThresholds()

    def run_checks(
        self,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        category_id: str = "27",
        default_language: str = "hi",
        privacy_status: str = "private",
        made_for_kids: Optional[bool] = None,
    ) -> List[QualityCheckResult]:
        """Execute complete metadata inspection suite."""
        results: List[QualityCheckResult] = []
        tags = tags or []

        # 1. Title validation
        clean_title = (title or "").strip()
        if not clean_title:
            results.append(
                QualityCheckResult(
                    check_name="metadata_title_present",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message="Title is missing or empty.",
                    suggested_correction="Provide a valid YouTube Short title.",
                )
            )
        elif len(clean_title) > self.thresholds.max_title_length:
            results.append(
                QualityCheckResult(
                    check_name="metadata_title_length",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Title length ({len(clean_title)} chars) exceeds YouTube limit ({self.thresholds.max_title_length} chars).",
                    measured_value=len(clean_title),
                    expected_value=f"<={self.thresholds.max_title_length}",
                    suggested_correction="Shorten title to <= 100 characters.",
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="metadata_title_valid",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Title is valid ({len(clean_title)} chars).",
                    measured_value=clean_title,
                )
            )

        # 2. Check for placeholder strings in title
        title_lower = clean_title.lower()
        for placeholder in PLACEHOLDER_SUBSTRINGS:
            if placeholder in title_lower:
                results.append(
                    QualityCheckResult(
                        check_name="metadata_title_no_placeholder",
                        status=QualityStatus.FAIL,
                        severity=CheckSeverity.CRITICAL,
                        message=f"Title contains unreplaced placeholder text: '{placeholder}'.",
                        measured_value=clean_title,
                        suggested_correction="Replace placeholder with approved production title.",
                    )
                )
                break
        else:
            results.append(
                QualityCheckResult(
                    check_name="metadata_title_no_placeholder",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message="No placeholder patterns found in title.",
                )
            )

        # 3. Description validation
        clean_desc = (description or "").strip()
        if len(clean_desc) > self.thresholds.max_description_length:
            results.append(
                QualityCheckResult(
                    check_name="metadata_description_length",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Description length ({len(clean_desc)} chars) exceeds YouTube limit ({self.thresholds.max_description_length} chars).",
                    measured_value=len(clean_desc),
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="metadata_description_valid",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Description is valid ({len(clean_desc)} chars).",
                )
            )

        # Check placeholder in description
        desc_lower = clean_desc.lower()
        for placeholder in PLACEHOLDER_SUBSTRINGS:
            if placeholder in desc_lower:
                results.append(
                    QualityCheckResult(
                        check_name="metadata_description_no_placeholder",
                        status=QualityStatus.WARNING,
                        severity=CheckSeverity.WARNING,
                        message=f"Description contains potential placeholder text: '{placeholder}'.",
                        suggested_correction="Review description text before upload.",
                    )
                )
                break

        # 4. Tags validation
        total_tags_len = sum(len(t) for t in tags)
        if total_tags_len > self.thresholds.max_total_tags_length:
            results.append(
                QualityCheckResult(
                    check_name="metadata_tags_total_length",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Total tags string length ({total_tags_len} chars) exceeds YouTube ceiling ({self.thresholds.max_total_tags_length} chars).",
                    measured_value=total_tags_len,
                    suggested_correction="Reduce number of tags.",
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="metadata_tags_total_length",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Tags total length ({total_tags_len} chars across {len(tags)} tags) is within limits.",
                    measured_value=total_tags_len,
                )
            )

        # 5. Category ID validation
        if category_id in VALID_YOUTUBE_CATEGORIES:
            results.append(
                QualityCheckResult(
                    check_name="metadata_category_id",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Category ID '{category_id}' ({VALID_YOUTUBE_CATEGORIES[category_id]}) is valid.",
                    measured_value=category_id,
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="metadata_category_id",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Invalid YouTube Category ID '{category_id}'.",
                    measured_value=category_id,
                    expected_value="Valid category id (e.g. 27 for Education, 28 for Science & Tech)",
                )
            )

        # 6. Privacy status validation
        clean_privacy = privacy_status.lower().strip()
        if clean_privacy in ["private", "unlisted", "public"]:
            results.append(
                QualityCheckResult(
                    check_name="metadata_privacy_status",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Privacy status is '{clean_privacy}'.",
                    measured_value=clean_privacy,
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="metadata_privacy_status",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Invalid privacy status '{privacy_status}'. Must be private, unlisted, or public.",
                    measured_value=privacy_status,
                )
            )

        # 7. Made-for-kids setting (Mandatory explicit review)
        if made_for_kids is None:
            results.append(
                QualityCheckResult(
                    check_name="metadata_made_for_kids_specified",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message="selfDeclaredMadeForKids setting was not explicitly reviewed or configured (is None).",
                    suggested_correction="Explicitly configure whether content is made for kids (typically False for A Lesson With AI).",
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="metadata_made_for_kids_specified",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"selfDeclaredMadeForKids is explicitly configured as {made_for_kids}.",
                    measured_value=made_for_kids,
                )
            )

        return results
