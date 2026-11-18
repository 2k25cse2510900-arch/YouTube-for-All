"""Hinglish Text Processing Engine for Natural Indian Multi-Lingual Speech Synthesis.

Distinguishes between:
A. Hindi words written in Devanagari.
B. Hindi words written in Roman script.
C. English words embedded inside Hindi sentences.
D. Complete English sentences.
E. Technical terms, anime names and proper nouns.

Transforms mixed text into a unified, authentic Indian phonetic representation
for neural acoustic modeling while preserving original script tokens for millisecond-accurate subtitles.
"""

from dataclasses import dataclass, field
from enum import Enum
import re
from typing import Dict, List, Optional, Tuple
import unicodedata

from src.audio_engine.models import BoundaryType, TimestampBoundary
from src.audio_engine.pronunciation_dictionary import PronunciationDictionary, TokenType
from src.common.logger import setup_logger

logger = setup_logger("hinglish_processor")


class LanguageCategory(str, Enum):
    """Categorization of a word or phrase for language-aware pronunciation."""

    DEVANAGARI_HINDI = "devanagari_hindi"
    ROMAN_HINDI = "roman_hindi"
    ENGLISH_LOANWORD = "english_loanword"
    TECHNICAL_ANIME_TERM = "technical_anime_term"
    COMPLETE_ENGLISH = "complete_english"
    NUMBER_UNIT = "number_unit"
    PUNCTUATION = "punctuation"
    UNKNOWN = "unknown"


@dataclass
class TokenClassification:
    """Detailed linguistic metadata for a single token."""

    original_token: str
    speech_token: str
    category: LanguageCategory
    notes: str = ""


@dataclass
class ProcessedHinglishResult:
    """Output of Hinglish preprocessing containing speech text and token alignment mapping."""

    original_text: str
    speech_text: str
    token_alignments: List[Tuple[str, str]] = field(default_factory=list)
    classifications: List[TokenClassification] = field(default_factory=list)
    word_count: int = 0


# Recognized compound technical and anime terminology
COMPOUND_PHRASES: Dict[str, str] = {
    "square-cube law": "स्क्वेयर-क्यूब लॉ",
    "square cube law": "स्क्वेयर-क्यूब लॉ",
    "colossal giant": "कोलोसल टाइटन",
    "the science of giants": "अटैक ऑन टाइटन",
    "cross-sectional area": "क्रॉस-सेक्शनल एरिया",
    "cross sectional area": "क्रॉस-सेक्शनल एरिया",
    "real life": "रियल लाइफ़",
    "linear dimensions": "लीनियर डायमेंशन्स",
    "eren jaeger": "एरेन येगर",
    "captain levi": "कैप्टन लिवाई",
    "navigator ackerman": "मिकासा एकरमैन",
}


