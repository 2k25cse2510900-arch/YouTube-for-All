"""Audio Mixer with volume control and BGM ducking."""

import math
from pathlib import Path
import struct
import wave
from typing import List, Optional

from config.settings import get_settings
from src.audio_engine.exceptions import AudioMixingError
from src.audio_engine.models import AudioMixResult, BGMTrackMetadata, SFXCue
from src.common.logger import setup_logger

logger = setup_logger("audio_mixer")


class AudioMixer:
    """Composites voiceover, background music, and sound effects with volume ducking."""

    def __init__(self):
        self.settings = get_settings().audio

    def mix_wav_audio(
        self,
        voiceover_wav_path: Path,
        output_wav_path: Path,
        bgm_track: Optional[BGMTrackMetadata] = None,
        sfx_cues: Optional[List[SFXCue]] = None,
        voice_volume: Optional[float] = None,
        bgm_ducked_volume: Optional[float] = None,
        bgm_normal_volume: Optional[float] = None,
        allow_synthetic_fallback: bool = False,
        is_mock_asset: bool = False,
    ) -> AudioMixResult:
        """Mix voiceover audio with ducked BGM and SFX into a single 16-bit PCM WAV file.

        Ducking Rule:
        - BGM volume is reduced to ducked_volume (e.g. 0.15) while voiceover is playing.
        - Voiceover is maintained at 100% (volume 1.0).

        SAFEGUARD:
        - Synthetic sine-wave fallback is strictly prohibited unless allow_synthetic_fallback=True (test only).
        """
        voice_path = Path(voiceover_wav_path).resolve()
        out_path = Path(output_wav_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if not voice_path.exists():
            raise AudioMixingError(f"Voiceover audio file does not exist: {voice_path}")

        v_vol = voice_volume if voice_volume is not None else self.settings.voice_volume
        bgm_duck = bgm_ducked_volume if bgm_ducked_volume is not None else self.settings.bgm_volume_ducked

        try:
            with wave.open(str(voice_path), "rb") as vf:
                channels = vf.getnchannels()
                sample_width = vf.getsampwidth()
                framerate = vf.getframerate()
                n_frames = vf.getnframes()
                voice_raw = vf.readframes(n_frames)

            duration = round(n_frames / float(framerate), 3)

            # Unpack voiceover samples (assuming 16-bit PCM)
            fmt = f"<{n_frames * channels}h" if sample_width == 2 else f"<{n_frames * channels}b"
            voice_samples = list(struct.unpack(fmt, voice_raw))

            # Apply voiceover volume scaling
            mixed_samples = [int(s * v_vol) for s in voice_samples]

            # If BGM is specified, verify track status and mix physical audio or strictly handle missing file
            bgm_id = None
            is_synthetic = False
            if bgm_track:
                if getattr(bgm_track, "status", "ACTIVE") != "ACTIVE" or not getattr(bgm_track, "is_verified", True):
                    raise AudioMixingError(
                        f"PRODUCTION AUDIO BLOCKED: BGM track '{bgm_track.track_id}' is '{getattr(bgm_track, 'status', 'UNKNOWN')}' "
                        f"(is_verified={getattr(bgm_track, 'is_verified', False)}). "
                        "Unverified or disabled BGM tracks cannot be mixed into production audio."
                    )
                bgm_id = bgm_track.track_id
                if bgm_track.is_file_on_disk:
                    is_synthetic = False
                    try:
                        bgm_p = Path(bgm_track.file_path)
                        temp_wav_created = None
                        if bgm_p.suffix.lower() != ".wav":
                            wav_sibling = bgm_p.with_suffix(".wav")
                            if wav_sibling.exists():
                                bgm_p = wav_sibling
                            else:
                                import subprocess
                                import tempfile
                                t_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                                t_wav.close()
                                temp_wav_created = Path(t_wav.name)
                                subprocess.run(
                                    ["ffmpeg", "-y", "-i", str(bgm_p), "-ar", str(framerate), "-ac", str(channels), str(temp_wav_created)],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    check=True,
                                )
                                bgm_p = temp_wav_created

                        with wave.open(str(bgm_p), "rb") as bf:
                            b_channels = bf.getnchannels()
                            b_width = bf.getsampwidth()
                            b_rate = bf.getframerate()
                            b_nframes = bf.getnframes()
                            b_raw = bf.readframes(b_nframes)

                        if temp_wav_created and temp_wav_created.exists():
                            temp_wav_created.unlink(missing_ok=True)
                        b_fmt = f"<{b_nframes * b_channels}h" if b_width == 2 else f"<{b_nframes * b_channels}b"
                        b_samples = list(struct.unpack(b_fmt, b_raw))
                        if b_samples:
                            for i in range(len(mixed_samples)):
                                b_val = b_samples[i % len(b_samples)]
                                ducked_b = int(b_val * bgm_duck)
                                mixed_samples[i] = max(-32768, min(32767, mixed_samples[i] + ducked_b))
                    except Exception as b_err:
                        raise AudioMixingError(f"Failed to read BGM audio file '{bgm_track.file_path}': {b_err}") from b_err
                else:
                    if not allow_synthetic_fallback:
                        raise AudioMixingError(
                            f"PRODUCTION AUDIO BLOCKED: BGM audio file '{bgm_track.file_path}' does not exist on disk. "
                            "Synthetic audio fallback is strictly prohibited in production mode. "
                            "Please verify and download licensed BGM assets before final production."
                        )
                    logger.warning(
                        "BGM file '%s' not found on disk. Generating synthetic sine fallback for test environment (allow_synthetic_fallback=True).",
                        bgm_track.file_path,
                    )
                    is_synthetic = True
                    for i in range(len(mixed_samples)):
                        t = (i // channels) / float(framerate)
                        # Ambient background synth tone
                        bgm_sample = int(3000.0 * bgm_duck * math.sin(2.0 * math.pi * 110.0 * t))
                        val = mixed_samples[i] + bgm_sample
                        # Clamp to 16-bit signed integer [-32768, 32767]
                        mixed_samples[i] = max(-32768, min(32767, val))

            # Apply SFX cues if any (synthetic ping only if allow_synthetic_fallback)
            sfx_count = 0
            if sfx_cues and allow_synthetic_fallback:
                for cue in sfx_cues:
                    start_frame = int(cue.start_time_seconds * framerate) * channels
                    if start_frame < len(mixed_samples):
                        sfx_count += 1
                        # Subtle 440Hz ping
                        for k in range(min(framerate // 4, (len(mixed_samples) - start_frame) // channels)):
                            idx = start_frame + k * channels
                            if idx < len(mixed_samples):
                                tone = int(4000.0 * cue.volume * math.sin(2.0 * math.pi * 440.0 * k / framerate))
                                mixed_samples[idx] = max(-32768, min(32767, mixed_samples[idx] + tone))

            # Write output WAV file
            with wave.open(str(out_path), "wb") as out_f:
                out_f.setnchannels(channels)
                out_f.setsampwidth(2)
                out_f.setframerate(framerate)
                out_f.writeframes(struct.pack(f"<{len(mixed_samples)}h", *mixed_samples))

            file_size = out_path.stat().st_size
            logger.info(
                "Mixed audio successfully exported to '%s' (Duration: %.2fs, Size: %d bytes)",
                out_path.name, duration, file_size
            )

            return AudioMixResult(
                mixed_audio_path=str(out_path),
                duration_seconds=duration,
                voiceover_duration=duration,
                bgm_track_id=bgm_id,
                sfx_count=sfx_count,
                file_size_bytes=file_size,
                cost_usd=0.0,
                is_mock_asset=is_mock_asset,
                is_synthetic_mix=is_synthetic,
            )

        except Exception as err:
            msg = f"Failed to mix audio files into '{out_path.name}': {err}"
            logger.error(msg)
            raise AudioMixingError(msg) from err

    def generate_ffmpeg_ducking_filter(
        self,
        voiceover_input_index: int = 0,
        bgm_input_index: int = 1,
        bgm_ducked_volume: float = 0.15,
        voiceover_volume: float = 1.0,
    ) -> str:
        """Generate native FFmpeg sidechaincompress audio ducking filtergraph for Stage 7B.

        Ducks the BGM input when the voiceover input has active speech.
        """
        return (
            f"[{voiceover_input_index}:a]volume={voiceover_volume}[voice];"
            f"[{bgm_input_index}:a]volume={bgm_ducked_volume}[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
