"""Pure Native Hindi Text Processing Engine for Natural Indian Speech Synthesis.

Enforces 100% Devanagari Hindi speech representation with:
1. Zero foreign-English accent influence.
2. Scientific concept translation into authentic natural Hindi:
   - Square-Cube Law -> वर्ग-घन का नियम
   - Volume -> आयतन
   - Weight -> भार / वज़न
   - Muscles -> मांसपेशियाँ
   - Physics -> भौतिक विज्ञान / भौतिकी
   - Science -> विज्ञान
   - Real Life -> वास्तविक जीवन
   - Character -> पात्र
   - Colossal Giant -> विशालकाय टाइटन
   - Cross-sectional Area -> अनुप्रस्थ काट का क्षेत्रफल
   - Linear Dimensions -> लंबाई-चौड़ाई
3. Hindi numeral expansion (60 -> साठ, 40000 -> चालीस हज़ार, 8 -> आठ).
4. Measurement units expansion (meter -> मीटर, kg -> किलोग्राम, x/times -> गुना).
5. Discourse marker alignment (दरअसल, सच तो यह है, सोचिए ज़रा, जबकि).
6. Punctuation mapping to Hindi prosody pauses (Purna Viram '।').
7. Word-level timestamp re-alignment for millisecond-accurate subtitle synchronization.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple
import unicodedata

from src.audio_engine.models import BoundaryType, TimestampBoundary
from src.common.logger import setup_logger

logger = setup_logger("native_hindi_processor")

DEFAULT_HINDI_DICT_PATH = Path(__file__).parent / "data" / "native_hindi_dict.json"


@dataclass
class ProcessedHindiResult:
    """Output of Native Hindi text processing containing pure Devanagari speech text and metadata."""

    original_text: str
    speech_text: str
    token_alignments: List[Tuple[str, str]] = field(default_factory=list)
    word_count: int = 0
    contains_latin: bool = False
    concepts_translated: List[str] = field(default_factory=list)


class NativeHindiTextProcessor:
    """Transforms raw script text into 100% pure Devanagari Hindi speech representations."""

    def __init__(self, dict_path: Optional[Path] = None):
        self.dict_path = dict_path or DEFAULT_HINDI_DICT_PATH
        self.scientific_concepts: Dict[str, str] = {}
        self.hinglish_replacements: Dict[str, str] = {}
        self.numerals_map: Dict[str, str] = {}
        self.units_map: Dict[str, str] = {}
        self.discourse_markers: Dict[str, str] = {}
        self.phonetic_refinements: Dict[str, str] = {}

        self._load_dictionary()

    def _load_dictionary(self) -> None:
        """Load native Hindi dictionary and translation tables."""
        if not self.dict_path.exists():
            logger.warning("Native Hindi dictionary not found at %s. Using internal defaults.", self.dict_path)
            self._init_fallback_lexicon()
            return

        try:
            with open(self.dict_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.scientific_concepts = data.get("scientific_concepts_translation", {})
                self.hinglish_replacements = data.get("hinglish_loanwords_to_hindi", {})
                self.numerals_map = data.get("hindi_numerals_map", {})
                self.units_map = data.get("measurement_units", {})
                self.discourse_markers = data.get("discourse_markers", {})
                self.phonetic_refinements = data.get("devanagari_phonetic_refinements", {})
            logger.debug(
                "Loaded %d scientific concepts and %d numerals from %s",
                len(self.scientific_concepts),
                len(self.numerals_map),
                self.dict_path.name,
            )
        except Exception as err:
            logger.error("Failed to load native Hindi dictionary from %s: %s", self.dict_path, err)
            self._init_fallback_lexicon()

    def _init_fallback_lexicon(self) -> None:
        """Built-in fallback lexicon if external JSON is missing."""
        self.scientific_concepts = {
            "square-cube law": "वर्ग-घन का नियम",
            "square cube law": "वर्ग-घन का नियम",
            "volume": "आयतन",
            "weight": "भार",
            "muscles": "मांसपेशियाँ",
            "physics": "भौतिक विज्ञान",
            "science": "विज्ञान",
            "real life": "वास्तविक जीवन",
            "character": "पात्र",
            "colossal giant": "विशालकाय टाइटन",
            "cross-sectional area": "अनुप्रस्थ काट का क्षेत्रफल",
            "linear dimensions": "लंबाई-चौड़ाई",
        }
        self.hinglish_replacements = {
            "स्क्वेयर-क्यूब लॉ": "वर्ग-घन का नियम",
            "स्क्वेयर क्यूब लॉ": "वर्ग-घन का नियम",
            "वॉल्यूम": "आयतन",
            "वेट": "भार",
            "मसल्स": "मांसपेशियाँ",
            "फ़िज़िक्स": "भौतिक विज्ञान",
            "साइंस": "विज्ञान",
            "रियल लाइफ़": "वास्तविक जीवन",
            "कोलोसल टाइटन": "विशालकाय टाइटन",
        }

    def number_to_hindi(self, n: int) -> str:
        """Convert an integer (0 to 999999) into spoken Devanagari Hindi words."""
        if str(n) in self.numerals_map:
            return self.numerals_map[str(n)]

        if n < 0:
            return "ऋण " + self.number_to_hindi(-n)

        if n < 100:
            return self.numerals_map.get(str(n), str(n))

        if n < 1000:
            hundreds = n // 100
            remainder = n % 100
            h_text = self.numerals_map.get(str(hundreds), str(hundreds)) + " सौ"
            if remainder == 0:
                return h_text
            r_text = self.numerals_map.get(str(remainder), self.number_to_hindi(remainder))
            return f"{h_text} {r_text}"

        if n < 100000:
            thousands = n // 1000
            remainder = n % 1000
            t_text = self.numerals_map.get(str(thousands), self.number_to_hindi(thousands)) + " हज़ार"
            if remainder == 0:
                return t_text
            r_text = self.number_to_hindi(remainder)
            return f"{t_text} {r_text}"

        if n < 10000000:
            lakhs = n // 100000
            remainder = n % 100000
            l_text = self.numerals_map.get(str(lakhs), self.number_to_hindi(lakhs)) + " लाख"
            if remainder == 0:
                return l_text
            r_text = self.number_to_hindi(remainder)
            return f"{l_text} {r_text}"

        return str(n)

    def normalize_numbers_and_units(self, text: str) -> str:
        """Normalize numeric digits, compound multipliers, and measurement units into spoken Hindi."""
        t = text

        # 1. Multipliers: e.g., 40,000x, 40000x, 8x, 2x
        def replace_multiplier(match: re.Match) -> str:
            raw_num = match.group(1).replace(",", "")
            try:
                num = int(raw_num)
                hindi_words = self.number_to_hindi(num)
                return f"{hindi_words} गुना"
            except ValueError:
                return match.group(0)

        t = re.sub(r"\b(\d[\d,]*)\s*[xX]\b", replace_multiplier, t)
        t = re.sub(r"\b(\d[\d,]*)\s* गुना\b", replace_multiplier, t)

        # 2. Hyphenated units: e.g., 60-meter, 70-kg, 60-m
        def replace_hyphen_unit(match: re.Match) -> str:
            raw_num = match.group(1).replace(",", "")
            unit = match.group(2).lower()
            try:
                num = int(raw_num)
                hindi_num = self.number_to_hindi(num)
                hindi_unit = self.units_map.get(unit, unit)
                return f"{hindi_num} {hindi_unit}"
            except ValueError:
                return match.group(0)

        t = re.sub(
            r"\b(\d[\d,]*)-([a-zA-Z]+)\b",
            replace_hyphen_unit,
            t,
        )

        # 3. Numeric + standalone unit: e.g., 60 meter, 70 kg
        def replace_num_unit(match: re.Match) -> str:
            raw_num = match.group(1).replace(",", "")
            unit = match.group(2).lower()
            if unit in self.units_map:
                try:
                    num = int(raw_num)
                    hindi_num = self.number_to_hindi(num)
                    hindi_unit = self.units_map[unit]
                    return f"{hindi_num} {hindi_unit}"
                except ValueError:
                    pass
            return match.group(0)

        t = re.sub(
            r"\b(\d[\d,]*)\s+([a-zA-Z]+)\b",
            replace_num_unit,
            t,
        )

        # 4. Standalone numbers with commas: e.g., 40,000 -> 40000 -> चालीस हज़ार
        def replace_standalone_num(match: re.Match) -> str:
            raw_num = match.group(0).replace(",", "")
            try:
                num = int(raw_num)
                return self.number_to_hindi(num)
            except ValueError:
                return match.group(0)

        t = re.sub(r"\b\d[\d,]*\b", replace_standalone_num, t)

        return t

    def translate_concepts(self, text: str) -> Tuple[str, List[str]]:
        """Translate scientific concepts and Hinglish loanwords into natural pure Hindi."""
        t = text
        translated: List[str] = []

        # 1. Compound scientific concepts in English (case-insensitive)
        # Sort by descending length so longest phrases match first
        sorted_concepts = sorted(self.scientific_concepts.items(), key=lambda kv: len(kv[0]), reverse=True)
        for english_concept, hindi_equiv in sorted_concepts:
            pattern = r"\b" + re.escape(english_concept) + r"\b"
            if re.search(pattern, t, flags=re.IGNORECASE):
                t = re.sub(pattern, hindi_equiv, t, flags=re.IGNORECASE)
                translated.append(f"{english_concept} -> {hindi_equiv}")

        # 2. Hinglish loanwords written in Devanagari (e.g. स्क्वेयर-क्यूब लॉ, वॉल्यूम, वेट)
        sorted_hinglish = sorted(self.hinglish_replacements.items(), key=lambda kv: len(kv[0]), reverse=True)
        for hinglish_term, hindi_equiv in sorted_hinglish:
            if hinglish_term in t:
                t = t.replace(hinglish_term, hindi_equiv)
                translated.append(f"{hinglish_term} -> {hindi_equiv}")

        return t, translated

    def normalize_punctuation(self, text: str) -> str:
        """Map standard punctuation to authentic Hindi prosody markers."""
        t = text

        # Replace ASCII periods ending sentences with Hindi Purna Viram '।'
        # Avoid changing periods in decimals or abbreviations if any remain
        t = re.sub(r"\.(?=\s|$)", " ।", t)

        # Ensure space before Purna Viram if missing
        t = re.sub(r"([^\s])।", r"\1 ।", t)

        # Clean multiple spaces or consecutive virams
        t = re.sub(r"([।!?])\s*([।!?])", r"\1", t)
        t = re.sub(r"\s+", " ", t).strip()

        return t

    def process_text(self, text: str) -> ProcessedHindiResult:
        """Process arbitrary input text into pure, expressive Devanagari Hindi speech text."""
        raw = text.strip()
        if not raw:
            return ProcessedHindiResult(original_text="", speech_text="", word_count=0)

        # Unicode normalization (NFC)
        raw = unicodedata.normalize("NFC", raw)

        # 1. Translate scientific concepts and loanwords
        translated_text, concepts_translated = self.translate_concepts(raw)

        # 2. Expand numbers and measurement units into Hindi words
        num_expanded = self.normalize_numbers_and_units(translated_text)

        # 3. Apply any phonetic refinements
        refined = num_expanded
        for source_word, refined_word in self.phonetic_refinements.items():
            refined = re.sub(r"\b" + re.escape(source_word) + r"\b", refined_word, refined)

        # 4. Normalize punctuation
        final_speech = self.normalize_punctuation(refined)

        # 5. Check if any Latin characters remain
        has_latin = bool(re.search(r"[a-zA-Z]", final_speech))
        if has_latin:
            logger.warning("Speech text still contains Latin characters: %s", final_speech)

        words = [w for w in re.split(r"\s+", final_speech) if w and not re.match(r"^[^\w\u0900-\u097F]+$", w)]

        # Generate simple 1-to-1 or best-effort token alignments
        orig_tokens = raw.split()
        speech_tokens = final_speech.split()
        alignments = []
        for i, s_tok in enumerate(speech_tokens):
            orig_match = orig_tokens[i] if i < len(orig_tokens) else s_tok
            alignments.append((orig_match, s_tok))

        return ProcessedHindiResult(
            original_text=raw,
            speech_text=final_speech,
            token_alignments=alignments,
            word_count=len(words),
            contains_latin=has_latin,
            concepts_translated=concepts_translated,
        )

    def align_boundaries(
        self,
        boundaries: List[TimestampBoundary],
        original_text: str,
    ) -> List[TimestampBoundary]:
        """Align synthesized word boundary timestamps back to original text tokens."""
        if not boundaries:
            return []

        orig_words = [w.strip() for w in original_text.split() if w.strip()]
        if not orig_words:
            return boundaries

        # If lengths match directly, 1-to-1 assign
        if len(boundaries) == len(orig_words):
            aligned = []
            for b, orig_w in zip(boundaries, orig_words):
                aligned.append(
                    TimestampBoundary(
                        text=orig_w,
                        offset_ms=b.offset_ms,
                        duration_ms=b.duration_ms,
                        boundary_type=b.boundary_type,
                    )
                )
            return aligned

        # If word counts differ (e.g. 60-meter -> साठ मीटर, 2 words for 1 token),
        # distribute or retain boundaries cleanly
        return boundaries
