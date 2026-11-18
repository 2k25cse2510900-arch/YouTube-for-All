"""Automated unit and integration test suite for the Hinglish Voice Engine."""

import math
from pathlib import Path
import struct
import tempfile
from typing import List
import wave

import pytest

from src.audio_engine.benchmark import BENCHMARK_CORPUS, VoiceBenchmarkRunner
from src.audio_engine.continuity import AudioContinuityProcessor, AudioMetrics
from src.audio_engine.hinglish_processor import HinglishTextProcessor, ProcessedHinglishResult
from src.audio_engine.models import BoundaryType, TimestampBoundary, VoiceSynthesisResult
from src.audio_engine.pronunciation_dictionary import PronunciationDictionary
from src.audio_engine.prosody import DeliveryStyle, EmotionController, ProsodyController
from src.audio_engine.quality_evaluator import QualityStatus, VoiceQualityChecker, VoiceQualityReport
from src.audio_engine.service import AudioEngine
from src.audio_engine.voice_providers.base import BaseVoiceProvider
from src.audio_engine.voice_providers.edge_tts_provider import EdgeTTSVoiceProvider
from src.audio_engine.voice_providers.elevenlabs_provider import ElevenLabsVoiceProvider
from src.audio_engine.voice_providers.google_tts_provider import GoogleCloudTTSVoiceProvider
from src.audio_engine.voice_providers.mock_voice_provider import MockVoiceProvider
from src.storyboard_generator.models import StoryboardDossier, StoryboardScene, VisualConsistencyProfile


# --- Fixtures ---

@pytest.fixture
def sample_dictionary(tmp_path):
    """Fixture providing a fresh PronunciationDictionary instance."""
    return PronunciationDictionary()


@pytest.fixture
def sample_processor():
    """Fixture providing a configured HinglishTextProcessor."""
    return HinglishTextProcessor()


@pytest.fixture
def sample_storyboard():
    """Fixture providing a multi-scene StoryboardDossier."""
    vc = VisualConsistencyProfile(
        character_name="Titan Scientist",
        facial_features="Sharp analytical eyes",
        hairstyle="Dark neat hair",
        clothing_and_attire="Lab coat",
        color_palette="Navy blue, white",
    )
    scenes = [
        StoryboardScene(
            scene_number=1,
            narration_hinglish="Kya 60-meter lamba Titan sach mein khada ho sakta hai?",
            narration_english_meaning="Can a 60-meter tall Titan really stand?",
            camera_angle="low-angle",
            framing="wide",
            subject_placement="center",
            image_prompt_positive="Giant silhouette",
            suggested_duration_seconds=5.0,
            sound_effect_cue="sfx_wind_howl",
        ),
        StoryboardScene(
            scene_number=2,
            narration_hinglish="Square-Cube Law ke mutaabiq, volume mass 40,000x badh jaata hai.",
            narration_english_meaning="According to Square-Cube Law, volume mass scales 40,000x.",
            camera_angle="eye-level",
            framing="medium",
            subject_placement="center",
            image_prompt_positive="Physics diagrams",
            suggested_duration_seconds=6.0,
            sound_effect_cue="sfx_electric_hum",
        ),
        StoryboardScene(
            scene_number=3,
            narration_hinglish="Is wajan se Titan ek second mein collapse ho jaayega!",
            narration_english_meaning="From this weight, Titan will collapse in one second!",
            camera_angle="high-angle",
            framing="close-up",
            subject_placement="center",
            image_prompt_positive="Collapsing skeleton",
            suggested_duration_seconds=5.0,
            sound_effect_cue="sfx_bone_crunch",
        ),
        StoryboardScene(
            scene_number=4,
            narration_hinglish="Toh अगली baar anime dekho, toh physics ke is rule ko yaad rakhna!",
            narration_english_meaning="So next time you watch anime, remember this rule!",
            camera_angle="eye-level",
            framing="medium",
            subject_placement="center",
            image_prompt_positive="Scientist concluding",
            suggested_duration_seconds=6.0,
        ),
    ]
    return StoryboardDossier(
        storyboard_id="sb_voice_engine_test",
        title="Voice Engine Test Storyboard",
        topic="Scaling Biomechanics",
        target_duration_seconds=24.0,
        pause_budget_seconds=2.0,
        hook="Hook text",
        body="Body text",
        takeaway="Takeaway text",
        visual_consistency=vc,
        scenes=scenes,
        bgm_suggestion={"mood": "Cinematic", "tempo": "Medium"},
    )


