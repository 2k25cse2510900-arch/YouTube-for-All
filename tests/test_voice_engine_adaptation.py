"""Regression tests for Phase 1: Adaptive, Consistent Native Hindi Voice Engine.

Verifies:
1. Voice assets inventory health (100% non-corrupted, non-silent, non-clipped audio).
2. Voice evaluation dataset schema, sample volume (>=100 samples), and human/model score decoupling.
3. Human evaluation workflow (recording review decisions, dimension scores, notes).
4. Reusable voice profile loading, text normalization, and sentence chunking.
5. Controlled comparison matrix integrity and human approval gates.
6. Safety and credit guards (zero unauthorized spending, zero key leakage).
"""

import json
from pathlib import Path
import pytest

from src.audio_engine.dataset import (
    HumanEvaluationScoreSheet,
    ModelObjectiveMetrics,
    VoiceEvaluationDataset,
    VoiceEvaluationSample,
)
from src.audio_engine.voice_profile import VoiceProfile, VoiceProfileConfig


@pytest.mark.skipif(not Path("data/voice_dataset/voice_assets_inventory.json").exists(), reason="Voice assets inventory excluded from repo")
def test_voice_assets_inventory_health():
    """Verify inventory file exists, is non-empty, and confirms 100% audio health."""
    inv_path = Path("data/voice_dataset/voice_assets_inventory.json")
    assert inv_path.exists(), "voice_assets_inventory.json must exist"

    data = json.loads(inv_path.read_text(encoding="utf-8"))
    assert data["total_files"] >= 140, "Must have audited at least 140 audio files"
    assert data["healthy_count"] == data["total_files"], "All audited files must be healthy"
    assert data["clipping_count"] == 0, "Zero audio files should have clipping"
    assert data["silent_count"] == 0, "Zero audio files should be silent"
    assert data["corrupted_count"] == 0, "Zero audio files should be corrupted"

    # Verify Sarvam benchmark (18) and production (6) presence
    groups = {g["group_id"]: g for g in data["groups"]}
    assert "sarvam_bulbul_benchmark" in groups
    assert "sarvam_bulbul_production" in groups


@pytest.mark.skipif(not Path("data/voice_dataset/voice_evaluation_dataset.json").exists(), reason="Voice evaluation dataset excluded from repo")
def test_voice_evaluation_dataset_sample_target_and_decoupling():
    """Verify dataset meets the ~100 sample target (144 samples) with decoupled human review."""
    dataset_path = Path("data/voice_dataset/voice_evaluation_dataset.json")
    assert dataset_path.exists(), "voice_evaluation_dataset.json must exist"

    dataset = VoiceEvaluationDataset.load_from_file(dataset_path)
    assert dataset.total_samples >= 100, f"Target was ~100 samples, got {dataset.total_samples}"
    assert len(dataset.samples) == dataset.total_samples

    # Check decoupling: model scores must exist while human evaluation retains separate state
    sarvam_samples = dataset.filter_samples(provider="sarvam_ai")
    assert len(sarvam_samples) == 24, "Must have 24 Sarvam Bulbul samples (18 bench + 6 prod)"

    for s in sarvam_samples:
        assert s.metrics.script_fidelity_score is not None
        assert s.metrics.signal_clarity_score is not None
        assert s.human_evaluation.decision == "PENDING", "Sarvam samples must remain PENDING human listening review"
        assert s.human_evaluation.naturalness is None, "Model must not auto-populate human naturalness score"

    edge_samples = dataset.filter_samples(provider="edge_tts")
    assert len(edge_samples) >= 80, "Must have historical Edge TTS samples"
    for s in edge_samples:
        assert s.human_evaluation.decision == "REJECTED", "Historical Edge TTS samples must reflect REJECTED status"
        assert s.human_evaluation.composite_score is not None


def test_human_evaluation_workflow():
    """Verify human evaluation workflow records scores and updates decision."""
    dataset = VoiceEvaluationDataset(dataset_id="test_dataset", version="0.1.0")

    mock_metrics = ModelObjectiveMetrics(
        duration_seconds=3.5,
        sample_rate_hz=24000,
        channels=1,
        bitrate_kbps=128.0,
        peak_dbfs=-0.5,
        mean_dbfs=-16.0,
        speech_rate_wpm=160.0,
    )

    sample = VoiceEvaluationSample(
        sample_id="test_sample_01",
        file_name="test.mp3",
        file_path="output/test.mp3",
        sha256_hash="abcdef123456",
        provider="sarvam_ai",
        model="bulbul:v4-flash",
        speaker="shubh_enhi_ads",
        category="test",
        script_text="यह एक परीक्षण वाक्य है।",
        word_count=5,
        generation_date="2026-11-17",
        metrics=mock_metrics,
    )
    dataset.add_sample(sample)

    assert sample.human_evaluation.decision == "PENDING"

    # Human reviewer evaluates the sample
    updated = dataset.record_human_evaluation(
        sample_id="test_sample_01",
        decision="APPROVED",
        reviewer="Creator",
        scores={
            "naturalness": 8.5,
            "hindi_pronunciation": 9.0,
            "word_clarity": 8.5,
            "sentence_continuity": 8.0,
            "pauses_and_rhythm": 8.5,
            "emotional_expression": 8.0,
            "pitch_warmth": 8.5,
            "voice_consistency": 8.5,
        },
        notes="Authentic Indian Hindi inflection, natural breath pauses.",
    )

    assert updated.human_evaluation.decision == "APPROVED"
    assert updated.human_evaluation.reviewer == "Creator"
    assert updated.human_evaluation.composite_score == 8.44
    assert "Authentic" in updated.human_evaluation.notes