class HinglishTextProcessor:
    """Transforms Roman and mixed Hinglish into authentic Indian speech representations."""

    def __init__(
        self,
        dictionary: Optional[PronunciationDictionary] = None,
        indian_phonetic_english: bool = False,
    ):
        self.dictionary = dictionary or PronunciationDictionary()
        self.indian_phonetic_english = indian_phonetic_english

    def process_indian_hinglish(self, text: str) -> ProcessedHinglishResult:
        """Process text into authentic Indian Hinglish with Indian English phonetics for all loanwords."""
        return self.process_text(text, preserve_english_latin=False)

    def normalize_numbers_and_units(self, text: str) -> str:
        """Expand numbers, units, and mathematical symbols for natural spoken delivery."""
        t = text

        # 1. Hyphenated measurement units (e.g., "60-meter", "100-kg", "70-kg")
        t = re.sub(r"(\d+)-meter\b", r"\1 meter", t, flags=re.IGNORECASE)
        t = re.sub(r"(\d+)-metre\b", r"\1 meter", t, flags=re.IGNORECASE)
        t = re.sub(r"(\d+)-second\b", r"\1 second", t, flags=re.IGNORECASE)
        t = re.sub(r"(\d+)-kg\b", r"\1 किलोग्राम", t, flags=re.IGNORECASE)

        # 2. Multipliers (e.g. "40,000x", "40,000×", "30x", "30×", "1156x")
        t = re.sub(r"(\d[\d,]*)\s*[xX×]\b", r"\1 गुना", t)
        t = re.sub(r"(\d[\d,]*)\s*[xX×]\s", r"\1 गुना ", t)

        # 3. Exponents and Powers (e.g. "(34)³", "(34)^3", "L³", "L²")
        t = re.sub(r"\((\d+)\)[³\^3]", r"\1 का cube", t)
        t = re.sub(r"\((\d+)\)[²\^2]", r"\1 का square", t)
        t = re.sub(r"\bA\s*∝\s*L²", "Area proportional to L square", t)
        t = re.sub(r"\bV\s*∝\s*L³", "Volume proportional to L cube", t)
        t = re.sub(r"\bL³\b", "L cube", t)
        t = re.sub(r"\bL²\b", "L square", t)

        # 4. Standardize punctuation spacing
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def classify_token(self, token: str) -> LanguageCategory:
        """Categorize an individual token into its linguistic category."""
        clean = token.strip()
        if not clean:
            return LanguageCategory.UNKNOWN

        if re.match(r"^[^\w\s\u0900-\u097F]+$", clean):
            return LanguageCategory.PUNCTUATION

        if re.match(r"^\d+([.,]\d+)?(-[a-zA-Z]+)?$", clean):
            return LanguageCategory.NUMBER_UNIT

        if re.search(r"[\u0900-\u097F]", clean):
            return LanguageCategory.DEVANAGARI_HINDI

        clean_lower = clean.lower()
        if clean_lower in [
            "square-cube", "titan", "titans", "colossal", "physics", "science",
            "volume", "weight", "muscles", "muscle", "anime", "attack",
            "biomechanics", "linear", "dimensions", "area", "scale", "skeleton",
            "gravity", "stress", "density"
        ]:
            return LanguageCategory.TECHNICAL_ANIME_TERM

        if self.dictionary.is_english_term(clean_lower):
            return LanguageCategory.ENGLISH_LOANWORD

        if clean_lower in self.dictionary._hindi_roman:
            return LanguageCategory.ROMAN_HINDI

        # Heuristic: If token contains common English morphology (e.g., 'tion', 'ment', 'ing')
        if any(clean_lower.endswith(sfx) for sfx in ["tion", "ment", "ing", "ness", "ity", "ble", "ous"]):
            return LanguageCategory.ENGLISH_LOANWORD

        return LanguageCategory.UNKNOWN

    def process_text(
        self,
        text: str,
        preserve_english_latin: Optional[bool] = None,
    ) -> ProcessedHinglishResult:
        """Process script text into natural dual-script text for the neural acoustic model.

        Parameters:
            text: Input script sentence (may be Roman Hindi, Devanagari, English, or mixed Hinglish).
            preserve_english_latin: Optional override. If True, English technical terms remain Latin.
                                    If False (default), English loanwords use Indian English phonetics.
        """
        if not text or not text.strip():
            return ProcessedHinglishResult(
                original_text="",
                speech_text="",
                token_alignments=[],
                classifications=[],
                word_count=0,
            )

        use_latin = preserve_english_latin if preserve_english_latin is not None else (not self.indian_phonetic_english)

        cleaned_text = unicodedata.normalize("NFKC", text.strip())
        normalized = self.normalize_numbers_and_units(cleaned_text)

        # Extract tokens preserving compound hyphenated words and punctuation
        tokens = re.findall(r"[\w\u0900-\u097F]+(?:-[\w\u0900-\u097F]+)*|[^\w\s\u0900-\u097F]+", normalized)

        processed_tokens: List[str] = []
        alignment_pairs: List[Tuple[str, str]] = []
        classifications: List[TokenClassification] = []

        i = 0
        while i < len(tokens):
            token = tokens[i]

            # Punctuation check
            if re.match(r"^[^\w\s\u0900-\u097F]+$", token):
                processed_tokens.append(token)
                classifications.append(
                    TokenClassification(
                        original_token=token,
                        speech_token=token,
                        category=LanguageCategory.PUNCTUATION,
                    )
                )
                i += 1
                continue

            # Check 2-word or 3-word compound phrases (e.g. "Square-Cube Law" or "The Science of Giants")
            compound_matched = False
            for span_len in (3, 2):
                if i + span_len <= len(tokens):
                    candidate = " ".join(tokens[i : i + span_len]).lower()
                    if candidate in COMPOUND_PHRASES and not use_latin:
                        speech_sub = COMPOUND_PHRASES[candidate]
                        sub_words = speech_sub.split(" ")
                        # Map each constituent token to a speech sub-token if equal length
                        if len(sub_words) == span_len:
                            for idx in range(span_len):
                                orig_tok = tokens[i + idx]
                                sp_tok = sub_words[idx]
                                processed_tokens.append(sp_tok)
                                alignment_pairs.append((orig_tok, sp_tok))
                                classifications.append(
                                    TokenClassification(
                                        original_token=orig_tok,
                                        speech_token=sp_tok,
                                        category=LanguageCategory.TECHNICAL_ANIME_TERM,
                                        notes=f"Compound match: {candidate}",
                                    )
                                )
                        else:
                            # Aggregate first token
                            for idx in range(span_len):
                                orig_tok = tokens[i + idx]
                                sp_tok = sub_words[0] if idx == 0 else ""
                                if sp_tok:
                                    processed_tokens.append(speech_sub)
                                alignment_pairs.append((orig_tok, speech_sub))
                                classifications.append(
                                    TokenClassification(
                                        original_token=orig_tok,
                                        speech_token=speech_sub,
                                        category=LanguageCategory.TECHNICAL_ANIME_TERM,
                                    )
                                )
                        i += span_len
                        compound_matched = True
                        break

            if compound_matched:
                continue

            cat = self.classify_token(token)

            # Transliterate or preserve word
            if use_latin and cat in (LanguageCategory.ENGLISH_LOANWORD, LanguageCategory.TECHNICAL_ANIME_TERM):
                # Preserved in Latin for legacy dual-script test mode
                processed_tokens.append(token)
                alignment_pairs.append((token, token))
                classifications.append(TokenClassification(original_token=token, speech_token=token, category=cat))
            else:
                # Look up language-aware Indian phonetic representation
                speech_word = self.dictionary.lookup(token, preserve_english_latin=use_latin)
                if speech_word:
                    processed_tokens.append(speech_word)
                    alignment_pairs.append((token, speech_word))
                    classifications.append(TokenClassification(original_token=token, speech_token=speech_word, category=cat))
                else:
                    processed_tokens.append(token)
                    alignment_pairs.append((token, token))
                    classifications.append(TokenClassification(original_token=token, speech_token=token, category=cat))

            i += 1

        # Reconstruct natural speech string with correct punctuation spacing
        speech_text = ""
        for idx, tok in enumerate(processed_tokens):
            if idx > 0 and not re.match(r"^[.,!?;:।\-/\'\"]+$", tok) and not speech_text.endswith(("-", " ", "/", "'", '"')):
                speech_text += " "
            speech_text += tok

        speech_text = speech_text.strip()
        orig_words = re.findall(r"[\w\u0900-\u097F]+", cleaned_text)

        return ProcessedHinglishResult(
            original_text=cleaned_text,
            speech_text=speech_text,
            token_alignments=alignment_pairs,
            classifications=classifications,
            word_count=len(orig_words),
        )

    def align_boundaries(
        self,
        boundaries: List[TimestampBoundary],
        original_text: str,
    ) -> List[TimestampBoundary]:
        """Align TTS provider timestamp boundaries back to original script words.

        Ensures subtitles match the approved script word-for-word while inheriting
        the precise millisecond timing of the synthesized speech.
        """
        orig_words = re.findall(r"[\w\u0900-\u097F]+(?:-[\w\u0900-\u097F]+)*", original_text)
        word_boundaries = [b for b in boundaries if b.boundary_type == BoundaryType.WORD]

        if not word_boundaries or not orig_words:
            return boundaries

        # Exact 1-to-1 match
        if len(word_boundaries) == len(orig_words):
            aligned: List[TimestampBoundary] = []
            for b, orig_w in zip(word_boundaries, orig_words):
                aligned.append(
                    TimestampBoundary(
                        text=orig_w,
                        offset_ms=b.offset_ms,
                        duration_ms=b.duration_ms,
                        boundary_type=BoundaryType.WORD,
                    )
                )
            return aligned

        # Handle split tokens (e.g. "60-meter" split into "60" and "meter")
        aligned = []
        b_idx = 0
        for orig_w in orig_words:
            if b_idx >= len(word_boundaries):
                break

            sub_tokens = orig_w.split("-")
            if len(sub_tokens) > 1 and b_idx + len(sub_tokens) <= len(word_boundaries):
                first_b = word_boundaries[b_idx]
                last_b = word_boundaries[b_idx + len(sub_tokens) - 1]
                total_dur = round((last_b.offset_ms + last_b.duration_ms) - first_b.offset_ms, 2)
                aligned.append(
                    TimestampBoundary(
                        text=orig_w,
                        offset_ms=first_b.offset_ms,
                        duration_ms=total_dur,
                        boundary_type=BoundaryType.WORD,
                    )
                )
                b_idx += len(sub_tokens)
            else:
                aligned.append(
                    TimestampBoundary(
                        text=orig_w,
                        offset_ms=word_boundaries[b_idx].offset_ms,
                        duration_ms=word_boundaries[b_idx].duration_ms,
                        boundary_type=BoundaryType.WORD,
                    )
                )
                b_idx += 1

        return aligned
