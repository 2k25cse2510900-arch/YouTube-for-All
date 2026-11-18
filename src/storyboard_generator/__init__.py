"""AI Script & Storyboard Generator package for A Lesson With AI.

Transforms verified research dossiers into cinematic 30-60s Hindi/Hinglish
Shorts storyboards with image prompts, visual consistency profiles, and pacing safeguards.
"""

from src.storyboard_generator.exceptions import (
    PacingExceededError,
    StoryboardGenerationError,
    StoryboardGeneratorError,
    StoryboardValidationError,
)
from src.storyboard_generator.models import (
    CameraMovement,
    ScientificClaimVerification,
    StoryboardDossier,
    StoryboardScene,
    VisualConsistencyProfile,
)
from src.storyboard_generator.pacing import (
    PacingBudget,
    calculate_pacing_budget,
    validate_combined_duration,
)
from src.storyboard_generator.service import StoryboardGenerator

__all__ = [
    "StoryboardGenerator",
    "StoryboardDossier",
    "StoryboardScene",
    "VisualConsistencyProfile",
    "CameraMovement",
    "ScientificClaimVerification",
    "PacingBudget",
    "calculate_pacing_budget",
    "validate_combined_duration",
    "StoryboardGeneratorError",
    "StoryboardValidationError",
    "PacingExceededError",
    "StoryboardGenerationError",
]