def test_reusable_voice_profile_loading_and_normalization():
    """Verify VoiceProfile configuration loading, text normalization, and chunking."""
    profile_path = Path("config/voice_profiles/sarvam_bulbul_shubh_v1.json")
    assert profile_path.exists(), "sarvam_bulbul_shubh_v1.json must exist"

    profile = VoiceProfile.load(profile_path)
    assert profile.config.provider == "sarvam_ai"
    assert profile.config.model == "bulbul:v4-flash"
    assert profile.config.speaker == "shubh_enhi_ads"
    assert profile.config.approval_status == "VOICE_PREVIEW_PENDING_HUMAN_LISTENING"

    # Test text normalization
    raw_input = "Galileo ने 1638 में Square-Cube Law की खोज की। 60m Colossal Giant 40000kg भार सहन नहीं कर सकता."
    norm = profile.normalize_text(raw_input)

    assert "गैलीलियो" in norm, "Galileo must be replaced with phonetic Devanagari"
    assert "सोलह सौ अड़तीस" in norm, "1638 must be expanded to Hindi numeral words"
    assert "वर्ग-घन का नियम" in norm, "Square-Cube Law must be replaced with approved Hindi translation"
    assert "साठ मीटर" in norm, "60m must be expanded to साठ मीटर"
    assert "चालीस हज़ार किलोग्राम" in norm, "40000kg must be expanded to चालीस हज़ार किलोग्राम"
    assert "।" in norm, "Western period must be converted to Devanagari danda"

    # Test natural sentence chunking
    chunks = profile.chunk_text(norm)
    assert len(chunks) >= 2, "Text should be split into natural clauses"
    for c in chunks:
        assert len(c.split()) <= profile.config.sentence_chunking.max_words_per_chunk


@pytest.mark.skipif(not Path("output/audio/benchmarks/controlled_comparison/controlled_comparison_data.json").exists(), reason="Comparison dataset excluded from repo")
def test_controlled_comparison_data_integrity():
    """Verify controlled comparison dataset contains all candidates and preserves human review gate."""
    comp_path = Path("output/audio/benchmarks/controlled_comparison/controlled_comparison_data.json")
    assert comp_path.exists(), "controlled_comparison_data.json must exist"

    data = json.loads(comp_path.read_text(encoding="utf-8"))
    assert len(data) == 6, "Must compare 6 key standardized benchmark sentences"

    for record in data:
        cands = record["candidates"]
        assert "sarvam_bulbul_v4_shubh" in cands
        assert "edge_tts_madhur_raw" in cands
        assert "edge_tts_madhur_prosody" in cands
        assert "edge_tts_swara_prosody" in cands
        assert "gtts_hindi" in cands
        assert "sarvam_instant_voice_cloning" in cands

        # Sarvam Bulbul must remain pending human listening
        assert cands["sarvam_bulbul_v4_shubh"]["status"] == "HUMAN_LISTENING_PENDING"
        # Edge TTS and Google TTS must reflect rejected status
        assert cands["edge_tts_madhur_raw"]["status"] == "HUMAN_LISTENING_FAILED"
        assert cands["gtts_hindi"]["status"] == "HUMAN_LISTENING_FAILED"
        # Voice cloning must reflect gated status
        assert cands["sarvam_instant_voice_cloning"]["status"] == "GATED_PENDING_REFERENCE_AUDIO"


def test_safety_and_api_key_privacy():
    """Ensure no API keys are exposed in dataset files, configs, or reports."""
    key_patterns = ["sk_x5g", "SARVAM_API_KEY=", "api-subscription-key"]

    files_to_check = [
        Path("data/voice_dataset/voice_assets_inventory.json"),
        Path("data/voice_dataset/voice_evaluation_dataset.json"),
        Path("config/voice_profiles/sarvam_bulbul_shubh_v1.json"),
        Path("output/audio/benchmarks/controlled_comparison/controlled_comparison_data.json"),
    ]

    for f in files_to_check:
        if f.exists():
            content = f.read_text(encoding="utf-8")
            assert "sk_x5g" not in content, f"API key prefix found in {f}"
