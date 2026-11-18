"""Prosody and Emotion Controller for Human-Like Native Hindi Speech Cadence.

Supports 7 Expressive Native Hindi Delivery Styles:
1. SAMANYA (सामान्य बातचीत - Conversational / Explanatory)
2. UTSAH (उत्साहपूर्ण वर्णन - Excited / Energetic)
3. JIGYASA (जिज्ञासा - Curious / Questioning / Hook)
4. AASHCHARYA (आश्चर्य - Surprise / Shocking Fact)
5. GAMBHIR (गंभीर व्याख्या - Serious / Dramatic / Scientific Reality)
6. BHAVNATMAK (भावनात्मक कहानी - Emotional Storytelling)
7. PRERNADAYAK (प्रेरणादायक वर्णन - Inspiring / Closing Takeaway)

Maintains full backward compatibility with legacy English style names.
"""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Dict, List, Optional

from src.common.logger import setup_logger

logger = setup_logger("prosody_controller")


class DeliveryStyle(str, Enum):
    """Supported delivery styles for expressive narrative voiceover."""

    # --- 7 Pure Native Hindi Styles ---
    SAMANYA = "samanya"              # सामान्य बातचीत (Conversational / Explanatory)
    UTSAH = "utsah"                  # उत्साहपूर्ण वर्णन (Excited / Energetic)
    JIGYASA = "jigyasa"              # जिज्ञासा (Curious / Questioning / Hook)
    AASHCHARYA = "aashcharya"        # आश्चर्य (Surprise / Shocking Fact)
    GAMBHIR = "gambhir"              # गंभीर व्याख्या (Serious / Dramatic / Scientific Reality)
    BHAVNATMAK = "bhavnatmak"        # भावनात्मक कहानी (Emotional Storytelling)
    PRERNADAYAK = "prernadayak"      # प्रेरणादायक वर्णन (Inspiring / Closing Takeaway)

    # --- Legacy English Styles (Preserved for full backward compatibility) ---
    CONVERSATIONAL = "conversational"
    CURIOUS = "curious"
    EXCITED = "excited"
    EDUCATIONAL = "educational"
    SERIOUS = "serious"
    DRAMATIC = "dramatic"
    EMOTIONAL = "emotional"
    SURPRISE = "surprise"
    CALM = "calm"


@dataclass
class ProsodyProfile:
    """Acoustic prosody settings governing rate, pitch, volume, and rhythm."""

    style: DeliveryStyle
    rate: str = "+0%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    clause_pause_ms: int = 180  # Natural breathing pause at commas / alpa viram
    sentence_pause_ms: int = 400  # Pacing between distinct sentences / purna viram
    emphasis_level: str = "moderate"


