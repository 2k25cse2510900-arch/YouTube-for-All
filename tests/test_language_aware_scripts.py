"""Tests proving language-aware script generation across Hindi, Hinglish, and English modes."""

import pytest
from src.script_manager.models import (
    ContentCategory,
    ResearchReference,
    SceneBreakdown,
    Script,
    ScriptLanguage,
    ScriptStatus,
    detect_script_language,
)


def test_hindi_language_script():
    """Verify Hindi script detection, validation, and retention."""
    hindi_script = Script(
        id="test_hindi_chrono_01",
        title="काल चक्र का रहस्य",
        category=ContentCategory.ANIME_SCIENCE,
        hook="क्या समय को सच में एक सेकंड के लिए रोका जा सकता है?",
        body="आइंस्टीन के सापेक्षता सिद्धांत के अनुसार, यदि कोई प्रकाश की गति से चले तो समय धीमा हो जाता है। लेकिन असल दुनिया में ऐसा करना भौतिक विज्ञान के नियमों के विपरीत है!",
        takeaway="तो अगली बार जब आप कोई एनिमे देखें, तो भौतिक विज्ञान के इस नियम को याद रखें।",
        language=ScriptLanguage.HINDI,
    )
    assert hindi_script.language == ScriptLanguage.HINDI
    assert "सापेक्षता सिद्धांत" in hindi_script.body
    assert detect_script_language(hindi_script.hook) == ScriptLanguage.HINDI


def test_hinglish_language_script():
    """Verify Hinglish script detection with technical terms in English."""
    hinglish_script = Script(
        id="test_hinglish_chrono_01",
        title="Can You Freeze Time in Real Life?",
        category=ContentCategory.ANIME_SCIENCE,
        hook="Anime mein toh characters easily time freeze kar dete hain!",
        body="Lekin real physics mein agar time freeze hua, toh light photons bhi ruk jayenge, aur aap completely blind ho jaoge! Isliye Quantum Mechanics kehta hai time dilation possible hai, par freeze karna impossible.",
        takeaway="Next time jab bhi aap anime dekhein, physics ke is rule ko zaroor yaad rakhein!",
    )
    # Auto-detection should identify Hinglish
    assert hinglish_script.language == ScriptLanguage.HINGLISH
    assert "time freeze" in hinglish_script.hook
    assert "Quantum Mechanics" in hinglish_script.body


def test_english_language_script():
    """Verify pure English script detection and validation."""
    english_script = Script(
        id="test_english_chrono_01",
        title="The Physics of Time Dilation",
        category=ContentCategory.ANIME_SCIENCE,
        hook="What happens to the human body if time suddenly halts?",
        body="According to special relativity, stopping time requires infinite energy and halts all photon movement, plunging the observer into absolute darkness and silence.",
        takeaway="Physics always demands a price for bending the laws of the universe.",
    )
    assert english_script.language == ScriptLanguage.ENGLISH
    assert detect_script_language(english_script.hook) == ScriptLanguage.ENGLISH


def test_language_detection_edge_cases():
    """Verify robust handling of edge cases in language detection."""
    assert detect_script_language("") == ScriptLanguage.HINGLISH
    assert detect_script_language("   ") == ScriptLanguage.HINGLISH

    # Predominantly English with one technical term
    eng_text = "The chrono-anchor stabilizes quantum fluctuations in the localized spacetime manifold."
    assert detect_script_language(eng_text) == ScriptLanguage.ENGLISH

    # Devanagari Hindi
    hindi_text = "क्या अटैक ऑन टाइटन का साठ मीटर लंबा विशालकाय टाइटन ज़िंदा रह सकता है?"
    assert detect_script_language(hindi_text) == ScriptLanguage.HINDI

    # Natural conversational Hinglish
    hinglish_text = "Agar aap light speed se travel karte hain toh aapka time slow ho jayega."
    assert detect_script_language(hinglish_text) == ScriptLanguage.HINGLISH
