"""Offline Unit Tests for Quality Checker Module.

Covers Scenarios 1-20: Video, audio, caption, and metadata quality validation.
Strictly offline: all FFmpeg and FFprobe calls are mock-tested.
"""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from src.quality_checker.exceptions import QualityGateFailedError
from src.quality_checker.models import (
    CheckSeverity,
    QualityReport,
    QualityStatus,
    QualityThresholds,
)
from src.quality_checker.service import QualityChecker
from src.video_editor.ffmpeg_runner import FFmpegRunner


@pytest.fixture
def mock_ffmpeg_runner():
    """Mock FFmpeg runner providing configurable probe and execution outputs."""
    runner = MagicMock(spec=FFmpegRunner)
    runner.check_ffmpeg_availability.return_value = (True, "ffmpeg version 9.0.2")
    runner.check_ffprobe_availability.return_value = (True, "ffprobe version 9.0.2")

    # Default valid 1080x1920 30fps vertical video probe metadata
    runner.probe_video.return_value = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "r_frame_rate": "30/1",
                "pix_fmt": "yuv420p",
                "duration": "45.000",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "44100",
                "channels": 2,
                "duration": "45.000",
            },
        ],
        "format": {
            "duration": "45.000000",
            "size": "15420000",
        },
    }

    # Default clean execution for blackdetect / silencedetect / volumedetect
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stderr = "max_volume: -6.2 dB\nmean_volume: -22.4 dB"
    runner.run_ffmpeg.return_value = (proc, 0.05)

    return runner


