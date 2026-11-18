"""Custom exceptions for the AI Script & Storyboard Generator."""


class StoryboardGeneratorError(Exception):
    """Base exception for all Storyboard Generator errors."""


class StoryboardValidationError(StoryboardGeneratorError):
    """Raised when storyboard schema or scene parameters fail validation."""


class PacingExceededError(StoryboardGeneratorError):
    """Raised when combined scene durations and pause budget exceed duration constraints."""


class StoryboardGenerationError(StoryboardGeneratorError):
    """Raised when the AI model fails to produce a valid storyboard."""


class ScriptFidelityError(StoryboardGeneratorError):
    """Raised when storyboard narration deviates from the approved source script."""

