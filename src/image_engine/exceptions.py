"""Exceptions for Image Generation Engine and Cost-Safety Guard."""


class ImageEngineError(Exception):
    """Base exception for all Image Generation Engine errors."""

    pass


class CostSafetyViolationError(ImageEngineError):
    """Raised when an operation attempts to invoke a paid provider or violates ₹0 budget."""

    pass


class ProductionEligibilityBlockedError(ImageEngineError):
    """Raised when an unapproved script or unverified scientific claims block image generation."""

    pass


class MockAssetProductionBlockedError(ImageEngineError):
    """Raised when a mock testing asset is submitted to production video assembly."""

    pass


class DisabledProviderError(ImageEngineError):
    """Raised when an unactivated or disabled provider stub is requested."""

    pass


class ImageReviewRequiredError(ImageEngineError):
    """Raised when images have not received mandatory human approval."""

    pass


class ImageProviderError(ImageEngineError):
    """Raised when an image provider fails during generation."""

    pass
