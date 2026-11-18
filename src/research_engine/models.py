"""Data models and schemas for the Gemini Research Engine."""

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class SourceType(str, Enum):
    """Categorization of supporting evidence sources."""

    ACADEMIC_PAPER = "academic_paper"
    BOOK = "book"
    JOURNAL_ARTICLE = "journal_article"
    EDUCATIONAL_WEBSITE = "educational_website"
    NEWS_REPORT = "news_report"
    GENERAL_CONSENSUS = "general_consensus"
    UNVERIFIED_PROPOSAL = "unverified_proposal"


class VerificationStatus(str, Enum):
    """Verification lifecycle of a research claim or citation."""

    UNVERIFIED = "unverified"  # Default for all AI-generated citations
    AI_PROPOSED = "ai_proposed"  # Sourced by AI, pending independent check
    HUMAN_CHECKED = "human_checked"  # Explicitly confirmed by human reviewer
    FACT_CHECKED = "fact_checked"  # Cross-verified against external primary source


class ResearchCitation(BaseModel):
    """Structured citation representation with strict verification guardrails."""

    claim: str = Field(..., min_length=1, description="The specific factual or scientific assertion")
    source_title: str = Field(..., min_length=1, description="Title of the paper, book, article, or source")
    source_type: SourceType = Field(default=SourceType.UNVERIFIED_PROPOSAL)
    url: Optional[str] = Field(default=None, description="Direct URL if verifiable; None if general knowledge")
    publication_details: Optional[str] = Field(
        default=None, description="Journal name, publication year, or authors if known"
    )
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        description="Verification state. AI-generated citations must start as unverified.",
    )
    is_verified: bool = Field(
        default=False,
        description="Strict boolean flag. Must remain False until independent verification occurs.",
    )
    verification_notes: Optional[str] = Field(
        default="AI-generated citation. Requires independent verification against primary source."
    )

    @model_validator(mode="after")
    def enforce_unverified_guardrail(self) -> "ResearchCitation":
        """Enforce that newly generated citations are NEVER automatically marked verified."""
        if self.verification_status in [VerificationStatus.UNVERIFIED, VerificationStatus.AI_PROPOSED]:
            self.is_verified = False
        return self

    def mark_verified_by_human(self, reviewer_notes: Optional[str] = None) -> None:
        """Mark citation as independently verified by a human reviewer."""
        self.verification_status = VerificationStatus.HUMAN_CHECKED
        self.is_verified = True
        if reviewer_notes:
            self.verification_notes = reviewer_notes


class AnimeScienceDossier(BaseModel):
    """Research dossier connecting an anime concept to real-world science."""

    dossier_id: str = Field(..., description="Unique dossier identifier")
    topic: str = Field(..., description="Core topic headline")
    anime_title: str = Field(..., description="Anime series name (e.g. Dr. Stone, Blue Lock)")
    character_or_scene: str = Field(..., description="Character, scene, or power system referenced")
    anime_canon_premise: str = Field(
        ...,
        description="The fictional mechanism or situation as presented in the anime story (clearly fiction)",
    )
    scientific_domain: str = Field(
        ..., description="Real-world academic domain (e.g. Neuroscience, Physics, Mathematics)"
    )
    real_world_scientific_explanation: str = Field(
        ..., description="Empirical, verified explanation of how the concept functions in reality"
    )
    demarcation_warning: str = Field(
        default="CRITICAL: The anime mechanics described are fictional canon and must never be conflated with empirical physical reality.",
        description="Explicit notice separating fictional canon from empirical science.",
    )
    citations: List[ResearchCitation] = Field(default_factory=list)
    suggested_creative_angles: List[str] = Field(
        default_factory=list,
        description="Hook ideas and storytelling angles to inspire the human creator's script",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_model_response: Optional[str] = None

    @model_validator(mode="after")
    def enforce_citation_unverified(self) -> "AnimeScienceDossier":
        """Ensure all citations within a fresh dossier start unverified."""
        for c in self.citations:
            if c.verification_status == VerificationStatus.UNVERIFIED:
                c.is_verified = False
        return self


class MotivationalThemeDossier(BaseModel):
    """Research dossier exploring psychological or natural concepts for storytelling."""

    dossier_id: str = Field(..., description="Unique dossier identifier")
    theme: str = Field(..., description="Core philosophical or emotional theme (e.g. Patience, Discipline)")
    psychological_or_natural_concept: str = Field(
        ..., description="Real-world mechanism, biological phenomenon, or cognitive pattern"
    )
    real_world_evidence: str = Field(
        ..., description="Empirical evidence or observable facts supporting the concept"
    )
    visual_metaphor_ideas: List[str] = Field(
        default_factory=list,
        description="Suggestions for vertical 9:16 visual metaphors (e.g. root networks, stone polishing)",
    )
    citations: List[ResearchCitation] = Field(default_factory=list)
    suggested_creative_angles: List[str] = Field(
        default_factory=list,
        description="Narrative entry points and emotional questions for creator guidance",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_model_response: Optional[str] = None

    @model_validator(mode="after")
    def enforce_citation_unverified(self) -> "MotivationalThemeDossier":
        """Ensure all citations within a fresh dossier start unverified."""
        for c in self.citations:
            if c.verification_status == VerificationStatus.UNVERIFIED:
                c.is_verified = False
        return self
