"""Pacing and timing calculation engine for YouTube Shorts scripts."""

from dataclasses import dataclass
from typing import List, Optional, Protocol, Tuple

from src.storyboard_generator.exceptions import PacingExceededError


@dataclass
class PacingBudget:
    """Calculated speech and timing targets for a Shorts script."""

    target_duration_seconds: float
    words_per_second: float
    pause_budget_seconds: float
    effective_speaking_seconds: float
    target_word_count: int
    min_word_count: int
    max_word_count: int


def calculate_pacing_budget(
    target_duration_seconds: float = 45.0,
    words_per_second: float = 2.2,
    pause_budget_seconds: float = 2.0,
) -> PacingBudget:
    """Compute flexible word-count targets based on duration, speech rate, and dramatic pauses."""
    target_duration = max(min(target_duration_seconds, 60.0), 15.0)
    pause_budget = max(pause_budget_seconds, 0.5)

    effective_speaking = max(target_duration - pause_budget, 10.0)
    target_words = round(effective_speaking * words_per_second)

    # Allow a +/- 12% window around target words to accommodate natural sentence structure
    margin = max(round(target_words * 0.12), 6)
    min_words = max(target_words - margin, 15)
    max_words = target_words + margin

    return PacingBudget(
        target_duration_seconds=target_duration,
        words_per_second=words_per_second,
        pause_budget_seconds=pause_budget,
        effective_speaking_seconds=round(effective_speaking, 2),
        target_word_count=target_words,
        min_word_count=min_words,
        max_word_count=max_words,
    )


def estimate_duration_from_narration(
    narration_text: str,
    words_per_second: float = 2.12,
    pause_budget_seconds: float = 2.0,
) -> tuple[float, int]:
    """Calculate estimated speech duration and total duration from complete narration text."""
    words = narration_text.strip().split()
    word_count = len(words)
    if word_count == 0:
        return 0.0, 0
    speech_duration = word_count / max(words_per_second, 0.5)
    total_duration = round(speech_duration + pause_budget_seconds, 2)
    return total_duration, word_count


def check_narration_duration_limits(
    narration_text: str,
    words_per_second: float = 2.12,
    pause_budget_seconds: float = 2.0,
    max_duration_seconds: float = 60.0,
) -> tuple[bool, float, Optional[str]]:
    """Verify that narration duration is within limits without silently condensing text.

    Returns:
        (is_within_limits, estimated_duration, warning_message_or_None)
    """
    total_duration, word_count = estimate_duration_from_narration(
        narration_text=narration_text,
        words_per_second=words_per_second,
        pause_budget_seconds=pause_budget_seconds,
    )
    if total_duration > max_duration_seconds:
        msg = (
            f"Narration Pacing Warning: Complete approved narration contains {word_count} words "
            f"estimating {total_duration:.1f}s (at {words_per_second:.2f} WPS + {pause_budget_seconds:.1f}s pauses), "
            f"exceeding the {max_duration_seconds:.1f}s YouTube Shorts ceiling. "
            "Pacing Engine will NOT silently condense approved narration. "
            "A separate shortened draft must be submitted to ScriptManager in PENDING_REVIEW status "
            "and explicitly approved by a human creator before entering production."
        )
        return False, total_duration, msg
    return True, total_duration, None



class HasDuration(Protocol):
    suggested_duration_seconds: float


def validate_combined_duration(
    scenes: List[HasDuration],
    pause_budget_seconds: float,
    target_duration_seconds: float,
    tolerance_seconds: float = 3.5,
) -> float:
    """Validate that combined scene durations and dramatic pauses fit within the target video duration.

    Enforces:
    1. Hard Shorts ceiling: Total combined duration must never exceed 60.0 seconds.
    2. Target proximity: Combined duration must not deviate from target by more than tolerance.
    """
    if not scenes:
        raise PacingExceededError("Storyboard must contain at least one scene.")

    scenes_total = sum(s.suggested_duration_seconds for s in scenes)
    combined_total = round(scenes_total + pause_budget_seconds, 2)

    # Hard YouTube Shorts duration ceiling
    if combined_total > 60.0:
        raise PacingExceededError(
            f"Combined duration ({combined_total:.1f}s = {scenes_total:.1f}s scenes + {pause_budget_seconds:.1f}s pauses) "
            f"exceeds the 60.0s YouTube Shorts hard ceiling."
        )

    # Minimum Shorts duration threshold
    if combined_total < 20.0:
        raise PacingExceededError(
            f"Combined duration ({combined_total:.1f}s) is too short for a complete Shorts story (minimum 20.0s)."
        )

    # Proximity check against target
    deviation = abs(combined_total - target_duration_seconds)
    if deviation > tolerance_seconds:
        raise PacingExceededError(
            f"Combined duration ({combined_total:.1f}s) deviates by {deviation:.1f}s from target "
            f"({target_duration_seconds:.1f}s). Allowed tolerance is +/- {tolerance_seconds:.1f}s."
        )

    return combined_total
