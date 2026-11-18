"""Comprehensive automated test suite for the Pure Native Hindi Human Voice Engine."""

import json
from pathlib import Path
import re
import pytest

from src.audio_engine.benchmark import NATIVE_HINDI_BENCHMARK_CORPUS, VoiceBenchmarkRunner
from src.audio_engine.continuity import AudioContinuityProcessor
from src.audio_engine.models import BoundaryType, TimestampBoundary, VoiceSynthesisResult
from src.audio_engine.native_hindi_processor import NativeHindiTextProcessor, ProcessedHindiResult
from src.audio_engine.prosody import DeliveryStyle, EmotionController, PROSODY_PROFILES, ProsodyController
from src.audio_engine.service import AudioEngine
from src.audio_engine.voice_providers.edge_tts_provider import EdgeTTSVoiceProvider
from src.audio_engine.voice_providers.mock_voice_provider import MockVoiceProvider


class TestNativeHindiLexicon:
    """Tests for native Hindi dictionary, translations, numerals, and discourse markers."""

    def test_native_hindi_dictionary_loading(self):
        dict_path = Path("src/audio_engine/data/native_hindi_dict.json")
        assert dict_path.exists(), f"Dictionary file missing at {dict_path}"

        with open(dict_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "scientific_concepts_translation" in data
        assert "hinglish_loanwords_to_hindi" in data
        assert "hindi_numerals_map" in data
        assert "measurement_units" in data
        assert "discourse_markers" in data

        concepts = data["scientific_concepts_translation"]
        assert concepts["square-cube law"] == "वर्ग-घन का नियम"
        assert concepts["volume"] == "आयतन"
        assert concepts["weight"] == "भार"
        assert concepts["muscles"] == "मांसपेशियाँ"
        assert concepts["physics"] == "भौतिक विज्ञान"
        assert concepts["science"] == "विज्ञान"
        assert concepts["colossal giant"] == "विशालकाय टाइटन"
        assert concepts["bones"] == "हड्डियाँ"
        assert concepts["cross-sectional area"] == "अनुप्रस्थ काट का क्षेत्रफल"


class TestNativeHindiTextProcessor:
    """Tests for text normalization, number-to-Hindi expansion, and pure Hindi speech processing."""

    @pytest.fixture
    def processor(self):
        return NativeHindiTextProcessor()

    def test_number_to_hindi_single_and_double_digits(self, processor):
        assert processor.number_to_hindi(0) == "शून्य"
        assert processor.number_to_hindi(1) == "एक"
        assert processor.number_to_hindi(2) == "दो"
        assert processor.number_to_hindi(8) == "आठ"
        assert processor.number_to_hindi(10) == "दस"
        assert processor.number_to_hindi(60) == "साठ"
        assert processor.number_to_hindi(70) == "सत्तर"
        assert processor.number_to_hindi(25) == "पच्चीस"

    def test_number_to_hindi_thousands_and_multipliers(self, processor):
        assert processor.number_to_hindi(100) == "सौ"
        assert processor.number_to_hindi(1000) == "एक हज़ार"
        assert processor.number_to_hindi(40000) == "चालीस हज़ार"

    def test_normalize_multipliers(self, processor):
        text = "उसका वज़न 8x और 40,000x बढ़ गया।"
        normalized = processor.normalize_numbers_and_units(text)
        assert "आठ गुना" in normalized
        assert "चालीस हज़ार गुना" in normalized

    def test_normalize_units(self, processor):
        t1 = "साठ मीटर ऊँचा 60-meter टाइटन"
        norm1 = processor.normalize_numbers_and_units(t1)
        assert "साठ मीटर" in norm1
        assert "60-meter" not in norm1

        t2 = "70-kg का इंसान"
        norm2 = processor.normalize_numbers_and_units(t2)
        assert "सत्तर किलोग्राम" in norm2

    def test_translate_concepts_english_to_pure_hindi(self, processor):
        text = "Square-Cube Law ke niyam ke hisab se Volume aur Weight exponentially badhta hai."
        res = processor.process_text(text)
        assert "वर्ग-घन का नियम" in res.speech_text
        assert "आयतन" in res.speech_text
        assert "भार" in res.speech_text
        assert len(res.concepts_translated) >= 3

    def test_translate_hinglish_loanwords_to_pure_hindi(self, processor):
        text = "स्क्वेयर-क्यूब लॉ के अनुसार वॉल्यूम और वेट बहुत अधिक बढ़ जाता है, जिससे मसल्स टूट जाती हैं।"
        res = processor.process_text(text)
        assert "वर्ग-घन का नियम" in res.speech_text
        assert "आयतन" in res.speech_text
        assert "भार" in res.speech_text
        assert "मांसपेशियाँ" in res.speech_text
        assert "स्क्वेयर-क्यूब लॉ" not in res.speech_text
        assert "वॉल्यूम" not in res.speech_text

    def test_punctuation_normalization(self, processor):
        text = "यह एक वाक्य है. क्या यह दूसरा वाक्य है? बिल्कुल!"
        res = processor.process_text(text)
        assert "। " in res.speech_text or res.speech_text.endswith("।") or "!" in res.speech_text
        assert "?" in res.speech_text
        assert "!" in res.speech_text

    def test_zero_latin_in_pure_hindi_sentence(self, processor):
        text = "क्या 60-meter लंबा Colossal Giant सच में ज़िंदा रह सकता है?"
        res = processor.process_text(text)
        assert not res.contains_latin
        assert not re.search(r"[a-zA-Z]", res.speech_text)
        assert "साठ मीटर" in res.speech_text
        assert "विशालकाय टाइटन" in res.speech_text


class TestNativeHindiProsody:
    """Tests for 7 Native Hindi expressive delivery styles and acoustic profiles."""

    def test_seven_native_styles_defined(self):
        expected_styles = [
            DeliveryStyle.SAMANYA,
            DeliveryStyle.UTSAH,
            DeliveryStyle.JIGYASA,
            DeliveryStyle.AASHCHARYA,
            DeliveryStyle.GAMBHIR,
            DeliveryStyle.BHAVNATMAK,
            DeliveryStyle.PRERNADAYAK,
        ]
        for style in expected_styles:
            assert style in PROSODY_PROFILES
            prof = PROSODY_PROFILES[style]
            assert prof.clause_pause_ms > 0
            assert prof.sentence_pause_ms > 0
            assert prof.rate is not None

    def test_style_inference_jigyasa(self):
        controller = ProsodyController()
        s1 = "क्या साठ मीटर ऊँचा विशालकाय टाइटन सच में ज़िंदा रह सकता है?"
        assert controller.infer_style_from_text(s1) == DeliveryStyle.JIGYASA

        s2 = "सोचिए ज़रा, अगर आपका कद दस गुना बढ़ा दिया जाए?"
        assert controller.infer_style_from_text(s2) == DeliveryStyle.JIGYASA

    def test_style_inference_gambhir(self):
        controller = ProsodyController()
        s1 = "इंसानी हड्डियों का ढाँचा इस भारी दबाव के नीचे कुचल जाएगा।"
        assert controller.infer_style_from_text(s1) == DeliveryStyle.GAMBHIR

    def test_style_inference_prernadayak(self):
        controller = ProsodyController()
        s1 = "तो अगली बार जब भी आप एनिमे देखें, तो इस नियम को ज़रूर याद रखें!"
        assert controller.infer_style_from_text(s1) == DeliveryStyle.PRERNADAYAK

    def test_style_inference_aashcharya(self):
        controller = ProsodyController()
        s1 = "यह तो बिल्कुल असंभव और चौंकाने वाला तथ्य है?!"
        assert controller.infer_style_from_text(s1) == DeliveryStyle.AASHCHARYA

    def test_emotion_controller_scene_mapping(self):
        # Scene 1 is Hook -> Jigyasa
        assert EmotionController.map_scene_to_style(1, 5, "क्या टाइटन ज़िंदा रह सकता है?") == DeliveryStyle.JIGYASA
        # Final scene is Outro -> Prernadayak
        assert EmotionController.map_scene_to_style(5, 5, "अगली बार याद रखें!") == DeliveryStyle.PRERNADAYAK
        # Middle scene with collapse -> Gambhir
        assert EmotionController.map_scene_to_style(3, 5, "हड्डियाँ टूट जाएँगी", "bone crunch") == DeliveryStyle.GAMBHIR


class TestNativeHindiBenchmarkSuite:
    """Tests for 30-Sentence Pure Native Hindi benchmark corpus and generated assets."""

    def test_corpus_size_and_categories(self):
        assert len(NATIVE_HINDI_BENCHMARK_CORPUS) == 30
        categories = set(item.category for item in NATIVE_HINDI_BENCHMARK_CORPUS)
        assert len(categories) == 7
        assert "जिज्ञासा & हुक" in categories
        assert "वर्ग-घन का नियम व वैज्ञानिक सिद्धांत" in categories
        assert "ज्यामिति, आयतन व भार वृद्धि" in categories
        assert "शारीरिक व अस्थि संरचना सीमाएँ" in categories
        assert "गंभीर वास्तविकता व असंभवता" in categories
        assert "सहज वार्तालाप व संबंधबोधक" in categories
        assert "प्रेरणादायक निष्कर्ष व समापन" in categories

    def test_all_benchmark_sentences_pure_devanagari(self):
        for item in NATIVE_HINDI_BENCHMARK_CORPUS:
            assert not re.search(r"[a-zA-Z]", item.text), f"Item '{item.item_id}' contains Latin characters: {item.text}"

    @pytest.mark.skipif(
        not Path("assets/audio/benchmark_hindi").exists(),
        reason="Benchmark audio files excluded from open-source repository",
    )
    def test_all_30_wav_files_exist_on_disk(self):
        benchmark_dir = Path("assets/audio/benchmark_hindi")
        assert benchmark_dir.exists()
        for item in NATIVE_HINDI_BENCHMARK_CORPUS:
            wav_file = benchmark_dir / f"{item.item_id}.wav"
            assert wav_file.exists(), f"Benchmark WAV file missing: {wav_file}"
            assert wav_file.stat().st_size > 50000, f"Benchmark WAV file is unusually small: {wav_file}"

    @pytest.mark.skipif(
        not Path("docs/reports/native_hindi_voice_benchmark_report.md").exists(),
        reason="Benchmark reports excluded from open-source repository",
    )
    def test_benchmark_report_exists_and_all_pass(self):
        rep_path = Path("docs/reports/native_hindi_voice_benchmark_report.md")
        assert rep_path.exists()
        content = rep_path.read_text(encoding="utf-8")
        assert "30/30 (100.0%)" in content
        assert "0 clipped samples" in content
        assert "hi-IN-MadhurNeural" in content
        assert "वर्ग-घन का नियम" in content


class TestAudioEngineNativeHindiIntegration:
    """Tests for AudioEngine and EdgeTTSVoiceProvider integration with Native Hindi Processor."""

    def test_edge_tts_provider_uses_native_hindi_processor_by_default(self):
        provider = EdgeTTSVoiceProvider()
        assert isinstance(provider.processor, NativeHindiTextProcessor)
        assert provider.provider_name == "edge_tts"
        assert provider.is_paid is False

    def test_audio_engine_initializes_native_hindi_processor(self):
        engine = AudioEngine()
        assert hasattr(engine, "native_hindi_processor")
        assert isinstance(engine.native_hindi_processor, NativeHindiTextProcessor)


class TestStrictVoiceQualityGate:
    """Tests for the multi-stage Voice Quality Gate and human-listening status transitions."""

    def test_unreviewed_voice_defaults_to_human_listening_review_pending(self, tmp_path):
        from src.audio_engine.quality_evaluator import VoiceLifecycleStatus, VoiceQualityChecker, QualityStatus
        checker = VoiceQualityChecker()

        # Use an existing benchmark WAV file
        wav_path = Path("assets/audio/voice_evaluation/candidate_a_madhur_prosody/sent_01_curious_q1.wav")
        if not wav_path.exists():
            pytest.skip("Benchmark WAV file not found on disk")

        report = checker.evaluate_audio(
            audio_path=wav_path,
            script_text="क्या आपने कभी सोचा है कि चींटी इतनी ऊँचाई से गिरने के बाद भी ज़िंदा कैसे बच जाती है?",
        )

        assert report.overall_status == QualityStatus.PASS
        assert report.passed is True
        # Automated tests pass, but production readiness is strictly False until human review
        assert report.lifecycle_status == VoiceLifecycleStatus.HUMAN_LISTENING_REVIEW_PENDING
        assert report.is_production_ready is False
        assert "Human listening review pending" in report.summary

    def test_failed_human_listening_review_blocks_production_readiness(self):
        from src.audio_engine.quality_evaluator import VoiceLifecycleStatus, VoiceQualityChecker
        checker = VoiceQualityChecker()

        wav_path = Path("assets/audio/voice_evaluation/candidate_a_madhur_prosody/sent_01_curious_q1.wav")
        if not wav_path.exists():
            pytest.skip("Benchmark WAV file not found on disk")

        report = checker.evaluate_audio(
            audio_path=wav_path,
            script_text="क्या आपने कभी सोचा है कि चींटी इतनी ऊँचाई से गिरने के बाद भी ज़िंदा कैसे बच जाती है?",
            human_score=5.4,
            human_approved=False,
            human_notes="Voice sounds synthetic and lacks natural conversational warmth.",
        )

        assert report.lifecycle_status == VoiceLifecycleStatus.HUMAN_LISTENING_FAILED
        assert report.is_production_ready is False
        assert report.human_listening_score == 5.4
        assert "FAILED" in report.summary

    def test_approved_human_listening_review_grants_production_ready(self):
        from src.audio_engine.quality_evaluator import VoiceLifecycleStatus, VoiceQualityChecker
        checker = VoiceQualityChecker()

        wav_path = Path("assets/audio/voice_evaluation/candidate_a_madhur_prosody/sent_01_curious_q1.wav")
        if not wav_path.exists():
            pytest.skip("Benchmark WAV file not found on disk")

        report = checker.evaluate_audio(
            audio_path=wav_path,
            script_text="क्या आपने कभी सोचा है कि चींटी इतनी ऊँचाई से गिरने के बाद भी ज़िंदा कैसे बच जाती है?",
            human_score=9.2,
            human_approved=True,
            human_notes="Authentic native Hindi speaker, perfectly natural conversational rhythm.",
        )

        assert report.lifecycle_status == VoiceLifecycleStatus.PRODUCTION_READY
        assert report.is_production_ready is True
        assert report.human_listening_score == 9.2
        assert "PRODUCTION READY" in report.summary

    def test_record_human_listening_evaluation_method(self):
        from src.audio_engine.quality_evaluator import VoiceLifecycleStatus, VoiceQualityChecker
        checker = VoiceQualityChecker()

        wav_path = Path("assets/audio/voice_evaluation/candidate_a_madhur_prosody/sent_01_curious_q1.wav")
        if not wav_path.exists():
            pytest.skip("Benchmark WAV file not found on disk")

        report = checker.evaluate_audio(
            audio_path=wav_path,
            script_text="क्या आपने कभी सोचा है कि चींटी इतनी ऊँचाई से गिरने के बाद भी ज़िंदा कैसे बच जाती है?",
        )
        assert report.lifecycle_status == VoiceLifecycleStatus.HUMAN_LISTENING_REVIEW_PENDING

        # Record human rejection
        updated = checker.record_human_listening_evaluation(
            report=report,
            score=5.2,
            approved=False,
            notes="Robotic cadence and artificial emotional flattening."
        )
        assert updated.lifecycle_status == VoiceLifecycleStatus.HUMAN_LISTENING_FAILED
        assert updated.is_production_ready is False