# Curated acoustic parameter profiles for neural speech engines
PROSODY_PROFILES: Dict[DeliveryStyle, ProsodyProfile] = {
    # --- Native Hindi Expressive Profiles ---
    DeliveryStyle.SAMANYA: ProsodyProfile(
        style=DeliveryStyle.SAMANYA,
        rate="+2%",
        pitch="+0Hz",
        volume="+0%",
        clause_pause_ms=180,
        sentence_pause_ms=400,
        emphasis_level="moderate",
    ),
    DeliveryStyle.UTSAH: ProsodyProfile(
        style=DeliveryStyle.UTSAH,
        rate="+10%",
        pitch="+5Hz",
        volume="+2%",
        clause_pause_ms=140,
        sentence_pause_ms=320,
        emphasis_level="strong",
    ),
    DeliveryStyle.JIGYASA: ProsodyProfile(
        style=DeliveryStyle.JIGYASA,
        rate="+4%",
        pitch="+4Hz",
        volume="+1%",
        clause_pause_ms=170,
        sentence_pause_ms=380,
        emphasis_level="moderate",
    ),
    DeliveryStyle.AASHCHARYA: ProsodyProfile(
        style=DeliveryStyle.AASHCHARYA,
        rate="+6%",
        pitch="+6Hz",
        volume="+2%",
        clause_pause_ms=150,
        sentence_pause_ms=350,
        emphasis_level="strong",
    ),
    DeliveryStyle.GAMBHIR: ProsodyProfile(
        style=DeliveryStyle.GAMBHIR,
        rate="-4%",
        pitch="-4Hz",
        volume="+1%",
        clause_pause_ms=240,
        sentence_pause_ms=500,
        emphasis_level="strong",
    ),
    DeliveryStyle.BHAVNATMAK: ProsodyProfile(
        style=DeliveryStyle.BHAVNATMAK,
        rate="-2%",
        pitch="-2Hz",
        volume="+0%",
        clause_pause_ms=200,
        sentence_pause_ms=450,
        emphasis_level="moderate",
    ),
    DeliveryStyle.PRERNADAYAK: ProsodyProfile(
        style=DeliveryStyle.PRERNADAYAK,
        rate="+2%",
        pitch="+2Hz",
        volume="+1%",
        clause_pause_ms=180,
        sentence_pause_ms=420,
        emphasis_level="moderate",
    ),

    # --- Legacy English Profiles ---
    DeliveryStyle.CONVERSATIONAL: ProsodyProfile(
        style=DeliveryStyle.CONVERSATIONAL,
        rate="+3%",
        pitch="+1Hz",
        volume="+0%",
        clause_pause_ms=170,
        sentence_pause_ms=380,
        emphasis_level="moderate",
    ),
    DeliveryStyle.CURIOUS: ProsodyProfile(
        style=DeliveryStyle.CURIOUS,
        rate="+4%",
        pitch="+4Hz",
        volume="+1%",
        clause_pause_ms=180,
        sentence_pause_ms=400,
        emphasis_level="moderate",
    ),
    DeliveryStyle.EXCITED: ProsodyProfile(
        style=DeliveryStyle.EXCITED,
        rate="+12%",
        pitch="+6Hz",
        volume="+2%",
        clause_pause_ms=140,
        sentence_pause_ms=320,
        emphasis_level="strong",
    ),
    DeliveryStyle.SURPRISE: ProsodyProfile(
        style=DeliveryStyle.SURPRISE,
        rate="+8%",
        pitch="+6Hz",
        volume="+2%",
        clause_pause_ms=150,
        sentence_pause_ms=350,
        emphasis_level="strong",
    ),
    DeliveryStyle.EDUCATIONAL: ProsodyProfile(
        style=DeliveryStyle.EDUCATIONAL,
        rate="-1%",
        pitch="+0Hz",
        volume="+0%",
        clause_pause_ms=220,
        sentence_pause_ms=450,
        emphasis_level="moderate",
    ),
    DeliveryStyle.SERIOUS: ProsodyProfile(
        style=DeliveryStyle.SERIOUS,
        rate="-4%",
        pitch="-4Hz",
        volume="+1%",
        clause_pause_ms=240,
        sentence_pause_ms=500,
        emphasis_level="strong",
    ),
    DeliveryStyle.DRAMATIC: ProsodyProfile(
        style=DeliveryStyle.DRAMATIC,
        rate="-6%",
        pitch="-5Hz",
        volume="+2%",
        clause_pause_ms=280,
        sentence_pause_ms=600,
        emphasis_level="strong",
    ),
    DeliveryStyle.EMOTIONAL: ProsodyProfile(
        style=DeliveryStyle.EMOTIONAL,
        rate="+1%",
        pitch="+2Hz",
        volume="+0%",
        clause_pause_ms=200,
        sentence_pause_ms=450,
        emphasis_level="moderate",
    ),
    DeliveryStyle.CALM: ProsodyProfile(
        style=DeliveryStyle.CALM,
        rate="-2%",
        pitch="-1Hz",
        volume="-1%",
        clause_pause_ms=220,
        sentence_pause_ms=420,
        emphasis_level="moderate",
    ),
}


