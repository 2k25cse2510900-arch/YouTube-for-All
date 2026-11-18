"""Gemini Research Engine package for A Lesson With AI.

Conducts factual research for Anime + Real-World Science and Motivational
Storytelling themes while enforcing strict citation verification integrity
and fiction-versus-fact demarcation.
"""

from src.research_engine.client import GeminiResearchClient
from src.research_engine.exceptions import (
    GeminiAPIKeyMissingError,
    GeminiPermanentError,
    GeminiTransientError,
    ResearchDemarcationError,
    ResearchEngineError,
    ResearchParsingError,
)
from src.research_engine.models import (
    AnimeScienceDossier,
    MotivationalThemeDossier,
    ResearchCitation,
    SourceType,
    VerificationStatus,
)
from src.research_engine.service import ResearchEngine

__all__ = [
    "ResearchEngine",
    "GeminiResearchClient",
    "AnimeScienceDossier",
    "MotivationalThemeDossier",
    "ResearchCitation",
    "SourceType",
    "VerificationStatus",
    "ResearchEngineError",
    "GeminiAPIKeyMissingError",
    "GeminiTransientError",
    "GeminiPermanentError",
    "ResearchParsingError",
    "ResearchDemarcationError",
]
