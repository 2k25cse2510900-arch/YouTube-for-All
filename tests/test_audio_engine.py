"""Automated test suite for Audio Engine, Voice Providers, BGM Licensing, and Caption Generation."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest
import wave

from src.audio_engine.bgm_library import BGMLibraryManager
from src.audio_engine.exceptions import (
    AudioEngineError,
    AudioLicenseVerificationError,
    AudioMixingError,
    VoiceSynthesisError,
)
from src.audio_engine.mixer import AudioMixer
from src.audio_engine.models import (
    BGMTrackMetadata,
    BoundaryType,
    SFXCue,
    TimestampBoundary,
    VoiceSynthesisResult,
)
from src.audio_engine.service import AudioEngine
from src.audio_engine.voice_providers.edge_tts_provider import EdgeTTSVoiceProvider
from src.audio_engine.voice_providers.mock_voice_provider import MockVoiceProvider
from src.caption_generator.models import CaptionFormat, CaptionStyle
from src.caption_generator.service import SubtitleGenerator
from src.image_engine.eligibility import ProductionEligibilityValidator
from src.image_engine.exceptions import MockAssetProductionBlockedError
from src.image_engine.models import GeneratedImageMetadata, SceneImageStatus, StoryboardImageManifest
from src.storage_manager.models import ProductionAssetType
from src.storage_manager.service import StorageManager
from src.storyboard_generator.models import (
    CameraMovement,
    StoryboardDossier,
    StoryboardScene,
    VisualConsistencyProfile,
)


@pytest.fixture
def sample_storyboard():
    """Sample StoryboardDossier fixture with Hinglish narration and SFX cues."""
    vc = VisualConsistencyProfile(
        character_name="Senku Ishigami",
        facial_features="Sharp crimson eyes",
        hairstyle="Spiky green-to-white gradient hair",
        clothing_and_attire="Science tunic",
        color_palette="Emerald green, stone grey",
    )
    scenes = [
        StoryboardScene(
            scene_number=1,
            narration_hinglish="Kya aapko lagta hai ki Senku 3,700 saal tak patthar mein jaag sakta tha?",
            narration_english_meaning="Do you think Senku could stay awake in stone for 3,700 years?",
            camera_angle="eye-level",
            framing="medium-close-up",
            subject_placement="center",
            image_prompt_positive="Senku stone cracking",
            suggested_duration_seconds=4.0,
            camera_movement=CameraMovement.SLOW_ZOOM_IN,
            sound_effect_cue="sfx_stone_crack",
        ),
        StoryboardScene(
            scene_number=2,
            narration_hinglish="Real science kehti hai human brain ko continuous metabolic glucose chahiye.",
            narration_english_meaning="Real science says the brain needs continuous metabolic glucose.",
            camera_angle="high-angle",
            framing="medium-shot",
            subject_placement="center",
            image_prompt_positive="Brain MRI synaptic pulses",
            suggested_duration_seconds=16.0,
            camera_movement=CameraMovement.STATIC_DRIFT,
            sound_effect_cue="sfx_electric_hum",
        ),
    ]
    return StoryboardDossier(
        storyboard_id="sb_audio_test_senku",
        title="Senku Consciousness Science",
        topic="Time Perception in Stasis",
        target_duration_seconds=22.0,
        pause_budget_seconds=2.0,
        hook="Hook text",
        body="Body text",
        takeaway="Takeaway text",
        visual_consistency=vc,
        scenes=scenes,
        bgm_suggestion={"mood": "Suspense", "tempo": "Medium"},
    )


# --- 1. Voice Provider Tests ---

def test_mock_voice_provider_offline_generation(tmp_path):
    """Verify MockVoiceProvider generates a valid standard 16-bit PCM WAV file without network."""
    provider = MockVoiceProvider()
    out_file = tmp_path / "mock_speech.wav"

    sample_text = "Namaste doston! Dr. Stone ka science sach mein adbhut hai."
    result = provider.synthesize(
        text=sample_text,
        voice_id="mock_hi_voice",
        output_path=out_file,
    )

    assert out_file.exists()
    assert result.duration_seconds > 0.0
    assert result.cost_usd == 0.0
    assert result.provider == "mock_voice"
    assert len(result.boundaries) >= 1

    # Verify WAV header
    with wave.open(str(out_file), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2  # 16-bit
        assert wf.getframerate() == 44100


@pytest.mark.integration
def test_edge_tts_provider_live_hinglish_synthesis(tmp_path):
    """Verify EdgeTTSVoiceProvider synthesizes sample Hindi/Hinglish speech and extracts actual timestamps.

    Live API test: ONLY run explicitly with `pytest -m integration`.
    """
    provider = EdgeTTSVoiceProvider()
    out_file = tmp_path / "edge_speech.mp3"

    sample_text = "Namaste doston! Dr. Stone ka science sach mein adbhut hai."
    voice = "hi-IN-MadhurNeural"

    result = provider.synthesize(
        text=sample_text,
        voice_id=voice,
        output_path=out_file,
    )

    assert out_file.exists()
    assert result.file_size_bytes > 0
    assert result.cost_usd == 0.0
    assert result.provider == "edge_tts"
    assert result.voice_id == voice

    # Verify actual timestamps were extracted
    assert len(result.boundaries) >= 1
    for b in result.boundaries:
        assert b.duration_ms > 0.0
        assert b.end_seconds >= b.start_seconds
        assert b.text != ""


def test_edge_tts_empty_text_raises_error(tmp_path):
    """Verify EdgeTTSVoiceProvider raises VoiceSynthesisError on empty text."""
    provider = EdgeTTSVoiceProvider()
    with pytest.raises(VoiceSynthesisError) as exc:
        provider.synthesize("", "hi-IN-MadhurNeural", tmp_path / "empty.mp3")
    assert "empty text" in str(exc.value)


# --- 2. BGM & SFX Licensing Tests ---

def test_bgm_library_verified_youtube_audio_tracks(tmp_path):
    """Verify YouTube Audio Library tracks are registered with license and attribution status."""
    manager = BGMLibraryManager(bgm_dir=tmp_path / "bgm", sfx_dir=tmp_path / "sfx")
    catalog = manager.list_catalog()

    yt_tracks = [t for t in catalog if t.source == "YouTube Audio Library"]
    assert len(yt_tracks) >= 3
    for track in yt_tracks:
        assert track.source == "YouTube Audio Library"
        assert "Attribution Not Required" in track.license
        assert track.attribution_required is False
        assert track.title != ""
        assert track.artist != ""


def test_bgm_library_rejects_closed_freepd(tmp_path):
    """Verify BGMLibraryManager strictly rejects FreePD tracks per requirements."""
    manager = BGMLibraryManager(bgm_dir=tmp_path / "bgm", sfx_dir=tmp_path / "sfx")
    invalid_track = BGMTrackMetadata(
        track_id="invalid_freepd_01",
        title="Old Track",
        artist="Unknown",
        source="FreePD.com",  # Closed source
        license="Public Domain",
        file_path="old.mp3",
    )
    with pytest.raises(AudioLicenseVerificationError) as exc:
        manager.register_bgm_track(invalid_track)
    assert "FreePD is closed" in str(exc.value)


def test_bgm_library_get_track_for_mood(tmp_path):
    """Verify mood-based BGM selection returns appropriate track when active verified track exists."""
    manager = BGMLibraryManager(bgm_dir=tmp_path / "bgm", sfx_dir=tmp_path / "sfx")
    # Catalog entries disabled due to duplicate physical file remediation; register active verified track
    manager.register_bgm_track(BGMTrackMetadata(
        track_id="yt_bgm_test_suspense",
        title="Test Suspense Pulse",
        artist="YouTube Creator Studio",
        source="YouTube Audio Library",
        license="YouTube Audio Library License - Attribution Not Required",
        file_path=str(tmp_path / "bgm" / "test_suspense.mp3"),
        mood="Suspense",
        status="ACTIVE",
        is_verified=True,
    ))
    suspense_track = manager.get_track_for_mood("Suspense")
    assert suspense_track is not None
    assert suspense_track.mood == "Suspense"

    # When querying mood with no active tracks, returns None (voiceover-only mode)
    manager_empty = BGMLibraryManager(bgm_dir=tmp_path / "empty_bgm", sfx_dir=tmp_path / "sfx")
    assert manager_empty.get_track_for_mood("UnknownMood") is None


# --- 3. Audio Mixer & Ducking Tests ---

def test_audio_mixer_ducking_and_sfx(tmp_path):
    """Verify AudioMixer mixes voiceover, ducked BGM, and SFX cues into valid WAV."""
    mixer = AudioMixer()

    # Generate test voiceover WAV
    voice_wav = tmp_path / "voice.wav"
    out_mixed_wav = tmp_path / "mixed.wav"

    mock_voice = MockVoiceProvider()
    mock_voice.synthesize("Test voiceover narration sentence.", "mock_hi", voice_wav)

    bgm_track = BGMTrackMetadata(
        track_id="test_bgm",
        title="Test BGM",
        artist="Test Artist",
        file_path="test_bgm.mp3",
    )
    sfx_cues = [SFXCue(cue_name="sfx_stone_crack", start_time_seconds=0.5, volume=0.7)]

    result = mixer.mix_wav_audio(
        voiceover_wav_path=voice_wav,
        output_wav_path=out_mixed_wav,
        bgm_track=bgm_track,
        sfx_cues=sfx_cues,
        bgm_ducked_volume=0.15,
        voice_volume=1.0,
        allow_synthetic_fallback=True,
    )

    assert out_mixed_wav.exists()
    assert result.duration_seconds > 0.0
    assert result.sfx_count == 1
    assert result.cost_usd == 0.0
    assert result.is_synthetic_mix is True

    # Verify output audio parameters
    with wave.open(str(out_mixed_wav), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 44100


def test_audio_mixer_strictly_blocks_missing_bgm_in_production(tmp_path):
    """Verify AudioMixer hard-blocks synthetic sine fallback in production mode (allow_synthetic_fallback=False)."""
    mixer = AudioMixer()
    voice_wav = tmp_path / "voice.wav"
    out_mixed = tmp_path / "mixed.wav"

    mock_voice = MockVoiceProvider()
    mock_voice.synthesize("Test narration for production check.", "mock_hi", voice_wav)

    missing_bgm = BGMTrackMetadata(
        track_id="missing_bgm",
        title="Missing BGM",
        artist="Unknown",
        file_path="nonexistent_audio.mp3",
    )
    assert not missing_bgm.is_file_on_disk

    with pytest.raises(AudioMixingError, match="PRODUCTION AUDIO BLOCKED: BGM audio file.*does not exist on disk"):
        mixer.mix_wav_audio(
            voiceover_wav_path=voice_wav,
            output_wav_path=out_mixed,
            bgm_track=missing_bgm,
            allow_synthetic_fallback=False,
        )


def test_audio_mixer_strictly_blocks_disabled_or_unverified_bgm(tmp_path):
    """Verify AudioMixer hard-blocks disabled or unverified BGM tracks from entering production audio."""
    mixer = AudioMixer()
    voice_wav = tmp_path / "voice.wav"
    out_mixed = tmp_path / "mixed.wav"

    mock_voice = MockVoiceProvider()
    mock_voice.synthesize("Test narration.", "mock_hi", voice_wav)

    # 1. Disabled track
    disabled_bgm = BGMTrackMetadata(
        track_id="yt_bgm_suspense_revelation_01",
        title="Space Station",
        artist="Jeremy Blake",
        file_path="space_station.mp3",
        status="DISABLED",
        is_verified=False,
    )
    with pytest.raises(AudioMixingError, match="PRODUCTION AUDIO BLOCKED: BGM track '.*' is 'DISABLED'"):
        mixer.mix_wav_audio(
            voiceover_wav_path=voice_wav,
            output_wav_path=out_mixed,
            bgm_track=disabled_bgm,
        )

    # 2. Unverified track
    unverified_bgm = BGMTrackMetadata(
        track_id="cc_bgm_airplane_mode_josh_woodward",
        title="Airplane Mode",
        artist="Josh Woodward",
        file_path="airplane_mode.mp3",
        status="UNVERIFIED",
        is_verified=False,
    )
    with pytest.raises(AudioMixingError, match="PRODUCTION AUDIO BLOCKED: BGM track '.*' is 'UNVERIFIED'"):
        mixer.mix_wav_audio(
            voiceover_wav_path=voice_wav,
            output_wav_path=out_mixed,
            bgm_track=unverified_bgm,
        )


def test_audio_mixer_with_real_wav_on_disk(tmp_path):
    """Verify AudioMixer successfully mixes actual on-disk WAV file without synthetic fallback."""
    import struct
    mixer = AudioMixer()

    voice_wav = tmp_path / "voice.wav"
    mock_voice = MockVoiceProvider()
    mock_voice.synthesize("Narration sentence for mixing test.", "mock_hi", voice_wav)

    bgm_wav = tmp_path / "real_bgm.wav"
    with wave.open(str(bgm_wav), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        samples = [int(500 * (i % 50)) for i in range(44100)]
        wf.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    bgm_track = BGMTrackMetadata(
        track_id="real_bgm",
        title="Real Licensed BGM",
        artist="Test Artist",
        file_path=str(bgm_wav),
    )
    assert bgm_track.is_file_on_disk

    out_mixed = tmp_path / "mixed_real.wav"
    result = mixer.mix_wav_audio(
        voiceover_wav_path=voice_wav,
        output_wav_path=out_mixed,
        bgm_track=bgm_track,
        allow_synthetic_fallback=False,
    )

    assert out_mixed.exists()
    assert result.is_synthetic_mix is False
    assert result.bgm_track_id == "real_bgm"


def test_ffmpeg_ducking_filter_syntax():
    """Verify FFmpeg ducking filtergraph string is formatted correctly."""
    mixer = AudioMixer()
    filter_str = mixer.generate_ffmpeg_ducking_filter(
        voiceover_input_index=0,
        bgm_input_index=1,
        bgm_ducked_volume=0.15,
        voiceover_volume=1.0,
    )
    assert "[0:a]volume=1.0[voice]" in filter_str
    assert "[1:a]volume=0.15[bgm]" in filter_str
    assert "amix=inputs=2:duration=first" in filter_str


# --- 4. Subtitle and Caption Generator Tests ---

def test_caption_generator_srt_export(tmp_path):
    """Verify SubtitleGenerator generates compliant SubRip (.srt) using actual timestamps."""
    generator = SubtitleGenerator()
    boundaries = [
        TimestampBoundary(text="Namaste doston!", offset_ms=100.0, duration_ms=1987.0, boundary_type=BoundaryType.SENTENCE),
        TimestampBoundary(text="Dr. Stone ka science sach hai.", offset_ms=2100.0, duration_ms=3500.0, boundary_type=BoundaryType.SENTENCE),
    ]

    srt_path = tmp_path / "captions.srt"
    items = generator.build_caption_items(boundaries)
    generator.export_srt(items, srt_path)

    assert srt_path.exists()
    content = srt_path.read_text(encoding="utf-8")

    assert "1" in content
    assert "00:00:00,100 --> 00:00:02,087" in content
    assert "Namaste doston!" in content
    assert "2" in content
    assert "00:00:02,100 --> 00:00:05,600" in content
    assert "Dr. Stone ka science sach hai." in content


def test_caption_generator_ass_vertical_styling(tmp_path):
    """Verify SubtitleGenerator generates valid 9:16 vertical ASS subtitles with safe margins."""
    generator = SubtitleGenerator()
    boundaries = [
        TimestampBoundary(text="Namaste doston!", offset_ms=100.0, duration_ms=1987.0),
    ]

    ass_path = tmp_path / "captions.ass"
    items = generator.build_caption_items(boundaries)
    generator.export_ass(items, ass_path)

    assert ass_path.exists()
    content = ass_path.read_text(encoding="utf-8")

    # Verify vertical 9:16 layout resolution
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content

    # Verify safe margin above Shorts description
    assert "ShortsDefault" in content
    assert "Dialogue: 0,0:00:00.10,0:00:02.09,ShortsDefault,,0,0,0,,Namaste doston!" in content


def test_caption_generator_export_both(tmp_path):
    """Verify export_both creates both .srt and .ass files."""
    generator = SubtitleGenerator()
    boundaries = [
        TimestampBoundary(text="Line 1", offset_ms=0.0, duration_ms=2000.0),
    ]
    base = tmp_path / "test_subs"
    srt_p, ass_p = generator.export_both(boundaries, base)

    assert srt_p.exists() and srt_p.suffix == ".srt"
    assert ass_p.exists() and ass_p.suffix == ".ass"


# --- 5. Integrated AudioEngine Service Tests ---

def test_audio_engine_orchestration_with_mock_provider(sample_storyboard, tmp_path):
    """Verify AudioEngine orchestrates voice synthesis and audio mixing with MockVoiceProvider."""
    isolated_bgm = BGMLibraryManager(bgm_dir=tmp_path / "bgm", sfx_dir=tmp_path / "sfx")
    # Register active track for synthetic fallback testing
    isolated_bgm.register_bgm_track(BGMTrackMetadata(
        track_id="yt_bgm_test_active",
        title="Test Active BGM",
        artist="YouTube Creator Studio",
        source="YouTube Audio Library",
        license="YouTube Audio Library License - Attribution Not Required",
        file_path=str(tmp_path / "bgm" / "non_existent.mp3"),
        mood="Suspense",
        status="ACTIVE",
        is_verified=True,
    ))
    engine = AudioEngine(voice_provider=MockVoiceProvider(), bgm_manager=isolated_bgm)

    voice_wav = tmp_path / "storyboard_voice.wav"
    mixed_wav = tmp_path / "storyboard_final_audio.wav"

    # 1. Synthesize voiceover
    voice_res = engine.synthesize_voiceover(sample_storyboard, voice_wav)
    assert voice_wav.exists()
    assert voice_res.duration_seconds > 0.0
    assert voice_res.is_mock_asset is True

    # 2. Mix with licensed BGM and SFX (explicit test fallback enabled)
    mix_res = engine.mix_storyboard_audio(voice_wav, sample_storyboard, mixed_wav, allow_synthetic_fallback=True)
    assert mixed_wav.exists()
    assert mix_res.duration_seconds > 0.0
    assert mix_res.sfx_count == 2  # 2 SFX cues in sample_storyboard
    assert mix_res.cost_usd == 0.0
    assert mix_res.is_synthetic_mix is True

    # 3. Test voiceover-only mixing without BGM
    voiceover_only_bgm = BGMLibraryManager(bgm_dir=tmp_path / "empty_bgm", sfx_dir=tmp_path / "sfx")
    vo_engine = AudioEngine(voice_provider=MockVoiceProvider(), bgm_manager=voiceover_only_bgm)
    vo_mixed_wav = tmp_path / "vo_only_mixed.wav"
    vo_mix_res = vo_engine.mix_storyboard_audio(voice_wav, sample_storyboard, vo_mixed_wav, allow_synthetic_fallback=False)
    assert vo_mixed_wav.exists()
    assert vo_mix_res.bgm_track_id is None
    assert vo_mix_res.is_synthetic_mix is False


# --- 6. Mock Audio Quarantine & Eligibility Gate Tests ---

def test_mock_audio_quarantine_in_eligibility_validator(sample_storyboard):
    """Verify that Mock assets are strictly barred from video production."""
    # 1. Mock voice result must be rejected
    mock_voice = VoiceSynthesisResult(
        audio_path="test_mock.wav",
        duration_seconds=15.0,
        voice_id="mock_hi",
        provider="MockVoiceProvider",
        cost_usd=0.0,
        is_mock_asset=True,
    )
    with pytest.raises(MockAssetProductionBlockedError, match="VIDEO PRODUCTION BLOCKED: Voice synthesis asset is a MOCK asset"):
        ProductionEligibilityValidator.validate_audio_for_production(mock_voice)

    # 2. Real voice result must be accepted
    real_voice = VoiceSynthesisResult(
        audio_path="test_real.wav",
        duration_seconds=15.0,
        voice_id="hi-IN-MadhurNeural",
        provider="EdgeTTSVoiceProvider",
        cost_usd=0.0,
        is_mock_asset=False,
    )
    ProductionEligibilityValidator.validate_audio_for_production(real_voice)

    # 3. In video production validation, mock voice raises MockAssetProductionBlockedError
    manifest = StoryboardImageManifest(
        storyboard_id=sample_storyboard.storyboard_id,
        total_scenes=len(sample_storyboard.scenes),
        has_mock_assets=False,
        images=[
            GeneratedImageMetadata(
                scene_number=s.scene_number,
                image_path=f"img_{s.scene_number}.png",
                provider="test_provider",
                prompt_used="test prompt",
                is_mock_asset=False,
                status=SceneImageStatus.APPROVED,
                reviewer_notes="Approved",
            )
            for s in sample_storyboard.scenes
        ],
    )
    with pytest.raises(MockAssetProductionBlockedError, match="Voice synthesis asset is a MOCK asset"):
        ProductionEligibilityValidator.validate_for_video_production(
            storyboard=sample_storyboard,
            manifest=manifest,
            voice_result=mock_voice,
        )


# --- 7. Empty & Invalid Timestamp Protection Tests ---

def test_subtitle_generator_rejects_empty_and_invalid_boundaries(tmp_path):
    """Verify SubtitleGenerator never outputs empty files and safely rejects invalid boundaries."""
    generator = SubtitleGenerator()

    # Empty boundaries list
    with pytest.raises(AudioEngineError, match="No timestamp boundaries provided"):
        generator.build_caption_items([])

    # Negative duration / end before start
    with pytest.raises(AudioEngineError, match="Invalid timestamp boundary: end time"):
        generator.build_caption_items([
            TimestampBoundary.model_construct(text="Invalid timing", offset_ms=3000.0, duration_ms=-500.0)
        ])

    # Empty text boundaries
    with pytest.raises(AudioEngineError, match="All timestamp boundaries had empty text"):
        generator.build_caption_items([
            TimestampBoundary(text="   ", offset_ms=0.0, duration_ms=1000.0)
        ])

    # Empty export guards
    srt_p = tmp_path / "empty.srt"
    with pytest.raises(AudioEngineError, match="Cannot export empty subtitle file"):
        generator.export_srt([], srt_p)

    ass_p = tmp_path / "empty.ass"
    with pytest.raises(AudioEngineError, match="Cannot export empty subtitle file"):
        generator.export_ass([], ass_p)

    # Overlapping boundaries clamped safely without faking word timings
    overlapping = [
        TimestampBoundary(text="First phrase", offset_ms=0.0, duration_ms=2000.0),
        TimestampBoundary(text="Second phrase", offset_ms=1500.0, duration_ms=1500.0),  # starts before first ends
    ]
    items = generator.build_caption_items(overlapping)
    assert len(items) == 2
    assert items[0].end_seconds == 2.0
    assert items[1].start_seconds == 2.0  # Clamped to previous end
    assert items[1].end_seconds == 3.0


def test_subtitle_generator_skips_fully_nested_boundaries():
    """Verify SubtitleGenerator safely skips fully nested/enclosed boundaries to prevent zero-duration cues."""
    generator = SubtitleGenerator()
    boundaries = [
        TimestampBoundary(text="Enclosing primary sentence", offset_ms=0.0, duration_ms=3000.0),  # 0.0s to 3.0s
        TimestampBoundary(text="Nested inner clause", offset_ms=1000.0, duration_ms=1000.0),       # 1.0s to 2.0s (nested!)
        TimestampBoundary(text="Following valid sentence", offset_ms=3200.0, duration_ms=1800.0),  # 3.2s to 5.0s
    ]

    items = generator.build_caption_items(boundaries)
    assert len(items) == 2
    assert items[0].text == "Enclosing primary sentence"
    assert items[0].start_seconds == 0.0
    assert items[0].end_seconds == 3.0

    assert items[1].text == "Following valid sentence"
    assert items[1].start_seconds == 3.2
    assert items[1].end_seconds == 5.0


def test_subtitle_generator_skips_zero_and_sub_centisecond_durations(tmp_path):
    """Verify SubtitleGenerator skips zero-duration and sub-centisecond intervals that round to identical timestamps."""
    generator = SubtitleGenerator()
    boundaries = [
        TimestampBoundary(text="Zero duration line", offset_ms=500.0, duration_ms=0.0),
        TimestampBoundary(text="Sub-centisecond line", offset_ms=1000.0, duration_ms=4.0),  # 1.000s to 1.004s (rounds to 1.00s in ASS)
        TimestampBoundary(text="Valid speech line", offset_ms=2000.0, duration_ms=1500.0),  # 2.0s to 3.5s
    ]

    items = generator.build_caption_items(boundaries)
    assert len(items) == 1
    assert items[0].text == "Valid speech line"
    assert items[0].start_seconds == 2.0
    assert items[0].end_seconds == 3.5

    # Export to SRT and ASS
    srt_p = tmp_path / "valid.srt"
    ass_p = tmp_path / "valid.ass"
    generator.export_srt(items, srt_p)
    generator.export_ass(items, ass_p)

    srt_content = srt_p.read_text(encoding="utf-8")
    assert "00:00:02,000 --> 00:00:03,500" in srt_content
    assert "Valid speech line" in srt_content

    ass_content = ass_p.read_text(encoding="utf-8")
    assert "Dialogue: 0,0:00:02.00,0:00:03.50,ShortsDefault,,0,0,0,,Valid speech line" in ass_content


def test_export_srt_and_ass_filter_zero_duration_events(tmp_path):
    """Verify export_srt and export_ass reject or skip events whose start and end match identically."""
    from src.caption_generator.models import CaptionItem
    generator = SubtitleGenerator()

    # Create an artificial item with identical start and end
    zero_item = CaptionItem(index=1, start_seconds=2.000, end_seconds=2.000, text="Flash text")

    srt_p = tmp_path / "flash.srt"
    with pytest.raises(AudioEngineError, match="No valid positive-duration caption items"):
        generator.export_srt([zero_item], srt_p)

    ass_p = tmp_path / "flash.ass"
    with pytest.raises(AudioEngineError, match="No valid positive-duration caption items"):
        generator.export_ass([zero_item], ass_p)


# --- 8. Audio and Caption StorageManager Integration Tests ---

def test_audio_and_captions_storage_manager_registration(sample_storyboard, tmp_path):
    """Verify AudioEngine and SubtitleGenerator correctly register assets in StorageManager."""
    prod_dir = tmp_path / "output" / "productions"
    manifest_dir = tmp_path / "data" / "processed" / "storage"
    sm = StorageManager(base_productions_dir=prod_dir, manifest_dir=manifest_dir)

    prod_id = "prod_test_audio_01"
    pkg = sm.create_production_package(storyboard_id=sample_storyboard.storyboard_id, production_id=prod_id)

    engine = AudioEngine(voice_provider=MockVoiceProvider(), storage_manager=sm)
    voice_res, voice_asset = engine.synthesize_and_register_voiceover(sample_storyboard, prod_id)

    assert Path(voice_asset.file_path).exists()
    assert voice_asset.asset_type == ProductionAssetType.VOICEOVER_AUDIO
    assert voice_asset.is_mock_asset is True
    assert voice_asset.metadata["provider"] == "mock_voice"
    assert voice_asset.metadata["duration_seconds"] > 0.0

    # Test captions registration
    gen = SubtitleGenerator()
    boundaries = [
        TimestampBoundary(text="Line 1 narration", offset_ms=0.0, duration_ms=2500.0),
    ]
    (srt_path, ass_path), (srt_asset, ass_asset) = gen.generate_and_register_captions(
        boundaries=boundaries,
        production_id=prod_id,
        storyboard_id=sample_storyboard.storyboard_id,
        storage_manager=sm,
        is_mock_asset=voice_res.is_mock_asset,
    )

    assert srt_path.exists()
    assert ass_path.exists()
    assert srt_asset.asset_type == ProductionAssetType.CAPTIONS
    assert ass_asset.asset_type == ProductionAssetType.CAPTIONS
    assert srt_asset.is_mock_asset is True
    assert ass_asset.is_mock_asset is True

    # Verify updated package manifest has all registered assets
    reloaded_pkg = sm.get_package(prod_id, storyboard_id=sample_storyboard.storyboard_id)
    assert len(reloaded_pkg.assets) == 3


# --- 9. BGM Attribution Retention Tests ---

def test_storage_manager_preserves_bgm_attribution_on_cleanup(sample_storyboard, tmp_path):
    """Verify StorageManager retains complete BGM attribution metadata in retained_metadata.json and upload_history.json."""
    prod_dir = tmp_path / "output" / "productions"
    manifest_dir = tmp_path / "data" / "processed" / "storage"
    sm = StorageManager(base_productions_dir=prod_dir, manifest_dir=manifest_dir)

    prod_id = "prod_test_bgm_retention"
    pkg = sm.create_production_package(storyboard_id=sample_storyboard.storyboard_id, production_id=prod_id)

    # Register a temporary asset
    temp_file = Path(pkg.root_dir) / "video" / "final.mp4"
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file.write_bytes(b"dummy video bytes")
    sm.register_asset(prod_id, ProductionAssetType.FINAL_VIDEO, temp_file)

    # Record upload
    # Record upload with valid 11-char YouTube ID
    sm.record_upload_started(prod_id, "12345678901", "https://youtu.be/12345678901")

    mock_client = MagicMock()
    list_req = MagicMock()
    list_req.execute.return_value = {
        "items": [{
            "id": "12345678901",
            "status": {"uploadStatus": "processed", "privacyStatus": "private"},
            "snippet": {"title": "Senku Science Short"},
        }]
    }
    mock_client.videos.return_value.list.return_value = list_req

    bgm_track = BGMTrackMetadata(
        track_id="cinematic_curiosity",
        title="Cinematic Curiosity",
        artist="Jeremy Blake",
        source="YouTube Audio Library",
        license="YouTube Audio Library License",
        file_path="assets/audio/bgm/cinematic_curiosity.mp3",
        attribution_required=True,
        attribution_text="Music: Cinematic Curiosity by Jeremy Blake (YouTube Audio Library)",
    )

    report = sm.verify_and_cleanup(
        production_id=prod_id,
        storyboard_id=sample_storyboard.storyboard_id,
        youtube_client=mock_client,
        bgm_track=bgm_track,
    )

    assert report.status.value == "cleaned"

    # Verify retained_metadata.json contains BGM attribution
    retained_file = Path(pkg.root_dir) / "retained_metadata.json"
    assert retained_file.exists()
    import json
    with open(retained_file, "r", encoding="utf-8") as f:
        retained_data = json.load(f)

    assert retained_data["bgm_title"] == "Cinematic Curiosity"
    assert retained_data["bgm_artist"] == "Jeremy Blake"
    assert retained_data["bgm_license"] == "YouTube Audio Library License"
    assert "Jeremy Blake" in retained_data["bgm_attribution_text"]

    # Verify upload_history.json contains BGM attribution
    with open(manifest_dir / "upload_history.json", "r", encoding="utf-8") as f:
        history_data = json.load(f)
    record = next(r for r in history_data["records"] if r["production_id"] == prod_id)
    assert record["bgm_title"] == "Cinematic Curiosity"
    assert record["bgm_attribution_text"] == "Music: Cinematic Curiosity by Jeremy Blake (YouTube Audio Library)"


def test_bgm_and_sfx_manual_import(tmp_path):
    """Verify importing real BGM and SFX calculates SHA-256 and copies to asset directory."""
    bgm_dir = tmp_path / "bgm"
    sfx_dir = tmp_path / "sfx"
    manager = BGMLibraryManager(bgm_dir=bgm_dir, sfx_dir=sfx_dir)

    # 1. Create a dummy external mp3
    src_mp3 = tmp_path / "downloaded_track.mp3"
    src_mp3.write_bytes(b"MOCK_MP3_AUDIO_DATA_FOR_BGM")

    imported_bgm = manager.import_bgm_track(
        source_audio_path=src_mp3,
        track_id="yt_bgm_custom_01",
        title="Dramatic Space Walk",
        artist="Jeremy Blake",
        source="YouTube Audio Library",
        license_name="YouTube Audio Library License - Attribution Not Required",
        attribution_required=False,
    )

    assert imported_bgm.track_id == "yt_bgm_custom_01"
    assert imported_bgm.is_file_on_disk is True
    assert imported_bgm.file_checksum is not None
    assert len(imported_bgm.file_checksum) == 64

    # 2. Create a dummy external wav for SFX
    src_wav = tmp_path / "downloaded_sfx.wav"
    src_wav.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00data\x00\x00\x00\x00")

    imported_sfx = manager.import_sfx_track(
        source_audio_path=src_wav,
        sfx_id="sfx_custom_whoosh",
        name="Sci-Fi Whoosh",
    )

    assert imported_sfx.sfx_id == "sfx_custom_whoosh"
    assert imported_sfx.is_file_on_disk is True
    assert imported_sfx.file_checksum is not None
    assert len(imported_sfx.file_checksum) == 64
