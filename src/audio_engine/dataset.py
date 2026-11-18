"""Voice Evaluation and Learning Dataset Architecture.

Tracks quality metrics across both objective model measurements and human listening judgments:
- Naturalness and human-like delivery
- Native Hindi pronunciation
- Word clarity
- Sentence continuity
- Pauses and rhythm
- Emotional expression
- Pitch variation and warmth
- Consistency between generations
- Script fidelity
- Human reviewer feedback
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HumanEvaluationScoreSheet(BaseModel):
    """Detailed human-listening evaluation scorecard across all 8 qualitative dimensions."""

    decision: str = Field(default="PENDING", description="PENDING, APPROVED, REJECTED, or NEEDS_REVISION")
    reviewer: Optional[str] = Field(default=None, description="Name or identifier of human reviewer")
    evaluated_at: Optional[str] = Field(default=None, description="ISO timestamp of evaluation")
    naturalness: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Conversational naturalness (1-10)")
    hindi_pronunciation: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Authentic Indian Hindi pronunciation (1-10)")
    word_clarity: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Diction and phoneme clarity (1-10)")
    sentence_continuity: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Smooth sentence flow without mechanical cuts (1-10)")
    pauses_and_rhythm: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Natural breathing pauses and cadence (1-10)")
    emotional_expression: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Appropriate drama, curiosity, excitement (1-10)")
    pitch_warmth: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Vocal warmth and organic pitch inflection (1-10)")
    voice_consistency: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Identity consistency across sentences (1-10)")
    composite_score: Optional[float] = Field(default=None, ge=1.0, le=10.0, description="Weighted composite human score")
    notes: Optional[str] = Field(default=None, description="Qualitative feedback and reviewer notes")


class ModelObjectiveMetrics(BaseModel):
    """Acoustic and technical signal measurements derived objectively from audio files."""

    duration_seconds: float
    sample_rate_hz: int
    channels: int
    bitrate_kbps: float
    peak_dbfs: float
    mean_dbfs: float
    speech_rate_wpm: float
    clipped_samples: int = 0
    clipping_ratio: float = 0.0
    script_fidelity_score: float = Field(default=10.0, ge=0.0, le=10.0, description="Objective word presence vs script")
    signal_clarity_score: float = Field(default=10.0, ge=0.0, le=10.0, description="Signal-to-noise and headroom rating")


class VoiceEvaluationSample(BaseModel):
    """Complete dataset record combining sample metadata, acoustic measurements, and human review."""

    sample_id: str
    file_name: str
    file_path: str
    sha256_hash: str
    provider: str
    model: str
    speaker: str
    language: str = "hi-IN"
    category: str
    script_text: str
    word_count: int
    generation_date: str
    metrics: ModelObjectiveMetrics
    human_evaluation: HumanEvaluationScoreSheet = Field(default_factory=HumanEvaluationScoreSheet)


class VoiceEvaluationDataset(BaseModel):
    """Structured catalog managing the voice evaluation and learning dataset."""

    dataset_id: str = "hindi_voice_evaluation_v1"
    version: str = "1.0.0"
    description: str = "Structured dataset tracking Hindi speech naturalness, pronunciation, and human feedback"
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_samples: int = 0
    samples: Dict[str, VoiceEvaluationSample] = Field(default_factory=dict)

    def add_sample(self, sample: VoiceEvaluationSample) -> None:
        """Add or update an evaluation sample."""
        self.samples[sample.sample_id] = sample
        self.total_samples = len(self.samples)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def record_human_evaluation(
        self,
        sample_id: str,
        decision: str,
        reviewer: str,
        scores: Optional[Dict[str, float]] = None,
        notes: Optional[str] = None,
    ) -> VoiceEvaluationSample:
        """Record explicit human reviewer score and feedback for a sample."""
        if sample_id not in self.samples:
            raise KeyError(f"Sample ID '{sample_id}' not found in voice evaluation dataset.")

        scores = scores or {}
        sample = self.samples[sample_id]
        sheet = sample.human_evaluation

        sheet.decision = decision.upper()
        sheet.reviewer = reviewer
        sheet.evaluated_at = datetime.now(timezone.utc).isoformat()
        sheet.notes = notes

        # Set individual dimension scores if provided
        for dim in [
            "naturalness",
            "hindi_pronunciation",
            "word_clarity",
            "sentence_continuity",
            "pauses_and_rhythm",
            "emotional_expression",
            "pitch_warmth",
            "voice_consistency",
        ]:
            if dim in scores:
                setattr(sheet, dim, scores[dim])

        # Compute average composite score
        valid_scores = [
            getattr(sheet, d)
            for d in [
                "naturalness",
                "hindi_pronunciation",
                "word_clarity",
                "sentence_continuity",
                "pauses_and_rhythm",
                "emotional_expression",
                "pitch_warmth",
                "voice_consistency",
            ]
            if getattr(sheet, d) is not None
        ]
        if valid_scores:
            sheet.composite_score = round(sum(valid_scores) / len(valid_scores), 2)

        self.updated_at = datetime.now(timezone.utc).isoformat()
        return sample

    def filter_samples(
        self,
        provider: Optional[str] = None,
        speaker: Optional[str] = None,
        decision: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[VoiceEvaluationSample]:
        """Filter dataset samples by provider, speaker, decision, or category."""
        results = list(self.samples.values())
        if provider:
            results = [s for s in results if s.provider.lower() == provider.lower()]
        if speaker:
            results = [s for s in results if s.speaker.lower() == speaker.lower()]
        if decision:
            results = [s for s in results if s.human_evaluation.decision.upper() == decision.upper()]
        if category:
            results = [s for s in results if s.category.lower() == category.lower()]
        return results

    def save_to_file(self, path: Path) -> None:
        """Serialize dataset to JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.total_samples = len(self.samples)
        self.updated_at = datetime.now(timezone.utc).isoformat()
        p.write_text(self.model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load_from_file(cls, path: Path) -> "VoiceEvaluationDataset":
        """Load dataset from JSON file."""
        p = Path(path)
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(**data)
