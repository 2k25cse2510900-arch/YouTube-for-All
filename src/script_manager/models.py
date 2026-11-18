"""Data models and schemas for Script Manager."""

from datetime import datetime, timezone
from enum import Enum
import hashlib
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class ContentCategory(str, Enum):
    """Supported content categories for A Lesson With AI."""

    ANIME_SCIENCE = "anime_science"
    MOTIVATIONAL_STORY = "motivational_story"


class ScriptLanguage(str, Enum):
    """Supported narration and script languages."""

    HINDI = "hindi"
    HINGLISH = "hinglish"
    ENGLISH = "english"


def detect_script_language(text: str) -> ScriptLanguage:
    """Intelligently detect whether text is Hindi, Hinglish, or English."""
    if not text or not text.strip():
        return ScriptLanguage.HINGLISH

    devanagari_chars = len(re.findall(r"[\u0900-\u097F]", text))
    total_alpha = len(re.findall(r"[a-zA-Z\u0900-\u097F]", text))

    if total_alpha > 0 and (devanagari_chars / total_alpha) > 0.25:
        return ScriptLanguage.HINDI

    hinglish_markers = {
        "kya", "hai", "hain", "hota", "hoti", "hote", "kyun", "lekin",
        "kaise", "zindagi", "toh", "agar", "apne", "yeh", "woh", "bhi",
        "nahi", "karte", "raha", "rahi", "samajh", "dekhein", "baat"
    }
    words = [w.lower() for w in re.findall(r"[a-zA-Z]+", text)]
    hinglish_matches = sum(1 for w in words if w in hinglish_markers)

    if len(words) > 0 and (hinglish_matches / len(words)) >= 0.06:
        return ScriptLanguage.HINGLISH

    return ScriptLanguage.ENGLISH


class ScriptStatus(str, Enum):
    """Lifecycle states of a script."""

    PENDING_REVIEW = "pending_review"  # Ingested, awaiting human review
    APPROVED = "approved"  # Human-approved, ready for daily production queue
    REJECTED = "rejected"  # Rejected by human review
    IN_PRODUCTION = "in_production"  # Currently actively being rendered/edited
    USED = "used"  # Video published/completed; cannot be reused
    ARCHIVED = "archived"  # Deprecated or retired


class SceneBreakdown(BaseModel):
    """Visual and narration cues for a single scene in a Short."""

    scene_number: int = Field(ge=1, description="Sequential scene index starting at 1")
    visual_prompt: str = Field(..., min_length=1, description="Visual description for image/video generation")
    narration: str = Field(..., min_length=1, description="Voiceover spoken line for this scene")
    estimated_seconds: float = Field(default=0.0, ge=0.0, description="Estimated duration in seconds")


class ResearchReference(BaseModel):
    """Fact-checking and research citations (supports future Gemini integration)."""

    claim: str = Field(..., min_length=1, description="The factual or scientific assertion")
    source: Optional[str] = Field(default=None, description="Citation URL or academic reference")
    source_url: Optional[str] = Field(default=None, description="Direct citation URL")
    source_title: Optional[str] = Field(default=None, description="Academic source title")
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    is_verified: bool = Field(default=False, description="Whether claim has been verified")
    notes: Optional[str] = Field(default=None, description="Verification or context notes")

    @model_validator(mode="after")
    def sync_source_fields(self) -> "ResearchReference":
        """Ensure source, source_url, and source_title remain synced."""
        if self.source and not self.source_url:
            self.source_url = self.source
        if not self.source and self.source_url:
            self.source = self.source_url
        if not self.source_title:
            self.source_title = self.claim
        return self


class Script(BaseModel):
    """Master representation of a YouTube Shorts script."""

    id: str = Field(..., min_length=1, description="Unique script identifier")
    title: str = Field(..., min_length=1, description="Title or topic headline")
    category: ContentCategory = Field(..., description="Content category (anime_science or motivational_story)")
    hook: str = Field(..., min_length=1, description="Attention-grabbing opening hook (0-3s)")
    body: str = Field(..., min_length=1, description="Core educational explanation or motivational narrative")
    takeaway: str = Field(..., min_length=1, description="Concluding takeaway, moral, or call-to-reflection")

    scenes: List[SceneBreakdown] = Field(default_factory=list)
    research_references: List[ResearchReference] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    target_duration_seconds: float = Field(default=45.0, gt=0, le=60.0)
    estimated_duration_seconds: float = Field(default=0.0, ge=0.0)

    status: ScriptStatus = Field(default=ScriptStatus.PENDING_REVIEW)
    language: ScriptLanguage = Field(default=ScriptLanguage.HINGLISH, description="Target narration language: hindi, hinglish, english")
    source_file: Optional[str] = Field(default=None)
    content_hash: str = Field(default="")

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    used_at: Optional[datetime] = None

    rejection_reason: Optional[str] = None
    approval_notes: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def validate_id_format(cls, v: str) -> str:
        clean = v.strip().lower()
        if not re.match(r"^[a-z0-9_-]+$", clean):
            raise ValueError(f"Script ID must contain only alphanumeric characters, underscores, and dashes: '{v}'")
        return clean

    @model_validator(mode="after")
    def compute_hash_and_duration(self) -> "Script":
        """Compute content hash and estimate speech duration based on word count."""
        # Estimate spoken duration (~2.5 words per second / 150 words per minute)
        full_text = f"{self.hook} {self.body} {self.takeaway}"
        words = full_text.split()
        word_count = len(words)
        if self.estimated_duration_seconds == 0.0 and word_count > 0:
            self.estimated_duration_seconds = round(word_count / 2.5, 2)

        # Auto-detect language if default
        if self.language == ScriptLanguage.HINGLISH and word_count > 0:
            self.language = detect_script_language(full_text)

        # Compute deterministic content hash for duplicate detection
        if not self.content_hash:
            normalized_content = re.sub(r"\s+", " ", full_text.strip().lower())
            self.content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()

        return self

    @property
    def script_id(self) -> str:
        """Alias for id for pipeline consistency."""
        return self.id

    @property
    def full_script_text(self) -> str:
        """Return the combined spoken text of the Short."""
        return f"{self.hook.strip()}\n\n{self.body.strip()}\n\n{self.takeaway.strip()}"

    @property
    def total_words(self) -> int:
        """Total word count across hook, body, and takeaway."""
        return len(self.full_script_text.split())

    def mark_approved(self, notes: Optional[str] = None) -> None:
        """Transition script to APPROVED status."""
        self.status = ScriptStatus.APPROVED
        self.approved_at = datetime.now(timezone.utc)
        self.approval_notes = notes
        self.updated_at = datetime.now(timezone.utc)

    def mark_rejected(self, reason: Optional[str] = None) -> None:
        """Transition script to REJECTED status."""
        self.status = ScriptStatus.REJECTED
        self.rejection_reason = reason
        self.updated_at = datetime.now(timezone.utc)

    def mark_used(self) -> None:
        """Transition script to USED status to prevent reuse."""
        self.status = ScriptStatus.USED
        self.used_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