def _generate_test_pcm_wav(
    path: Path,
    duration_s: float = 2.0,
    sample_rate: int = 44100,
    amplitude: int = 16000,
    frequency: float = 440.0,
    insert_silence_s: float = 0.0,
    insert_clipping: bool = False,
) -> Path:
    """Helper creating standard 16-bit mono PCM WAV for audio testing."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = int(sample_rate * duration_s)

    samples = []
    for i in range(n_samples):
        t = i / sample_rate
        # Optional silence gap in the middle (0.5s to 0.5s + insert_silence_s)
        if 0.5 <= t < (0.5 + insert_silence_s):
            samples.append(0)
        else:
            val = int(amplitude * math.sin(2.0 * math.pi * frequency * t))
            if insert_clipping and (i % 200 == 0):
                val = 32767
            samples.append(max(-32768, min(32767, val)))

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    return path


# --- 1. Pronunciation Dictionary Tests ---

def test_pronunciation_dictionary_bundled_lookup(sample_dictionary):
    """Verify bundled pronunciation dictionary translates common Hindi words while protecting English terms."""
    # Hindi word lookup
    assert sample_dictionary.lookup("haddiyon") == "हड्डियों"
    assert sample_dictionary.lookup("zinda") == "ज़िंदा"
    assert sample_dictionary.lookup("mutaabiq") == "मुताबिक"

    # Protected English technical terms must return None (do not transliterate to Devanagari)
    assert sample_dictionary.lookup("square-cube") is None
    assert sample_dictionary.lookup("colossal") is None
    assert sample_dictionary.lookup("titan") is None
    assert sample_dictionary.lookup("stress") is None
    assert sample_dictionary.is_english_term("physics") is True


def test_pronunciation_dictionary_custom_registration(tmp_path):
    """Verify runtime registration and persistence of custom terms."""
    p_dict = PronunciationDictionary()
    p_dict.register("senku", "सेनकू")
    assert p_dict.lookup("senku") == "सेनकू"

    p_dict.register_english_term("chlorine")
    assert p_dict.lookup("chlorine") is None
    assert p_dict.is_english_term("chlorine") is True

    # Test JSON export and reload
    export_file = tmp_path / "custom_dict.json"
    p_dict.save_to_json(export_file)
    assert export_file.is_file()

    reloaded = PronunciationDictionary(custom_dict_path=export_file)
    assert reloaded.lookup("senku") == "सेनकू"
    assert reloaded.is_english_term("chlorine") is True


# --- 2. Hinglish Text Processor Tests ---

def test_hinglish_processor_number_and_unit_normalization(sample_processor):
    """Verify number, exponent, and multiplier normalization."""
    raw = "60-meter lamba Titan 40,000x wajan ke saath (34)³ volume badhata hai."
    normalized = sample_processor.normalize_numbers_and_units(raw)

    assert "60 meter" in normalized
    assert "40,000 गुना" in normalized
    assert "34 का cube" in normalized


def test_hinglish_processor_proportionality_math(sample_processor):
    """Verify formula proportionality notation is expanded for natural speech."""
    raw = "Area A ∝ L² aur Volume V ∝ L³ scale hote hain."
    normalized = sample_processor.normalize_numbers_and_units(raw)

    assert "Area proportional to L square" in normalized
    assert "Volume proportional to L cube" in normalized


def test_hinglish_processor_dual_script_transformation(sample_processor):
    """Verify Hindi grammar is transformed into Devanagari while English technical terms are preserved."""
    raw = "Square-Cube Law ke mutaabiq Titan ki haddiyon par stress padega."
    res: ProcessedHinglishResult = sample_processor.process_text(raw)

    # Protected English terms stay in Latin
    assert "Square-Cube" in res.speech_text
    assert "Titan" in res.speech_text
    assert "stress" in res.speech_text

    # Hindi words translated to Devanagari
    assert "मुताबिक" in res.speech_text
    assert "हड्डियों" in res.speech_text
    assert res.word_count > 0


def test_hinglish_processor_boundary_alignment(sample_processor):
    """Verify boundary alignment preserves exact timestamps while mapping back to original script words."""
    orig = "Titan 60-meter lamba hai"
    boundaries = [
        TimestampBoundary(text="Titan", offset_ms=0.0, duration_ms=400.0, boundary_type=BoundaryType.WORD),
        TimestampBoundary(text="60", offset_ms=450.0, duration_ms=300.0, boundary_type=BoundaryType.WORD),
        TimestampBoundary(text="meter", offset_ms=760.0, duration_ms=400.0, boundary_type=BoundaryType.WORD),
        TimestampBoundary(text="lamba", offset_ms=1200.0, duration_ms=500.0, boundary_type=BoundaryType.WORD),
        TimestampBoundary(text="hai", offset_ms=1750.0, duration_ms=250.0, boundary_type=BoundaryType.WORD),
    ]

    aligned = sample_processor.align_boundaries(boundaries, orig)
    assert len(aligned) == 4
    assert aligned[0].text == "Titan"
    assert aligned[1].text == "60-meter"
    assert aligned[1].offset_ms == 450.0
    assert aligned[1].duration_ms == 710.0  # Combined duration of "60" + "meter"
    assert aligned[2].text == "lamba"
    assert aligned[3].text == "hai"


# --- 3. Prosody and Emotion Controller Tests ---

def test_prosody_controller_semantic_inference():
    """Verify semantic style inference selects appropriate delivery style based on sentence features."""
    prosody = ProsodyController()

    # Question -> Curious
    assert prosody.infer_style_from_text("Kya Titan sach mein khada ho sakta hai?") == DeliveryStyle.CURIOUS

    # Dramatic exclamation -> Dramatic
    assert prosody.infer_style_from_text("Ek second mein wajan se collapse ho jaayega!") == DeliveryStyle.DRAMATIC

    # Technical explanation -> Educational
    assert prosody.infer_style_from_text("Square-Cube Law ke mutaabiq volume 40,000x badhta hai.") == DeliveryStyle.EDUCATIONAL

    # Serious warning -> Serious
    assert prosody.infer_style_from_text("Titan ki haddiyon par dangerous pressure padega.") == DeliveryStyle.SERIOUS


def test_prosody_controller_ssml_construction():
    """Verify well-formed W3C SSML construction with prosody rates and pause breaks."""
    prosody = ProsodyController()
    ssml = prosody.build_ssml(
        speech_text="Dhyan se samjho, mass cube rate par badhta hai.",
        voice_id="hi-IN-MadhurNeural",
        style=DeliveryStyle.EDUCATIONAL,
        emphasis_words=["cube rate"],
    )

    assert "<speak" in ssml
    assert "<voice name='hi-IN-MadhurNeural'>" in ssml
    assert "<prosody" in ssml
    assert "<break time=" in ssml
    assert "<emphasis" in ssml


def test_emotion_controller_scene_mapping():
    """Verify EmotionController maps storyboard scenes to appropriate delivery styles."""
    # Scene 1 is Hook -> Curious
    s1 = EmotionController.map_scene_to_style(scene_number=1, total_scenes=4, scene_narration="Opening hook")
    assert s1 == DeliveryStyle.CURIOUS

    # Scene with crunch/collapse cue -> Dramatic
    s3 = EmotionController.map_scene_to_style(
        scene_number=3, total_scenes=4, scene_narration="Middle scene", sound_effect_cue="sfx_bone_crunch"
    )
    assert s3 == DeliveryStyle.DRAMATIC

    # Final scene is Takeaway -> Conversational
    s4 = EmotionController.map_scene_to_style(scene_number=4, total_scenes=4, scene_narration="Final takeaway")
    assert s4 == DeliveryStyle.CONVERSATIONAL


# --- 4. Audio Continuity Processor Tests ---

def test_audio_continuity_analysis_and_metrics(tmp_path):
    """Verify PCM analysis correctly measures duration, peak dBFS, and RMS dBFS."""
    wav_path = tmp_path / "test_clean.wav"
    _generate_test_pcm_wav(wav_path, duration_s=2.0, amplitude=16384)

    continuity = AudioContinuityProcessor()
    metrics: AudioMetrics = continuity.analyze_wav(wav_path)

    assert 1.95 <= metrics.duration_seconds <= 2.05
    assert metrics.channels == 1
    assert metrics.bit_depth == 16
    assert -6.5 <= metrics.peak_dbfs <= -5.5
    assert metrics.clipped_samples == 0
    assert metrics.clipping_ratio == 0.0


def test_audio_continuity_clipping_detection(tmp_path):
    """Verify clipping detection identifies over-amplified samples."""
    clipped_wav = tmp_path / "test_clipped.wav"
    _generate_test_pcm_wav(clipped_wav, duration_s=1.0, amplitude=32767, insert_clipping=True)

    continuity = AudioContinuityProcessor()
    metrics = continuity.analyze_wav(clipped_wav)

    assert metrics.clipped_samples > 0
    assert metrics.clipping_ratio > 0.0


def test_audio_continuity_silence_gap_detection(tmp_path):
    """Verify detection of internal silence gaps."""
    gap_wav = tmp_path / "test_gap.wav"
    # Insert a 0.9s silence gap in the middle
    _generate_test_pcm_wav(gap_wav, duration_s=3.0, amplitude=16000, insert_silence_s=0.9)

    continuity = AudioContinuityProcessor()
    metrics = continuity.analyze_wav(gap_wav)

    assert metrics.max_silence_gap_seconds >= 0.8


def test_audio_continuity_stitching(tmp_path):
    """Verify seamless stitching of multiple WAV segments."""
    seg1 = tmp_path / "seg1.wav"
    seg2 = tmp_path / "seg2.wav"
    _generate_test_pcm_wav(seg1, duration_s=1.0, frequency=440.0)
    _generate_test_pcm_wav(seg2, duration_s=1.0, frequency=880.0)

    stitched_out = tmp_path / "stitched.wav"
    continuity = AudioContinuityProcessor()
    out = continuity.stitch_segments([seg1, seg2], stitched_out, pause_between_ms=50)

    assert out.is_file()
    stitched_metrics = continuity.analyze_wav(out)
    assert stitched_metrics.duration_seconds >= 2.0


def test_audio_continuity_loudness_peak_normalization(tmp_path):
    """Verify peak normalization adjusts amplitude to broadcast target."""
    quiet_wav = tmp_path / "quiet.wav"
    _generate_test_pcm_wav(quiet_wav, duration_s=1.0, amplitude=4000)

    continuity = AudioContinuityProcessor()
    before_metrics = continuity.analyze_wav(quiet_wav)

    norm_wav = tmp_path / "normalized.wav"
    continuity._peak_normalize_pcm(quiet_wav, norm_wav, target_peak_dbfs=-1.5)
    after_metrics = continuity.analyze_wav(norm_wav)

    assert after_metrics.peak_dbfs > before_metrics.peak_dbfs
    assert -2.0 <= after_metrics.peak_dbfs <= -1.0


# --- 5. Voice Quality Checker Tests ---

def test_voice_quality_checker_pass(tmp_path):
    """Verify clean, optimal voice audio passes all quality checks."""
    wav_path = tmp_path / "clean_voice.wav"
    _generate_test_pcm_wav(wav_path, duration_s=5.0, amplitude=8000)

    checker = VoiceQualityChecker()
    # 12 words over 5 seconds = 144 WPM (optimal)
    script = "Yeh ek sample script hai jo normal speech rate ko test karti hai."
    report: VoiceQualityReport = checker.evaluate_audio(wav_path, script)

    assert report.passed is True
    assert report.overall_status in [QualityStatus.PASS, QualityStatus.WARNING]
    assert 130.0 <= report.speech_rate_wpm <= 160.0


def test_voice_quality_checker_excessive_gap_warning(tmp_path):
    """Verify excessive dead air gap triggers quality warning or fail."""
    gap_wav = tmp_path / "gap_voice.wav"
    _generate_test_pcm_wav(gap_wav, duration_s=4.0, amplitude=16000, insert_silence_s=0.9)

    checker = VoiceQualityChecker()
    script = "Sentence one sentence two sentence three sentence four."
    report = checker.evaluate_audio(gap_wav, script)

    gap_checks = [c for c in report.checks if "Internal Pause Continuity" in c.name]
    assert len(gap_checks) == 1
    assert gap_checks[0].status in [QualityStatus.WARNING, QualityStatus.FAIL]


# --- 6. Pluggable Providers & Zero-Cost Guard Tests ---

def test_pluggable_providers_zero_cost_enforcement(tmp_path):
    """Verify paid providers (ElevenLabs, Google Cloud TTS) declare paid status and reject unauthorized calls."""
    # ElevenLabs
    el_provider = ElevenLabsVoiceProvider()
    assert el_provider.is_paid is True
    assert el_provider.provider_name == "elevenlabs"
    with pytest.raises(Exception) as exc1:
        el_provider.synthesize("test", "adam", tmp_path / "el.mp3")
    assert "₹0 budget policy" in str(exc1.value) or "not configured" in str(exc1.value)

    # Google Cloud TTS
    g_provider = GoogleCloudTTSVoiceProvider()
    assert g_provider.is_paid is True
    assert g_provider.provider_name == "google_cloud_tts"
    with pytest.raises(Exception) as exc2:
        g_provider.synthesize("test", "hi-IN-Wavenet-A", tmp_path / "g.mp3")
    assert "₹0 budget policy" in str(exc2.value) or "not configured" in str(exc2.value)


# --- 7. Benchmark Corpus Integrity Test ---

def test_benchmark_corpus_integrity():
    """Verify 30 benchmark items are fully specified with categories and styles."""
    assert len(BENCHMARK_CORPUS) >= 30
    seen_ids = set()

    for item in BENCHMARK_CORPUS:
        assert item.item_id not in seen_ids, f"Duplicate item_id: {item.item_id}"
        seen_ids.add(item.item_id)
        assert len(item.text) > 20
        assert item.category
        assert isinstance(item.delivery_style, DeliveryStyle)
        assert item.notes


# --- 8. AudioEngine Integration Tests ---

def test_audio_engine_scene_by_scene_synthesis(tmp_path, sample_storyboard):
    """Verify AudioEngine synthesizes a storyboard scene-by-scene using MockVoiceProvider."""
    mock_prov = MockVoiceProvider()
    engine = AudioEngine(voice_provider=mock_prov)

    out_file = tmp_path / "scene_by_scene_voice.wav"
    res = engine.synthesize_voiceover(
        storyboard=sample_storyboard,
        output_path=out_file,
        scene_by_scene=True,
    )

    assert out_file.is_file()
    assert res.duration_seconds > 0.0
    assert len(res.boundaries) > 0
    assert res.provider == "mock_voice"

    # Evaluate voice quality
    quality = engine.evaluate_voice_quality(
        audio_path=out_file,
        script_text=" ".join(s.narration_hinglish for s in sample_storyboard.scenes),
        boundaries=res.boundaries,
    )
    assert quality.word_count > 0
    assert quality.passed is True


# --- 9. Language-Aware Indian Hinglish & Regression Word Tests ---

def test_language_aware_indian_hinglish_regression_words(sample_processor, sample_dictionary):
    """Specific regression test for: जबकि, Colossal, Titan, Square-Cube Law, Volume, Weight, Muscles, Physics, Science."""
    # 1. Dictionary Indian phonetic lookups
    assert sample_dictionary.lookup_indian_phonetic("colossal") == "कोलोसल"
    assert sample_dictionary.lookup_indian_phonetic("titan") == "टाइटन"
    assert sample_dictionary.lookup_indian_phonetic("square-cube") == "स्क्वेयर-क्यूब"
    assert sample_dictionary.lookup_indian_phonetic("volume") == "वॉल्यूम"
    assert sample_dictionary.lookup_indian_phonetic("weight") == "वेट"
    assert sample_dictionary.lookup_indian_phonetic("muscles") == "मसल्स"
    assert sample_dictionary.lookup_indian_phonetic("physics") == "फ़िज़िक्स"
    assert sample_dictionary.lookup_indian_phonetic("science") == "साइंस"
    assert sample_dictionary.lookup_hindi_devanagari("jabki") == "जबकि"

    # 2. Processor Indian Hinglish transformation
    text = "जबकि Colossal Giant aur Square-Cube Law ke mutaabiq Volume aur Weight badhne se Muscles fail honge in Physics and Science."
    res = sample_processor.process_indian_hinglish(text)
    assert "जबकि" in res.speech_text
    assert "कोलोसल" in res.speech_text
    assert "टाइटन" in res.speech_text
    assert "स्क्वेयर-क्यूब लॉ" in res.speech_text
    assert "वॉल्यूम" in res.speech_text
    assert "वेट" in res.speech_text
    assert "मसल्स" in res.speech_text
    assert "फ़िज़िक्स" in res.speech_text
    assert "साइंस" in res.speech_text


def test_token_classification(sample_processor):
    """Verify processor distinguishes Devanagari Hindi, Roman Hindi, English loanwords, and technical terms."""
    from src.audio_engine.hinglish_processor import LanguageCategory
    assert sample_processor.classify_token("जबकि") == LanguageCategory.DEVANAGARI_HINDI
    assert sample_processor.classify_token("haddiyon") == LanguageCategory.ROMAN_HINDI
    assert sample_processor.classify_token("Colossal") == LanguageCategory.TECHNICAL_ANIME_TERM
    assert sample_processor.classify_token("Titan") == LanguageCategory.TECHNICAL_ANIME_TERM
    assert sample_processor.classify_token("60-meter") == LanguageCategory.NUMBER_UNIT

