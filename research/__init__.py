"""Research & Fact-Checking domain facade for YouTube-for-All."""
from src.research_engine.service import ResearchEngine
from src.research_engine.client import GeminiResearchClient

__all__ = [
    "ResearchEngine",
    "GeminiResearchClient",
]