class ProsodyController:
    """Manages speech cadence, emotional inflection, and rhythm shaping for native Hindi speech."""

    def __init__(self, default_style: DeliveryStyle = DeliveryStyle.SAMANYA):
        self.default_style = default_style

    def get_profile(self, style: DeliveryStyle) -> ProsodyProfile:
        """Retrieve acoustic profile for a given style."""
        return PROSODY_PROFILES.get(style, PROSODY_PROFILES[self.default_style])

    def infer_style_from_text(self, text: str) -> DeliveryStyle:
        """Infer appropriate delivery style based on sentence semantics, rhythm, and punctuation."""
        t = text.strip().lower()
        is_devanagari = bool(re.search(r"[\u0900-\u097F]", text))

        if is_devanagari:
            # --- 1. Devanagari Pure Native Hindi Style Inference ---
            # Surprise / Shocking Fact (!? or ?!, हैरान, असंभव)
            if "?!" in t or "!?" in t or any(w in t for w in ["हैरान", "असंभव", "चौंकाने"]):
                return DeliveryStyle.AASHCHARYA

            # Questions & Hooks -> Jigyasa (जिज्ञासा)
            if t.endswith("?") or any(t.startswith(w) for w in ["क्या", "कैसे", "क्यों", "कहाँ", "सोचिए"]):
                return DeliveryStyle.JIGYASA

            # Takeaway / Outro / Advice -> Prernadayak (प्रेरणादायक वर्णन)
            if any(w in t for w in ["अगली बार", "याद रखें", "सीख", "ज़रूर याद"]):
                return DeliveryStyle.PRERNADAYAK

            # Exclamations -> Utsah or Gambhir depending on context
            if t.endswith("!"):
                if any(w in t for w in ["टूट", "दबाव", "कुचल", "खतरा", "बिखर"]):
                    return DeliveryStyle.GAMBHIR
                return DeliveryStyle.UTSAH

            # Scientific breakdown, limits & structural collapse -> Gambhir (गंभीर व्याख्या)
            if any(w in t for w in ["हड्डियों", "दबाव", "भारी वज़न", "भार", "अस्थि", "कुचल", "क्षमता"]):
                return DeliveryStyle.GAMBHIR

            # Excitement keywords -> Utsah (उत्साहपूर्ण)
            if any(w in t for w in ["शानदार", "रोमांचक", "ज़बरदस्त", "अद्भुत"]):
                return DeliveryStyle.UTSAH

            # Emotional reflections -> Bhavnatmak (भावनात्मक)
            if any(w in t for w in ["दिल", "एहसास", "महसूस", "दुख", "सच्चाई"]):
                return DeliveryStyle.BHAVNATMAK

            return DeliveryStyle.SAMANYA

        # --- 2. Roman Hindi & English Style Inference (Backward Compatible) ---
        # Surprise (!? or ?!)
        if "?!" in t or "!?" in t or any(w in t for w in ["sochiye agar", "impossible", "hairat"]):
            return DeliveryStyle.SURPRISE

        # Questions & Openers -> Curious
        if t.endswith("?") or any(t.startswith(w) for w in ["kya", "kyu", "kyun", "kaise", "can", "why"]):
            return DeliveryStyle.CURIOUS

        # Exclamations & Surprises -> Excited or Dramatic
        if t.endswith("!"):
            if any(w in t for w in ["crush", "toot", "stress", "mushkil", "fail", "break", "collapse", "fracture"]):
                return DeliveryStyle.DRAMATIC
            return DeliveryStyle.EXCITED

        # Technical & Math Explanations -> Educational
        if any(w in t for w in ["cube", "square", "volume", "weight", "mutaabiq", "law", "physics", "scale", "bones", "proportional"]):
            return DeliveryStyle.EDUCATIONAL

        # Warnings & Gravity -> Serious
        if any(w in t for w in ["haddiyon", "pressure", "neeche", "danger", "compressive"]):
            return DeliveryStyle.SERIOUS

        # Calm explanations
        if any(w in t for w in ["aaram se", "dheere", "shanti"]):
            return DeliveryStyle.CALM

        return DeliveryStyle.CONVERSATIONAL

    def build_ssml(
        self,
        speech_text: str,
        voice_id: str,
        style: Optional[DeliveryStyle] = None,
        emphasis_words: Optional[List[str]] = None,
    ) -> str:
        """Construct well-formed W3C SSML markup with prosody, pauses, and emphasis."""
        active_style = style or self.infer_style_from_text(speech_text)
        profile = self.get_profile(active_style)

        # XML escape text
        escaped = (
            speech_text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("'", "&apos;")
            .replace('"', "&quot;")
        )

        # Inject natural comma clause breaks if supported
        if profile.clause_pause_ms > 0:
            escaped = re.sub(
                r",\s*",
                f", <break time='{profile.clause_pause_ms}ms'/> ",
                escaped,
            )

        # Highlight emphasis words
        if emphasis_words:
            for ew in emphasis_words:
                pattern = re.compile(rf"\b({re.escape(ew)})\b", re.IGNORECASE)
                escaped = pattern.sub(f"<emphasis level='{profile.emphasis_level}'>\\1</emphasis>", escaped)

        ssml = (
            f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='hi-IN'>\n"
            f"  <voice name='{voice_id}'>\n"
            f"    <prosody rate='{profile.rate}' pitch='{profile.pitch}' volume='{profile.volume}'>\n"
            f"      {escaped}\n"
            f"    </prosody>\n"
            f"  </voice>\n"
            f"</speak>"
        )
        return ssml


class EmotionController:
    """Maps scene visual cues and storyboard moods to appropriate voice delivery styles."""

    @classmethod
    def map_scene_to_style(
        cls,
        scene_number: int,
        total_scenes: int,
        scene_narration: str,
        sound_effect_cue: Optional[str] = None,
    ) -> DeliveryStyle:
        """Determine the optimal vocal style for a specific scene in the storyboard."""
        is_devanagari = bool(re.search(r"[\u0900-\u097F]", scene_narration))

        # Scene 1 is always the Hook
        if scene_number == 1:
            return DeliveryStyle.JIGYASA if is_devanagari else DeliveryStyle.CURIOUS

        # Final scene is the Takeaway / Outro
        if scene_number == total_scenes:
            return DeliveryStyle.PRERNADAYAK if is_devanagari else DeliveryStyle.CONVERSATIONAL

        # Middle scenes depend on sound cue or content
        cue = (sound_effect_cue or "").lower()
        if any(w in cue for w in ["crunch", "roar", "drop", "collapse", "bone", "shock"]):
            return DeliveryStyle.GAMBHIR if is_devanagari else DeliveryStyle.DRAMATIC

        # Use semantic inference
        controller = ProsodyController()
        return controller.infer_style_from_text(scene_narration)
