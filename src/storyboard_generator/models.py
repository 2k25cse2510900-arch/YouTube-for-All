"""Data models and schemas for the AI Script & Storyboard Generator."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from src.research_engine.models import SourceType, VerificationStatus
from src.storyboard_generator.pacing import validate_combined_duration


class CameraMovement(str, Enum):
    """Subtle 2.5D camera movements for image-based storytelling."""

    SLOW_ZOOM_IN = "slow_zoom_in"  # Focuses intensity on character's eyes or formula
    SLOW_ZOOM_OUT = "slow_zoom_out"  # Reveals scale, environment, or perspective shock
    PAN_DOWN = "pan_down"  # Vertical mobile scroll motion (top to bottom)
    PAN_UP = "pan_up"  # Ground-up reveal
    STATIC_DRIFT = "static_drift"  # Subtle parallax/float for diagrams or technical views


class ScientificClaimVerification(BaseModel):
    """Tracks verification status at the individual scientific claim level."""

    claim: str = Field(..., min_length=1, description="Specific factual assertion")
    source_title: str = Field(..., min_length=1, description="Source publication or concept title")
    source_type: SourceType = Field(default=SourceType.UNVERIFIED_PROPOSAL)
    url: Optional[str] = Field(default=None)
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        description="Must start UNVERIFIED until an independent human check occurs.",
    )
    is_verified: bool = Field(
        default=False,
        description="Always False for newly generated claims. Hedging in script does NOT verify a claim.",
    )
    human_reviewer_notes: Optional[str] = Field(default=None)

    @model_validator(mode="after")
    def enforce_unverified_rule(self) -> "ScientificClaimVerification":
        """Ensure claims without explicit human sign-off cannot self-verify."""
        if self.verification_status in [VerificationStatus.UNVERIFIED, VerificationStatus.AI_PROPOSED]:
            self.is_verified = False
        return self

    def mark_human_verified(self, notes: str) -> None:
        """Explicitly record human verification of the primary source."""
        self.verification_status = VerificationStatus.HUMAN_CHECKED
        self.is_verified = True
        self.human_reviewer_notes = notes


class VisualConsistencyProfile(BaseModel):
    """Global character, style, and composition rules for image continuity."""

    character_name: str = Field(..., description="Character identity (e.g. Senku Ishigami, Original Protagonist)")
    character_reference_image: Optional[str] = Field(
        default=None,
        description="Path or URL to reference character image for tools supporting ControlNet, IP-Adapter or --cref",
    )
    facial_features: str = Field(..., description="Precise facial structure, eye color, expressions, distinctive marks")
    hairstyle: str = Field(..., description="Hair color, texture, silhouette, and style")
    clothing_and_attire: str = Field(..., description="Signature clothing, color patterns, and accessories")
    color_palette: str = Field(..., description="Dominant 3-4 hex or color names for cohesive aesthetic")
    art_direction: str = Field(
        default="Modern cinematic high-contrast anime key visual, dramatic volumetric lighting, 8k resolution, vertical 9:16",
        description="Overall rendering and art style prompt fragment",
    )
    negative_prompt: str = Field(
        default="distorted anatomy, extra limbs, deformed hands, missing fingers, low resolution, blurry, text, watermark, photorealistic face, 3d render",
        description="Universal negative prompt preventing common generation artifacts",
    )
    aspect_ratio: str = Field(default="9:16", description="Target aspect ratio for mobile Shorts")


class StoryboardScene(BaseModel):
    """A single sequential visual scene and corresponding voiceover line."""

    scene_number: int = Field(ge=1, description="Sequential index of the scene")
    narration_hinglish: str = Field(..., min_length=1, description="Conversational Hindi/Hinglish spoken line")
    narration_english_meaning: str = Field(..., min_length=1, description="English translation/meaning for review")

    # Cinematography & Composition
    camera_angle: str = Field(..., description="Camera angle (e.g. low-angle, eye-level, dutch-tilt)")
    framing: str = Field(..., description="Framing (e.g. extreme-close-up, medium-shot, wide-shot)")
    subject_placement: str = Field(..., description="Subject positioning (e.g. center-weighted for vertical 9:16)")

    # Modular, Provider-Independent Image Prompts
    image_prompt_positive: str = Field(..., min_length=1, description="Detailed English prompt for image generator")
    image_prompt_negative: str = Field(default="", description="Scene-specific negative prompt")

    suggested_duration_seconds: float = Field(gt=0, le=30.0, description="Screen duration in seconds")
    camera_movement: CameraMovement = Field(default=CameraMovement.SLOW_ZOOM_IN)
    sound_effect_cue: Optional[str] = Field(default=None, description="Audio SFX trigger (e.g. [SFX: Stone Crack])")


class StoryboardDossier(BaseModel):
    """Complete storyboard and production package for a 30-60s Short."""

    storyboard_id: str = Field(..., description="Unique storyboard identifier")
    title: str = Field(..., min_length=1, description="Shorts title")
    topic: str = Field(..., min_length=1, description="Core scientific/anime topic")
    target_duration_seconds: float = Field(default=45.0, ge=20.0, le=60.0)
    pause_budget_seconds: float = Field(default=2.0, ge=0.5, le=5.0)
    total_estimated_seconds: float = Field(default=0.0)
    total_spoken_words: int = Field(default=0)

    # Narrative Segments in Hindi/Hinglish
    hook: str = Field(..., min_length=1, description="Opening attention grabber (0-4s)")
    body: str = Field(..., min_length=1, description="Core narrative and scientific explanation")
    takeaway: str = Field(..., min_length=1, description="Closing takeaway / call to reflection")

    # Visual Direction & Scenes (Using default_factory=list for mutable lists)
    visual_consistency: VisualConsistencyProfile
    scenes: List[StoryboardScene] = Field(default_factory=list)

    # Audio Direction
    bgm_suggestion: Dict[str, str] = Field(
        default_factory=lambda: {
            "mood": "Tense and mysterious building into an uplifting scientific revelation",
            "tempo": "Medium-fast, 115-125 BPM",
            "instrumentation": "Sub-bass pulses, rhythmic ticking clock, rising electronic synth lead",
        }
    )

    # Scientific Verification Tracking (Individual Claim Level)
    scientific_claims: List[ScientificClaimVerification] = Field(default_factory=list)
    claims_pending_verification: List[str] = Field(default_factory=list)
    has_unverified_claims: bool = Field(default=True)

    # Provenance Tracking to Approved Source Script
    source_script_id: Optional[str] = Field(default=None, description="ID of the approved source script")
    source_script_checksum: Optional[str] = Field(default=None, description="Content hash of source script")
    source_script_version: Optional[str] = Field(default="1.0", description="Version of source script")
    source_narration_checksum: Optional[str] = Field(default=None, description="Checksum of source narration text")
    storyboard_narration_checksum: Optional[str] = Field(default=None, description="Checksum of storyboard scene narration")
    narration_fidelity_status: Optional[str] = Field(default=None, description="Status of fidelity validation (e.g. VERIFIED)")

    # Explicit Demarcation
    demarcation_warning: str = Field(
        default="CRITICAL: Anime mechanics are fictional canon. Real-world empirical science must be explicitly separated in presentation.",
        description="Non-negotiable warning",
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_and_compute_metrics(self) -> "StoryboardDossier":
        """Validate combined durations, compute word count, and track unverified claims."""
        # 1. Compute total spoken words and narration checksum
        full_narration = " ".join([s.narration_hinglish for s in self.scenes])
        self.total_spoken_words = len(full_narration.split())
        if full_narration and not self.storyboard_narration_checksum:
            import hashlib, re
            words = re.findall(r"[\w]+", full_narration.lower())
            self.storyboard_narration_checksum = hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()


        # 2. Validate combined scene durations + pause budget fit within target duration
        if self.scenes:
            combined_duration = validate_combined_duration(
                scenes=self.scenes,
                pause_budget_seconds=self.pause_budget_seconds,
                target_duration_seconds=self.target_duration_seconds,
                tolerance_seconds=3.5,
            )
            self.total_estimated_seconds = combined_duration

        # 3. Track unverified claims at the individual claim level
        pending = []
        for c in self.scientific_claims:
            if not c.is_verified:
                pending.append(c.claim)

        self.claims_pending_verification = pending
        self.has_unverified_claims = len(pending) > 0

        return self

    def verify_claim(self, claim_text: str, reviewer_notes: str) -> bool:
        """Mark a specific claim as verified by human reviewer."""
        for c in self.scientific_claims:
            if c.claim.strip().lower() == claim_text.strip().lower():
                c.mark_human_verified(reviewer_notes)
                # Re-evaluate pending
                self.claims_pending_verification = [claim.claim for claim in self.scientific_claims if not claim.is_verified]
                self.has_unverified_claims = len(self.claims_pending_verification) > 0
                return True
        return False

    def compute_narration_checksum(self) -> str:
        """Compute deterministic SHA-256 hash of all scene narrations combined."""
        import hashlib, re
        full_narration = " ".join([s.narration_hinglish for s in self.scenes])
        words = re.findall(r"[\w]+", full_narration.lower())
        return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()