@pytest.fixture
def dummy_video_file(tmp_path):
    """Create a dummy MP4 file on disk."""
    v_file = tmp_path / "valid_render_production.mp4"
    v_file.write_bytes(b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00valid_video_data")
    return v_file


# ---------------------------------------------------------------------------
# Video Validation Tests (Scenarios 1 - 7, 17 - 19)
# ---------------------------------------------------------------------------

def test_valid_vertical_video_passes(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 1: Confirm valid 1080x1920 vertical video passes all video checks."""
    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.video_checker.run_checks(dummy_video_file)

    failures = [r for r in results if r.status == QualityStatus.FAIL]
    assert len(failures) == 0, f"Expected 0 failures, got: {failures}"
    assert any(r.check_name == "video_resolution_and_aspect_ratio" and r.status == QualityStatus.PASS for r in results)
    assert any(r.check_name == "video_framerate" and r.status == QualityStatus.PASS for r in results)


def test_missing_video_fails(tmp_path, mock_ffmpeg_runner):
    """Scenario 2: Missing video file produces CRITICAL FAIL."""
    checker = QualityChecker(runner=mock_ffmpeg_runner)
    non_existent = tmp_path / "non_existent_video.mp4"
    results = checker.video_checker.run_checks(non_existent)

    assert len(results) == 1
    assert results[0].check_name == "video_file_exists"
    assert results[0].status == QualityStatus.FAIL
    assert results[0].severity == CheckSeverity.CRITICAL


def test_empty_video_file_fails(tmp_path, mock_ffmpeg_runner):
    """Scenario 3: Zero-byte video file produces CRITICAL FAIL."""
    empty_file = tmp_path / "empty_video.mp4"
    empty_file.write_bytes(b"")

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.video_checker.run_checks(empty_file)

    assert any(r.check_name == "video_file_non_empty" and r.status == QualityStatus.FAIL for r in results)


def test_wrong_resolution_fails(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 4: Horizontal (1920x1080) resolution fails vertical Shorts requirement."""
    mock_ffmpeg_runner.probe_video.return_value["streams"][0]["width"] = 1920
    mock_ffmpeg_runner.probe_video.return_value["streams"][0]["height"] = 1080

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.video_checker.run_checks(dummy_video_file)

    res_check = next(r for r in results if r.check_name == "video_resolution_and_aspect_ratio")
    assert res_check.status == QualityStatus.FAIL
    assert "1920x1080" in res_check.message


def test_wrong_aspect_ratio_fails(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 5: 1:1 square (1080x1080) resolution fails 9:16 Shorts requirement."""
    mock_ffmpeg_runner.probe_video.return_value["streams"][0]["width"] = 1080
    mock_ffmpeg_runner.probe_video.return_value["streams"][0]["height"] = 1080

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.video_checker.run_checks(dummy_video_file)

    res_check = next(r for r in results if r.check_name == "video_resolution_and_aspect_ratio")
    assert res_check.status == QualityStatus.FAIL


def test_invalid_duration_exceeds_60s_fails(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 6: Duration > 60s violates YouTube Shorts ceiling."""
    mock_ffmpeg_runner.probe_video.return_value["format"]["duration"] = "65.500"

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.video_checker.run_checks(dummy_video_file)

    dur_check = next(r for r in results if r.check_name == "video_duration_valid")
    assert dur_check.status == QualityStatus.FAIL
    assert "exceeds YouTube Shorts limit" in dur_check.message


def test_missing_video_stream_fails(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 7: Media container with zero video streams fails."""
    mock_ffmpeg_runner.probe_video.return_value["streams"] = [
        {"codec_type": "audio", "codec_name": "aac"}
    ]

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.video_checker.run_checks(dummy_video_file)

    assert any(r.check_name == "video_stream_exists" and r.status == QualityStatus.FAIL for r in results)


def test_mock_asset_rejection(tmp_path, mock_ffmpeg_runner):
    """Scenario 17: Mock or synthetic assets produce CRITICAL FAIL."""
    mock_video = tmp_path / "mock_senku_scene.mp4"
    mock_video.write_bytes(b"dummy")

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.video_checker.run_checks(mock_video, is_mock_asset=True)

    mock_check = next(r for r in results if r.check_name == "video_not_mock_asset")
    assert mock_check.status == QualityStatus.FAIL
    assert "Mock assets must never be published" in mock_check.message


def test_black_frame_warning(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 18: Black frame detection generates warning or fail depending on duration."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    # Simulate 3 seconds of black screen
    proc.stderr = "black_start:10.00 black_end:13.00 black_duration:3.00"
    mock_ffmpeg_runner.run_ffmpeg.return_value = (proc, 0.1)

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.video_checker.run_checks(dummy_video_file)

    black_check = next(r for r in results if r.check_name == "video_black_screen_detection")
    assert black_check.status == QualityStatus.WARNING
    assert "Detected black frames for 3.0s" in black_check.message


def test_frozen_scene_warning(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 19: Frozen scene detection generates WARNING."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stderr = "freezedetect: freeze_start: 5.20\nfreezedetect: freeze_start: 18.40"
    mock_ffmpeg_runner.run_ffmpeg.return_value = (proc, 0.1)

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.video_checker.run_checks(dummy_video_file)

    freeze_check = next(r for r in results if r.check_name == "video_frozen_scene_detection")
    assert freeze_check.status == QualityStatus.WARNING
    assert "Detected potentially static/frozen scene" in freeze_check.message


# ---------------------------------------------------------------------------
# Audio Validation Tests (Scenarios 8 - 10)
# ---------------------------------------------------------------------------

def test_missing_audio_stream_fails(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 8: Missing audio stream in media container produces CRITICAL FAIL."""
    mock_ffmpeg_runner.probe_video.return_value["streams"] = [
        {"codec_type": "video", "codec_name": "h264"}
    ]

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.audio_checker.run_checks(dummy_video_file)

    assert any(r.check_name == "audio_stream_exists" and r.status == QualityStatus.FAIL for r in results)


def test_silent_audio_warning(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 9: Prolonged silence triggers audio warning."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stderr = "silence_start: 4.5\nsilence_start: 12.0"
    mock_ffmpeg_runner.run_ffmpeg.return_value = (proc, 0.1)

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.audio_checker.run_checks(dummy_video_file)

    silence_check = next(r for r in results if r.check_name == "audio_excessive_silence_detection")
    assert silence_check.status == QualityStatus.WARNING


def test_audio_clipping_warning(dummy_video_file, mock_ffmpeg_runner):
    """Scenario 10: Peak volume at 0.0 dB (digital clipping) produces WARNING."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stderr = "max_volume: 0.0 dB\nmean_volume: -12.0 dB"
    mock_ffmpeg_runner.run_ffmpeg.return_value = (proc, 0.1)

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.audio_checker.run_checks(dummy_video_file)

    clip_check = next(r for r in results if r.check_name == "audio_clipping_detection")
    assert clip_check.status == QualityStatus.WARNING
    assert "Potential digital clipping" in clip_check.message


# ---------------------------------------------------------------------------
# Caption Validation Tests (Scenarios 11 - 14)
# ---------------------------------------------------------------------------

def test_invalid_captions_timing_fails(tmp_path):
    """Scenario 11: End time <= start time produces CRITICAL FAIL."""
    srt_file = tmp_path / "corrupted_timing.srt"
    srt_file.write_text(
        "1\n00:00:05,000 --> 00:00:03,000\nBackward in time\n",
        encoding="utf-8",
    )

    checker = QualityChecker()
    results = checker.caption_checker.run_checks(srt_file)

    timing_check = next(r for r in results if r.check_name == "captions_valid_timing")
    assert timing_check.status == QualityStatus.FAIL


def test_empty_captions_fails(tmp_path):
    """Scenario 12: Empty caption file produces CRITICAL FAIL."""
    empty_srt = tmp_path / "empty.srt"
    empty_srt.write_text("   \n\n", encoding="utf-8")

    checker = QualityChecker()
    results = checker.caption_checker.run_checks(empty_srt)

    empty_check = next(r for r in results if r.check_name == "captions_non_empty")
    assert empty_check.status == QualityStatus.FAIL


def test_invalid_timestamps_syntax(tmp_path):
    """Scenario 13: Malformed timestamps fail parsing gracefully with WARNING."""
    bad_srt = tmp_path / "bad_syntax.srt"
    bad_srt.write_text("1\nINVALID_TIME --> WRONG_TIME\nHello World\n", encoding="utf-8")

    checker = QualityChecker()
    results = checker.caption_checker.run_checks(bad_srt)

    assert any(r.check_name == "captions_event_parsing" and r.status == QualityStatus.WARNING for r in results)


def test_hindi_devanagari_encoding_preserved(tmp_path):
    """Scenario 14: Devanagari Hindi text verified intact and valid UTF-8."""
    hindi_srt = tmp_path / "hindi_lesson.srt"
    hindi_srt.write_text(
        "1\n00:00:00,000 --> 00:00:03,500\nक्या आप जानते हैं कि सेन्कू ने कैसे समय गिना?\n",
        encoding="utf-8",
    )

    checker = QualityChecker()
    results = checker.caption_checker.run_checks(hindi_srt)

    utf8_check = next(r for r in results if r.check_name == "captions_utf8_encoding")
    assert utf8_check.status == QualityStatus.PASS

    devanagari_check = next(r for r in results if r.check_name == "captions_hindi_devanagari_preserved")
    assert devanagari_check.status == QualityStatus.PASS


# ---------------------------------------------------------------------------
# Metadata Validation Tests (Scenarios 15 - 16)
# ---------------------------------------------------------------------------

def test_missing_title_fails():
    """Scenario 15: Missing or whitespace title produces CRITICAL FAIL."""
    checker = QualityChecker()
    results = checker.metadata_checker.run_checks(
        title="",
        description="Valid description",
        made_for_kids=False,
    )
    assert any(r.check_name == "metadata_title_present" and r.status == QualityStatus.FAIL for r in results)


def test_invalid_metadata_constraints():
    """Scenario 16: Title > 100 chars, invalid category ID, and placeholder text produce FAIL."""
    checker = QualityChecker()
    results = checker.metadata_checker.run_checks(
        title="This is a TODO placeholder title that is far too long and contains invalid markers for YouTube Shorts publishing",
        description="Lorem Ipsum dummy text",
        category_id="9999",  # Invalid ID
        made_for_kids=None,  # Not specified
    )

    failures = [r for r in results if r.status == QualityStatus.FAIL]
    failure_names = [f.check_name for f in failures]
    assert "metadata_title_no_placeholder" in failure_names
    assert "metadata_category_id" in failure_names
    assert "metadata_made_for_kids_specified" in failure_names


# ---------------------------------------------------------------------------
# Service Orchestration & Quality Report Tests (Scenario 20)
# ---------------------------------------------------------------------------

def test_quality_report_serialization_and_gate_enforcement(tmp_path, dummy_video_file, mock_ffmpeg_runner):
    """Scenario 20: Full quality check orchestration, JSON report generation, and gate enforcement."""
    checker = QualityChecker(runner=mock_ffmpeg_runner)
    report_json = tmp_path / "quality_report.json"
    valid_srt = tmp_path / "valid_captions.srt"
    valid_srt.write_text("1\n00:00:01,000 --> 00:00:03,000\nScience is ten billion percent fun!\n", encoding="utf-8")

    # 1. Clean report passes
    report = checker.check_production(
        production_id="prod_qa_test_01",
        video_path=dummy_video_file,
        caption_path=valid_srt,
        title="Senku Time Perception Science",
        description="Factual science behind Dr. Stone #Shorts",
        tags=["#Shorts", "Science", "Anime"],
        category_id="28",
        made_for_kids=False,
        output_report_path=report_json,
    )

    assert report.production_id == "prod_qa_test_01"
    assert report.is_upload_eligible is True
    assert report.total_failures == 0
    assert report_json.exists()

    # Markdown summary check
    md_summary = report.to_summary_markdown()
    assert "# Quality Check Report: `prod_qa_test_01`" in md_summary
    assert "Upload Eligible:** YES" in md_summary

    # Gate assertion succeeds
    checker.assert_upload_eligible(report)

    # 2. Defective report raises QualityGateFailedError
    failing_report = checker.check_production(
        production_id="prod_qa_failing_02",
        video_path=dummy_video_file,
        caption_path=valid_srt,
        title="",  # Empty title -> FAIL
        description="Test",
        made_for_kids=False,
    )

    assert failing_report.is_upload_eligible is False
    with pytest.raises(QualityGateFailedError, match="Quality gate rejected upload"):
        checker.assert_upload_eligible(failing_report)


def test_complete_audio_silence_fails_upload_eligibility(dummy_video_file, mock_ffmpeg_runner):
    """Confirm completely silent audio (-91 dB) produces FAIL and blocks upload eligibility."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stderr = "max_volume: -91.0 dB\nmean_volume: -91.0 dB"
    mock_ffmpeg_runner.run_ffmpeg.return_value = (proc, 0.05)

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.audio_checker.run_checks(dummy_video_file)

    silence_check = next(r for r in results if r.check_name == "audio_silence_level")
    assert silence_check.status == QualityStatus.FAIL
    assert "silent" in silence_check.message


def test_normal_speech_pauses_pass(dummy_video_file, mock_ffmpeg_runner):
    """Confirm pauses <= 3.5s pass silence check."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.returncode = 0
    proc.stderr = (
        "silence_start: 5.0\nsilence_end: 7.0 | silence_duration: 2.0\n"
        "max_volume: -6.0 dB\nmean_volume: -20.0 dB"
    )
    mock_ffmpeg_runner.run_ffmpeg.return_value = (proc, 0.05)

    checker = QualityChecker(runner=mock_ffmpeg_runner)
    results = checker.audio_checker.run_checks(dummy_video_file)

    silence_check = next(r for r in results if r.check_name == "audio_excessive_silence_detection")
    assert silence_check.status == QualityStatus.PASS


def test_missing_caption_fails_by_default():
    """Missing caption without explicit override produces FAIL."""
    checker = QualityChecker()
    results = checker.caption_checker.run_checks(caption_path=None)

    missing_check = next(r for r in results if r.check_name == "captions_presence")
    assert missing_check.status == QualityStatus.FAIL


def test_missing_caption_with_override_warns():
    """Missing caption with allow_no_captions=True produces WARNING instead of FAIL."""
    checker = QualityChecker()
    results = checker.caption_checker.run_checks(caption_path=None, allow_no_captions=True)

    missing_check = next(r for r in results if r.check_name == "captions_presence")
    assert missing_check.status == QualityStatus.WARNING


def test_not_checked_status_blocks_upload_eligibility(tmp_path, dummy_video_file, mock_ffmpeg_runner):
    """Skipping video checks records NOT_CHECKED and blocks upload eligibility."""
    checker = QualityChecker(runner=mock_ffmpeg_runner)
    valid_srt = tmp_path / "valid.srt"
    valid_srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

    report = checker.check_production(
        production_id="prod_partial_check",
        video_path=dummy_video_file,
        caption_path=valid_srt,
        title="Valid Title",
        description="Valid Desc",
        category_id="28",
        made_for_kids=False,
        skip_video_checks=True,
    )

    assert report.total_not_checked > 0
    assert report.is_upload_eligible is False
    assert report.overall_status == QualityStatus.NOT_CHECKED
    assert report.overall_status != QualityStatus.PASS

    # Incomplete inspections must be rejected by assert_upload_eligible
    with pytest.raises(QualityGateFailedError, match="incomplete inspection"):
        checker.assert_upload_eligible(report)
