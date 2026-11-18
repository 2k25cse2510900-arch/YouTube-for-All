"""Custom exceptions for the Gemini Research Engine."""


class ResearchEngineError(Exception):
    """Base exception for all Research Engine errors."""


class GeminiAPIKeyMissingError(ResearchEngineError):
    """Raised when GEMINI_API_KEY is not configured."""


class GeminiTransientError(ResearchEngineError):
    """Raised for transient issues (503 high demand, 429 rate limit, timeouts) suitable for retry."""


class GeminiPermanentError(ResearchEngineError):
    """Raised for permanent errors (401 auth failure, 400 invalid argument) that must not be retried."""


class ResearchParsingError(ResearchEngineError):
    """Raised when Gemini response cannot be parsed into the required structured dossier schema."""


class ResearchDemarcationError(ResearchEngineError):
    """Raised when anime fiction cannot be clearly demarcated from scientific evidence."""
