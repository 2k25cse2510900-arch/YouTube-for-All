"""Pronunciation Dictionary for Hinglish Voice Synthesis.

Maintains comprehensive phonetic mappings for:
1. Roman Hindi to canonical Devanagari.
2. English loanwords and scientific terminology to authentic Indian English phonetics.
3. Devanagari phonetic refinements for neural vocoder acoustic clarity.
"""

from enum import Enum
import json
from pathlib import Path
import re
from typing import Dict, List, Optional, Set

from src.common.logger import setup_logger

logger = setup_logger("pronunciation_dictionary")

DEFAULT_DICT_PATH = Path(__file__).parent / "data" / "pronunciation_dict.json"


class TokenType(str, Enum):
    """Linguistic classification of an input token."""

    DEVANAGARI_HINDI = "devanagari_hindi"
    ROMAN_HINDI = "roman_hindi"
    ENGLISH_INDIAN_PHONETIC = "english_indian_phonetic"
    NUMBER_UNIT = "number_unit"
    PUNCTUATION = "punctuation"
    UNKNOWN = "unknown"


class PronunciationDictionary:
    """Manages language-aware phonetic mappings for authentic Indian Hinglish narration."""

    def __init__(self, custom_dict_path: Optional[Path] = None):
        self._hindi_roman: Dict[str, str] = {}
        self._english_phonetic: Dict[str, str] = {}
        self._devanagari_fixes: Dict[str, str] = {}
        self._custom_overrides: Dict[str, str] = {}
        self._english_allowlist: Set[str] = set()

        # Load bundled base dictionary
        if DEFAULT_DICT_PATH.exists():
            self._load_file(DEFAULT_DICT_PATH)
        else:
            logger.warning("Bundled pronunciation dictionary not found at %s", DEFAULT_DICT_PATH)

        # Load optional custom user dictionary override
        if custom_dict_path and Path(custom_dict_path).exists():
            self._load_file(Path(custom_dict_path))

    def _load_file(self, path: Path) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

                # Modern structured dictionary
                if "hindi_roman_to_devanagari" in data or "english_to_indian_phonetics" in data:
                    hr = data.get("hindi_roman_to_devanagari", {})
                    for k, v in hr.items():
                        self._hindi_roman[k.lower().strip()] = v

                    ep = data.get("english_to_indian_phonetics", {})
                    for k, v in ep.items():
                        self._english_phonetic[k.lower().strip()] = v

                    df = data.get("devanagari_phonetic_fixes", {})
                    for k, v in df.items():
                        self._devanagari_fixes[k.strip()] = v

                    co = data.get("custom_overrides", {})
                    for k, v in co.items():
                        self._custom_overrides[k.lower().strip()] = v

                # Legacy entries dictionary format
                entries = data.get("entries", {})
                for k, v in entries.items():
                    self._hindi_roman[k.lower().strip()] = v

                for term in data.get("english_terms", []):
                    self._english_allowlist.add(term.lower().strip())

            total_entries = len(self._hindi_roman) + len(self._english_phonetic) + len(self._devanagari_fixes) + len(self._custom_overrides)
            logger.debug("Loaded %d pronunciation entries from %s", total_entries, path.name)
        except Exception as err:
            logger.error("Failed to load pronunciation dictionary from %s: %s", path, err)

    def classify_token(self, token: str) -> TokenType:
        """Classify a token linguistically into Devanagari, Roman Hindi, English loanword, or punctuation."""
        clean = token.strip()
        if not clean:
            return TokenType.UNKNOWN

        # Punctuation check
        if re.match(r"^[^\w\s\u0900-\u097F]+$", clean):
            return TokenType.PUNCTUATION

        # Number or unit check
        if re.match(r"^\d+([.,]\d+)?(-[a-zA-Z]+)?$", clean):
            return TokenType.NUMBER_UNIT

        # Devanagari character range check
        if re.search(r"[\u0900-\u097F]", clean):
            return TokenType.DEVANAGARI_HINDI

        clean_lower = clean.lower()
        if clean_lower in self._english_phonetic or clean_lower in self._english_allowlist:
            return TokenType.ENGLISH_INDIAN_PHONETIC

        if clean_lower in self._hindi_roman:
            return TokenType.ROMAN_HINDI

        return TokenType.UNKNOWN

    def lookup(self, word: str, preserve_english_latin: bool = True) -> Optional[str]:
        """Look up language-aware phonetic translation for a single token.

        Parameters:
            word: The input word (Roman Hindi, Devanagari, or English loanword).
            preserve_english_latin: If True (default), English loanwords return None (preserving Latin).
                                    If False, returns authentic Indian English phonetic Devanagari.
        """
        clean = word.strip()
        if not clean:
            return None

        clean_lower = clean.lower()
        # Custom runtime overrides take highest precedence
        if clean_lower in self._custom_overrides:
            return self._custom_overrides[clean_lower]

        # Devanagari phonetic fixes
        if clean in self._devanagari_fixes:
            return self._devanagari_fixes[clean]

        # English allowlist check: if preserving Latin, return None
        if preserve_english_latin:
            if clean_lower in self._english_allowlist or clean_lower in self._english_phonetic:
                return None
        else:
            if clean_lower in self._english_phonetic:
                return self._english_phonetic[clean_lower]

        # Roman Hindi to Devanagari
        if clean_lower in self._hindi_roman:
            return self._hindi_roman[clean_lower]

        # If already Devanagari and no override, return as-is
        if re.search(r"[\u0900-\u097F]", clean):
            return clean

        return None

    def lookup_indian_phonetic(self, word: str) -> Optional[str]:
        """Look up authentic Indian English phonetic Devanagari transcription for an English word."""
        clean_lower = word.lower().strip()
        if clean_lower in self._custom_overrides:
            return self._custom_overrides[clean_lower]
        return self._english_phonetic.get(clean_lower)

    def lookup_hindi_devanagari(self, word: str) -> Optional[str]:
        """Look up canonical Devanagari for a Roman Hindi word."""
        clean_lower = word.lower().strip()
        if clean_lower in self._custom_overrides:
            return self._custom_overrides[clean_lower]
        return self._hindi_roman.get(clean_lower)

    def lookup_compound(self, phrase: str) -> Optional[str]:
        """Look up multi-word compound terms (e.g. 'Square-Cube Law', 'The Science of Giants')."""
        clean = re.sub(r"\s+", " ", phrase.lower().strip())
        if clean in self._custom_overrides:
            return self._custom_overrides[clean]
        if clean in self._english_phonetic:
            return self._english_phonetic[clean]
        if clean in self._hindi_roman:
            return self._hindi_roman[clean]
        return None

    def register(self, word: str, replacement: str) -> None:
        """Register or override a custom phonetic translation at runtime."""
        self._custom_overrides[word.lower().strip()] = replacement

    def register_english_term(self, term: str) -> None:
        """Register an English term in the allowlist."""
        self._english_allowlist.add(term.lower().strip())

    def register_indian_phonetic(self, english_term: str, indian_phonetic: str) -> None:
        """Register an explicit Indian English phonetic mapping for an English loanword."""
        self._english_phonetic[english_term.lower().strip()] = indian_phonetic.strip()

    def is_english_term(self, word: str) -> bool:
        """Check whether a word is recognized as an English term."""
        clean = word.lower().strip()
        return clean in self._english_allowlist or clean in self._english_phonetic

    def is_devanagari(self, word: str) -> bool:
        """Check whether a token contains Devanagari script."""
        return bool(re.search(r"[\u0900-\u097F]", word))

    def to_dict(self) -> Dict[str, str]:
        """Return a consolidated copy of all phonetic dictionary entries."""
        combined = dict(self._hindi_roman)
        combined.update(self._english_phonetic)
        combined.update(self._devanagari_fixes)
        combined.update(self._custom_overrides)
        return combined

    def save_to_json(self, path: Path) -> None:
        """Export current dictionary state to structured JSON."""
        out_p = Path(path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump({
                "hindi_roman_to_devanagari": self._hindi_roman,
                "english_to_indian_phonetics": self._english_phonetic,
                "devanagari_phonetic_fixes": self._devanagari_fixes,
                "custom_overrides": self._custom_overrides,
                "english_terms": sorted(list(self._english_allowlist))
            }, f, ensure_ascii=False, indent=2)
        logger.info("Saved pronunciation entries to %s", out_p)
