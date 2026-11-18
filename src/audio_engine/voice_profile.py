"""Reusable Voice Profile Architecture for Adaptive Native Hindi Voice Synthesis.

Stores complete configuration for voice synthesis providers:
- Provider, model, speaker/cloned voice_id
- Language code and pace modulations
- Approved pronunciation dictionary
- Hindi text normalization rules (numerals, units, punctuation)
- Natural sentence chunking (clause limits, pause timing)
- Prosody preferences and delivery styles
- Human evaluation history and approval status
"""

import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SentenceChunkingConfig(BaseModel):
    """Rules for natural breath pauses and clause chunking to prevent TTS rushing."""

    max_words_per_chunk: int = Field(default=16, description="Maximum words before forcing a pause")
    max_chars_per_chunk: int = Field(default=120, description="Maximum characters per speech chunk")
    clause_delimiters: List[str] = Field(
        default=["।", "?", "!", ",", "—", "जबकि", "लेकिन", "क्योंकि", "अर्थात", "यानी"],
        description="Punctuation and conjunction markers indicating natural pauses"
    )
    comma_pause_ms: int = Field(default=180, description="Silence duration at commas (ms)")
    sentence_pause_ms: int = Field(default=380, description="Silence duration at full stops / danda (ms)")
    scene_transition_pause_ms: int = Field(default=450, description="Silence duration between scenes (ms)")


class NormalizationRulesConfig(BaseModel):
    """Rules for expanding numerals, units, and punctuation to pure Devanagari."""

    expand_numerals: bool = Field(default=True, description="Expand numbers like 60 -> साठ")
    expand_units: bool = Field(default=True, description="Expand units like m -> मीटर, kg -> किलोग्राम")
    normalize_danda: bool = Field(default=True, description="Convert western period '.' to Devanagari danda '।'")
    preserve_expressive_punctuation: bool = Field(default=True, description="Retain '?' and '!' for prosody")
    compound_word_hyphenation: bool = Field(default=True, description="Preserve hyphens in compound words (चलते-फिरते)")


class VoiceProfileConfig(BaseModel):
    """Complete reusable voice profile schema."""

    profile_id: str = "sarvam_bulbul_shubh_v1"
    profile_name: str = "Sarvam Bulbul v4 Flash (Shubh Native Indian Voice)"
    version: str = "1.0.0"
    provider: str = "sarvam_ai"
    model: str = "bulbul:v4-flash"
    speaker: str = "shubh_enhi_ads"
    cloned_voice_id: Optional[str] = None
    language_code: str = "hi-IN"
    base_pace: float = Field(default=1.0, ge=0.5, le=2.0)
    scene_pace_modifiers: Dict[str, float] = Field(
        default_factory=lambda: {
            "hook": 1.02,
            "exposition": 1.00,
            "science": 0.98,
            "climax": 0.96,
            "takeaway": 1.00,
        }
    )
    pronunciation_dictionary: Dict[str, str] = Field(default_factory=dict)
    normalization_rules: NormalizationRulesConfig = Field(default_factory=NormalizationRulesConfig)
    sentence_chunking: SentenceChunkingConfig = Field(default_factory=SentenceChunkingConfig)
    prosody_preferences: Dict[str, Any] = Field(
        default_factory=lambda: {
            "warmth_bias": "high",
            "cadence_style": "conversational_storyteller",
            "micro_pause_insertion": True,
            "target_wpm_range": (140, 165),
        }
    )
    human_evaluation_history: List[Dict[str, Any]] = Field(default_factory=list)
    approval_status: str = "VOICE_PREVIEW_PENDING_HUMAN_LISTENING"


class VoiceProfile:
    """Operational voice profile manager providing text normalization and clause chunking."""

    def __init__(self, config: VoiceProfileConfig):
        self.config = config

    @classmethod
    def load(cls, path: Path) -> "VoiceProfile":
        """Load voice profile from JSON file."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Voice profile file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        cfg = VoiceProfileConfig(**data)
        return cls(cfg)

    def save(self, path: Path) -> None:
        """Save voice profile to JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.config.model_dump_json(indent=2), encoding="utf-8")

    def normalize_text(self, text: str) -> str:
        """Normalize raw Hindi script text according to profile rules."""
        out = text.strip()

        # 1. Apply Pronunciation Dictionary Substitutions
        for term, phonetic in self.config.pronunciation_dictionary.items():
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            out = pattern.sub(phonetic, out)

        # 2. Unit expansion (handles attached units like 60m, 50m, 40000kg)
        if self.config.normalization_rules.expand_units:
            unit_map = {
                r"(\d+)\s*(?:मीटर|m|mtr)\b": r"\1 मीटर",
                r"(\d+)\s*(?:किमी|km)\b": r"\1 किलोमीटर",
                r"(\d+)\s*(?:किग्रा|kg)\b": r"\1 किलोग्राम",
                r"(\d+)\s*(?:टन|tonnes|tons)\b": r"\1 टन",
                r"(\d+)\s*x\b": r"\1 गुना",
            }
            for pat, rep in unit_map.items():
                out = re.sub(pat, rep, out, flags=re.IGNORECASE)

        # 3. Number expansion (common Hindi numerals in physics & anime)
        if self.config.normalization_rules.expand_numerals:
            num_map = {
                r"\b40000\b": "चालीस हज़ार",
                r"\b60000\b": "साठ हज़ार",
                r"\b27000\b": "सत्ताईस हज़ार",
                r"\b1638\b": "सोलह सौ अड़तीस",
                r"\b900\b": "नौ सौ",
                r"\b1000\b": "एक हज़ार",
                r"\b100\b": "सौ",
                r"\b60\b": "साठ",
                r"\b50\b": "पचास",
                r"\b30\b": "तीस",
                r"\b10\b": "दस",
                r"\b8\b": "आठ",
                r"\b4\b": "चार",
                r"\b2\b": "दो",
                r"\b1\b": "एक",
            }
            for pat, rep in num_map.items():
                out = re.sub(pat, rep, out)

        # 4. Punctuation normalization
        if self.config.normalization_rules.normalize_danda:
            # Replace western period preceded by Hindi word with danda
            out = re.sub(r"([^\d\s\.\?!])\.\s*", r"\1। ", out)

        # Collapse whitespace
        out = re.sub(r"\s+", " ", out).strip()
        return out

    def chunk_text(self, text: str) -> List[str]:
        """Split text into natural conversational chunks with syntactic pause markers."""
        norm = self.normalize_text(text)
        max_words = self.config.sentence_chunking.max_words_per_chunk

        # Split along strong clause boundary delimiters: ।, ?, !, —, comma
        raw_clauses = re.split(r"([।\?!—,])", norm)
        
        chunks = []
        current = ""

        i = 0
        while i < len(raw_clauses):
            seg = raw_clauses[i].strip()
            punct = raw_clauses[i + 1].strip() if i + 1 < len(raw_clauses) else ""
            i += 2 if punct else 1

            clause_unit = (seg + punct).strip()
            if not clause_unit:
                continue

            current_words = len(current.split()) if current else 0
            seg_words = len(clause_unit.split())

            if current_words + seg_words <= max_words:
                current = f"{current} {clause_unit}".strip()
            else:
                if current:
                    chunks.append(current)
                current = clause_unit

        if current:
            chunks.append(current)

        return chunks

    def get_scene_pace(self, scene_type: str) -> float:
        """Get recommended pace for scene category."""
        base = self.config.base_pace
        modifier = self.config.scene_pace_modifiers.get(scene_type.lower(), 1.0)
        return round(base * modifier, 3)
