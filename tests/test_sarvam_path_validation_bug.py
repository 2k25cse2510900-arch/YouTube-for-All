"""Regression tests for Sarvam TTS WindowsPath validation bug.

Verifies:
1. VoiceSynthesisResult accepts pathlib.Path / WindowsPath without Pydantic ValidationError.
2. audio_path is properly coerced to a valid non-empty string.
3. SarvamAIVoiceProvider generates a valid VoiceSynthesisResult with string audio_path.
4. Existing MP3 benchmark files in output/audio/benchmarks/candidate_comparisons/sarvam_hindi/
   are preserved intact.
5. Synthesis is never marked FAILED because of path validation.
"""

from datetime import datetime
import json
from pathlib import Path, PureWindowsPath, WindowsPath
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from src.audio_engine.models import VoiceSynthesisResult
from src.audio_engine.voice_providers.sarvam_provider import SarvamAIVoiceProvider


# --- 1. Model Validation Tests ---

def test_voice_synthesis_result_accepts_path_object():
    """Verify VoiceSynthesisResult accepts a pathlib.Path and coerces to str."""
    test_path = Path("output/audio/test_audio.mp3")
    result = VoiceSynthesisResult(
        audio_path=test_path,
        duration_seconds=3.5,
        voice_id="bulbul:v4-flash:shubh_enhi_ads",
        provider="sarvam_ai",
        file_size_bytes=45000,
    )
    assert isinstance(result.audio_path, str)
    assert result.audio_path == str(test_path)
    assert result.duration_seconds == 3.5
    assert result.provider == "sarvam_ai"


def test_voice_synthesis_result_accepts_pure_windows_path():
    """Verify VoiceSynthesisResult accepts PureWindowsPath without ValidationError."""
    win_path = PureWindowsPath(r"C:\workspace\output\audio\sarvam_hindi\sent_01.mp3")
    result = VoiceSynthesisResult(
        audio_path=win_path,
        duration_seconds=2.06,
        voice_id="bulbul:v4-flash:shubh_enhi_ads",
        provider="sarvam_ai",
        file_size_bytes=33024,
    )
    assert isinstance(result.audio_path, str)
    assert result.audio_path == str(win_path)
    assert result.file_size_bytes == 33024


def test_voice_synthesis_result_accepts_plain_string_path():
    """Verify VoiceSynthesisResult maintains backward compatibility with plain string paths."""
    str_path = "output/audio/test_plain.mp3"
    result = VoiceSynthesisResult(
        audio_path=str_path,
        duration_seconds=4.0,
        voice_id="hi-IN-MadhurNeural",
        provider="edge_tts",
    )
    assert isinstance(result.audio_path, str)
    assert result.audio_path == str_path


def test_voice_synthesis_result_rejects_empty_path():
    """Verify VoiceSynthesisResult rejects empty or whitespace paths."""
    with pytest.raises(ValueError):
        VoiceSynthesisResult(
            audio_path="",
            duration_seconds=1.0,
            voice_id="v1",
            provider="test",
        )
    with pytest.raises(ValueError):
        VoiceSynthesisResult(
            audio_path="   ",
            duration_seconds=1.0,
            voice_id="v1",
            provider="test",
        )


# --- 2. Provider Integration & Path Coercion Tests ---

def test_sarvam_provider_synthesize_returns_valid_result(tmp_path):
    """Verify SarvamAIVoiceProvider produces a valid VoiceSynthesisResult with string audio_path."""
    import asyncio
    provider = SarvamAIVoiceProvider(api_key="mock_test_key_12345")
    mock_audio_b64 = "SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjYwLjMuMTAwAAAAAAAAAAAAAAD/"
    out_file = tmp_path / "test_sarvam_out.mp3"

    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value={"audios": [mock_audio_b64]})

    # Context manager mock for aiohttp session.post
    mock_post_ctx = AsyncMock()
    mock_post_ctx.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post_ctx.__aexit__ = AsyncMock(return_value=None)

    with patch("aiohttp.ClientSession.post", return_value=mock_post_ctx):
        result = asyncio.run(provider.synthesize_async(
            text="कॉलॉसल टाइटन साठ मीटर ऊँचा है।",
            output_path=out_file,
            target_language_code="hi-IN",
        ))

    # Must validate and return successfully with string audio_path
    assert isinstance(result, VoiceSynthesisResult)
    assert isinstance(result.audio_path, str)
    assert result.audio_path == str(out_file)
    assert result.provider == "sarvam_ai"
    assert "bulbul" in result.voice_id
    assert out_file.exists()


# --- 3. Existing Audio Files Preservation Tests ---

@pytest.mark.skipif(not Path("output/audio/benchmarks/candidate_comparisons/sarvam_hindi").exists(), reason="Production audio benchmarks excluded from repo")
def test_existing_sarvam_benchmark_files_preserved():
    """Verify that all 18 Sarvam benchmark MP3 files exist and have non-zero size."""
    benchmark_dir = Path("output/audio/benchmarks/candidate_comparisons/sarvam_hindi")
    assert benchmark_dir.exists(), f"Benchmark directory {benchmark_dir} must exist."

    expected_ids = [
        "sent_01_short_statement",
        "sent_02_question_curious",
        "sent_03_dramatic_suspense",
        "sent_04_complex_history_names",
        "sent_05_scientific_scaling",
        "sent_06_sanskrit_technical",
        "sent_07_biomechanical_load",
        "sent_08_emotional_climax",
        "sent_09_action_collapse",
        "sent_10_philosophical_law",
        "sent_11_conversational_signoff",
        "sent_12_conversational_storytelling",
        "sent_13_natural_transition",
        "sent_14_scaling_comparison",
        "sent_15_anatomy_cardio",
        "sent_16_acoustic_heat_steam",
        "sent_17_lore_interrogative",
        "sent_18_thesis_summary",
    ]

    for sent_id in expected_ids:
        file_path = benchmark_dir / f"{sent_id}.mp3"
        assert file_path.exists(), f"File {file_path} must exist."
        file_size = file_path.stat().st_size
        assert file_size > 10000, f"File {file_path} size ({file_size} bytes) must be > 10KB."
