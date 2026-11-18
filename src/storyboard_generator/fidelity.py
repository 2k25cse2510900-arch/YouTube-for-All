"""Script-to-Storyboard Narration Fidelity Validation Service."""

from dataclasses import dataclass, field
import hashlib
import re
from typing import List, Optional, Tuple
import unicodedata

from src.script_manager.models import Script
from src.storyboard_generator.exceptions import ScriptFidelityError, StoryboardGeneratorError
from src.storyboard_generator.models import StoryboardDossier


@dataclass
class NarrationFidelityReport:
    """Detailed audit report verifying storyboard fidelity to its approved script."""

    is_valid: bool
    source_script_id: str
    script_checksum: str
    storyboard_checksum: str
    total_script_words: int
    total_storyboard_words: int
    hook_preserved: bool
    body_preserved: bool
    takeaway_preserved: bool
    sentence_order_preserved: bool
    missing_sentences: List[str] = field(default_factory=list)
    inserted_sentences: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def normalize_narration_text(text: str) -> str:
    """Normalize whitespace and Unicode while preserving characters and words."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKC", text)
    # Replace multiple spaces/newlines with a single space
    norm = re.sub(r"\s+", " ", norm).strip()
    return norm


def compute_canonical_narration_checksum(text: str) -> str:
    """Compute deterministic SHA-256 hash of normalized, punctuation-stripped lowercase words."""
    norm = normalize_narration_text(text).lower()
    # Remove punctuation for fuzzy-safe textual comparison
    clean_words = re.findall(r"[\w]+", norm)
    canonical = " ".join(clean_words)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def extract_sentences(text: str) -> List[str]:
    """Split Hindi/Hinglish text into discrete sentences respecting terminal punctuation."""
    norm = normalize_narration_text(text)
    if not norm:
        return []
    # Split on sentence terminals: ., ?, !, ।, or ellipsis followed by space
    raw_sentences = re.split(r"(?<=[.?!।])\s+", norm)
    sentences = [s.strip() for s in raw_sentences if s.strip()]
    return sentences


def extract_words(text: str) -> List[str]:
    """Extract ordered alphanumeric words (lowercased) for exact word-by-word fidelity checks."""
    norm = normalize_narration_text(text).lower()
    return re.findall(r"[\w]+", norm)


class ScriptStoryboardFidelityValidator:
    """Validates that a storyboard strictly preserves its source script without silent edits."""

    @classmethod
    def validate_fidelity(
        cls,
        script: Script,
        storyboard: StoryboardDossier,
        raise_on_error: bool = True,
    ) -> NarrationFidelityReport:
        """Verify that storyboard scenes contain the exact approved narration from script.

        Rules enforced:
        1. Source Script ID matches.
        2. Hook is preserved without modification.
        3. Body sentences are preserved in exact order without omission or insertions.
        4. Takeaway is preserved without omission.
        5. Sentence order is preserved across scenes.
        6. Every spoken sentence in script appears exactly once in storyboard.
        7. No extra narration is inserted.
        8. Exact word sequence matches.
        """
        errors: List[str] = []

        # 1. Script ID provenance
        if storyboard.source_script_id and storyboard.source_script_id != script.id:
            errors.append(
                f"Source script ID mismatch: Storyboard references '{storyboard.source_script_id}', "
                f"but validating against script '{script.id}'."
            )

        # 2. Extract script sentences
        hook_sentences = extract_sentences(script.hook)
        body_sentences = extract_sentences(script.body)
        takeaway_sentences = extract_sentences(script.takeaway)

        all_script_sentences = hook_sentences + body_sentences + takeaway_sentences
        script_full_text = f"{script.hook} {script.body} {script.takeaway}"
        script_words = extract_words(script_full_text)

        # 3. Extract storyboard scene sentences
        storyboard_scene_texts = [s.narration_hinglish for s in storyboard.scenes]
        storyboard_full_text = " ".join(storyboard_scene_texts)
        storyboard_words = extract_words(storyboard_full_text)

        all_storyboard_sentences: List[str] = []
        for scene_text in storyboard_scene_texts:
            all_storyboard_sentences.extend(extract_sentences(scene_text))

        # Checksums
        script_checksum = compute_canonical_narration_checksum(script_full_text)
        storyboard_checksum = compute_canonical_narration_checksum(storyboard_full_text)

        # 4. Check Hook preservation
        hook_canonical = compute_canonical_narration_checksum(script.hook)
        first_scene_words = extract_words(storyboard.scenes[0].narration_hinglish) if storyboard.scenes else []
        hook_words = extract_words(script.hook)
        hook_preserved = (hook_words == first_scene_words[:len(hook_words)]) if hook_words else False

        if not hook_preserved:
            # Check if hook appears in first scene
            errors.append(
                f"Script Hook not preserved in Storyboard opening scene. "
                f"Expected: '{script.hook}', Got: '{storyboard.scenes[0].narration_hinglish if storyboard.scenes else ''}'."
            )

        # 5. Check Takeaway preservation
        takeaway_canonical = compute_canonical_narration_checksum(script.takeaway)
        last_scene_words = extract_words(storyboard.scenes[-1].narration_hinglish) if storyboard.scenes else []
        takeaway_words = extract_words(script.takeaway)
        takeaway_preserved = (takeaway_words == last_scene_words[-len(takeaway_words):]) if takeaway_words else False

        if not takeaway_preserved:
            # Check if takeaway appears in any scene
            takeaway_found_anywhere = any(
                compute_canonical_narration_checksum(script.takeaway) in compute_canonical_narration_checksum(s.narration_hinglish)
                for s in storyboard.scenes
            )
            if not takeaway_found_anywhere:
                errors.append(
                    f"Script Takeaway omitted from Storyboard narration. "
                    f"Approved takeaway was: '{script.takeaway}'."
                )

        # 6. Sentence-by-sentence matching and ordering
        missing_sentences: List[str] = []
        script_canon_sentences = [compute_canonical_narration_checksum(s) for s in all_script_sentences]
        sb_canon_sentences = [compute_canonical_narration_checksum(s) for s in all_storyboard_sentences]

        for s_orig, s_canon in zip(all_script_sentences, script_canon_sentences):
            if s_canon not in sb_canon_sentences:
                missing_sentences.append(s_orig)

        inserted_sentences: List[str] = []
        for sb_orig, sb_canon in zip(all_storyboard_sentences, sb_canon_sentences):
            if sb_canon not in script_canon_sentences:
                inserted_sentences.append(sb_orig)

        if missing_sentences:
            errors.append(f"Approved script sentences missing from storyboard: {missing_sentences}")

        if inserted_sentences:
            errors.append(f"Unapproved extra sentences inserted into storyboard: {inserted_sentences}")

        # Check sentence order
        sentence_order_preserved = True
        sb_indices = []
        for s_canon in script_canon_sentences:
            if s_canon in sb_canon_sentences:
                sb_indices.append(sb_canon_sentences.index(s_canon))

        if sb_indices != sorted(sb_indices) or len(set(sb_indices)) != len(sb_indices):
            sentence_order_preserved = False
            errors.append("Sentence sequence ordering violated: Storyboard scenes narrate script out of order or with duplicates.")

        # 7. Word-for-word exact sequence check
        if script_words != storyboard_words:
            if len(script_words) != len(storyboard_words):
                errors.append(
                    f"Narration word count mismatch: Approved script has {len(script_words)} words, "
                    f"storyboard narration has {len(storyboard_words)} words."
                )
            else:
                for idx, (sw, sbw) in enumerate(zip(script_words, storyboard_words)):
                    if sw != sbw:
                        errors.append(f"Narration word discrepancy at position {idx+1}: expected '{sw}', got '{sbw}'.")
                        break

        body_preserved = (len(missing_sentences) == 0 and len(inserted_sentences) == 0 and sentence_order_preserved)
        is_valid = len(errors) == 0

        report = NarrationFidelityReport(
            is_valid=is_valid,
            source_script_id=script.id,
            script_checksum=script_checksum,
            storyboard_checksum=storyboard_checksum,
            total_script_words=len(script_words),
            total_storyboard_words=len(storyboard_words),
            hook_preserved=hook_preserved,
            body_preserved=body_preserved,
            takeaway_preserved=takeaway_preserved,
            sentence_order_preserved=sentence_order_preserved,
            missing_sentences=missing_sentences,
            inserted_sentences=inserted_sentences,
            errors=errors,
        )

        if not is_valid and raise_on_error:
            raise ScriptFidelityError(
                f"Script-to-Storyboard Fidelity Failure for script '{script.id}':\n"
                + "\n".join(f"- {e}" for e in errors)
            )

        return report
