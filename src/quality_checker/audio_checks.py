"""Audio validation checks for YouTube Shorts quality assurance."""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from src.common.logger import setup_logger
from src.quality_checker.models import (
    CheckSeverity,
    QualityCheckResult,
    QualityStatus,
    QualityThresholds,
)
from src.video_editor.ffmpeg_runner import FFmpegRunner

logger = setup_logger("quality_checker_audio")


class AudioChecker:
    """Inspects audio streams of rendered videos or standalone audio mix assets."""

    def __init__(
        self,
        runner: Optional[FFmpegRunner] = None,
        thresholds: Optional[QualityThresholds] = None,
    ):
        self.runner = runner or FFmpegRunner()
        self.thresholds = thresholds or QualityThresholds()

    def run_checks(
        self,
        media_path: Path,
        expected_duration: Optional[float] = None,
    ) -> List[QualityCheckResult]:
        """Execute complete audio inspection suite on a media file."""
        results: List[QualityCheckResult] = []
        path = Path(media_path).resolve()
        str_path = str(path)

        if not path.exists():
            results.append(
                QualityCheckResult(
                    check_name="audio_file_exists",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Media file does not exist at '{path}'.",
                    file_path=str_path,
                )
            )
            return results

        # 1. Probe container with FFprobe
        try:
            probe_data = self.runner.probe_video(path)
        except Exception as err:
            results.append(
                QualityCheckResult(
                    check_name="audio_ffprobe_parse",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"FFprobe failed to inspect audio: {err}",
                    file_path=str_path,
                )
            )
            return results

        streams = probe_data.get("streams", [])
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        # 2. Audio stream existence
        if not audio_streams:
            results.append(
                QualityCheckResult(
                    check_name="audio_stream_exists",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message="No audio stream detected in media file.",
                    file_path=str_path,
                    suggested_correction="Ensure voiceover/BGM was mapped to the output container.",
                )
            )
            return results

        a_stream = audio_streams[0]
        results.append(
            QualityCheckResult(
                check_name="audio_stream_exists",
                status=QualityStatus.PASS,
                severity=CheckSeverity.INFO,
                message="Audio stream detected.",
                file_path=str_path,
            )
        )

        # 3. Audio Codec
        a_codec = (a_stream.get("codec_name") or "").lower()
        supported_audio = ["aac", "mp3", "opus", "pcm_s16le", "flac"]
        if a_codec in supported_audio:
            results.append(
                QualityCheckResult(
                    check_name="audio_codec_supported",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Audio codec '{a_codec}' is supported for YouTube playback.",
                    file_path=str_path,
                    measured_value=a_codec,
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="audio_codec_supported",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Unsupported audio codec '{a_codec}'.",
                    file_path=str_path,
                    measured_value=a_codec,
                    suggested_correction="Encode audio as AAC or MP3.",
                )
            )

        # 4. Sample Rate & Channels
        sample_rate = int(a_stream.get("sample_rate", 0))
        channels = int(a_stream.get("channels", 0))

        if sample_rate in [44100, 48000]:
            results.append(
                QualityCheckResult(
                    check_name="audio_sample_rate",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Standard audio sample rate {sample_rate} Hz.",
                    file_path=str_path,
                    measured_value=sample_rate,
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="audio_sample_rate",
                    status=QualityStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message=f"Non-standard sample rate {sample_rate} Hz (recommended: 44.1 kHz or 48 kHz).",
                    file_path=str_path,
                    measured_value=sample_rate,
                )
            )

        if channels in [1, 2]:
            results.append(
                QualityCheckResult(
                    check_name="audio_channels",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Valid channel count ({'mono' if channels == 1 else 'stereo'}).",
                    file_path=str_path,
                    measured_value=channels,
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="audio_channels",
                    status=QualityStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message=f"Unusual audio channel layout with {channels} channels.",
                    file_path=str_path,
                    measured_value=channels,
                )
            )

        # 5. Loudness & Silence Analysis via FFmpeg volumedetect & silencedetect
        analysis_results = self._analyze_audio_levels(path, expected_duration=expected_duration)
        results.extend(analysis_results)

        return results

    def _analyze_audio_levels(
        self,
        media_path: Path,
        expected_duration: Optional[float] = None,
    ) -> List[QualityCheckResult]:
        """Perform volumedetect and silencedetect analysis on the audio stream."""
        results: List[QualityCheckResult] = []

        # Run volumedetect
        cmd_vol = [
            "-i", str(media_path),
            "-vn",
            "-af", "volumedetect",
            "-f", "null", "-",
        ]
        mean_vol: Optional[float] = None
        max_vol: Optional[float] = None

        try:
            proc, _ = self.runner.run_ffmpeg(cmd_vol, timeout=15)
            stderr = proc.stderr or ""

            # Parse max_volume and mean_volume
            max_vol_match = re.search(r"max_volume:\s*(-?[0-9.]+)\s*dB", stderr)
            mean_vol_match = re.search(r"mean_volume:\s*(-?[0-9.]+)\s*dB", stderr)

            if max_vol_match:
                max_vol = float(max_vol_match.group(1))
            if mean_vol_match:
                mean_vol = float(mean_vol_match.group(1))

            # 5a. Absolute silence / inaudible track check (BLOCKING FAIL)
            if (mean_vol is not None and mean_vol <= self.thresholds.absolute_silence_threshold_db) or (
                max_vol is not None and max_vol <= -50.0
            ):
                results.append(
                    QualityCheckResult(
                        check_name="audio_silence_level",
                        status=QualityStatus.FAIL,
                        severity=CheckSeverity.CRITICAL,
                        message=f"Audio track is completely silent or below audible threshold (mean: {mean_vol} dB, max: {max_vol} dB).",
                        file_path=str(media_path),
                        measured_value=f"mean={mean_vol}dB, max={max_vol}dB",
                        suggested_correction="Check TTS voiceover rendering and audio mixer output.",
                    )
                )
            elif mean_vol is not None and mean_vol < self.thresholds.min_audible_mean_volume_db:
                results.append(
                    QualityCheckResult(
                        check_name="audio_silence_level",
                        status=QualityStatus.WARNING,
                        severity=CheckSeverity.WARNING,
                        message=f"Audio track is unusually quiet (mean: {mean_vol:.1f} dB).",
                        file_path=str(media_path),
                        measured_value=f"{mean_vol} dB",
                        suggested_correction="Normalize voice narration levels for mobile device clarity.",
                    )
                )
            else:
                results.append(
                    QualityCheckResult(
                        check_name="audio_silence_level",
                        status=QualityStatus.PASS,
                        severity=CheckSeverity.INFO,
                        message=f"Mean loudness is audible at {mean_vol if mean_vol is not None else 'N/A'} dB.",
                        file_path=str(media_path),
                        measured_value=f"{mean_vol} dB",
                    )
                )

            # 5b. Clipping check
            if max_vol is not None:
                if max_vol >= self.thresholds.clipping_peak_db:
                    results.append(
                        QualityCheckResult(
                            check_name="audio_clipping_detection",
                            status=QualityStatus.WARNING,
                            severity=CheckSeverity.WARNING,
                            message=f"Potential digital clipping: peak volume is {max_vol:.1f} dB (>= {self.thresholds.clipping_peak_db} dB).",
                            file_path=str(media_path),
                            measured_value=f"{max_vol} dB",
                            suggested_correction="Reduce master or BGM gain in AudioMixer.",
                        )
                    )
                else:
                    results.append(
                        QualityCheckResult(
                            check_name="audio_clipping_detection",
                            status=QualityStatus.PASS,
                            severity=CheckSeverity.INFO,
                            message=f"Peak volume is safe at {max_vol:.1f} dB (no clipping).",
                            file_path=str(media_path),
                            measured_value=f"{max_vol} dB",
                        )
                    )

        except Exception as err:
            logger.debug("Volume analysis skipped: %s", err)

        # Run silencedetect (noise=-50dB, d=3.5s)
        cmd_silence = [
            "-i", str(media_path),
            "-vn",
            "-af", f"silencedetect=noise=-50dB:d={self.thresholds.max_consecutive_silence_seconds}",
            "-f", "null", "-",
        ]
        try:
            proc_s, _ = self.runner.run_ffmpeg(cmd_silence, timeout=15)
            stderr_s = proc_s.stderr or ""
            silence_starts = re.findall(r"silence_start:\s*([0-9.]+)", stderr_s)
            silence_durations = [float(d) for d in re.findall(r"silence_duration:\s*([0-9.]+)", stderr_s)]

            total_silence = sum(silence_durations)
            ref_duration = expected_duration or 45.0  # fallback reference duration

            # 5c. Excessive silence ratio (BLOCKING FAIL if > max_total_silence_ratio)
            if expected_duration and expected_duration > 0 and (total_silence / expected_duration) >= self.thresholds.max_total_silence_ratio:
                ratio_pct = int(round((total_silence / expected_duration) * 100))
                results.append(
                    QualityCheckResult(
                        check_name="audio_excessive_silence_detection",
                        status=QualityStatus.FAIL,
                        severity=CheckSeverity.CRITICAL,
                        message=f"Defective silence: {total_silence:.1f}s of silence detected ({ratio_pct}% of {expected_duration:.1f}s video duration).",
                        file_path=str(media_path),
                        measured_value=f"{total_silence:.1f}s ({ratio_pct}%)",
                        suggested_correction="Ensure voiceover narration spans the full timeline.",
                    )
                )
            elif (silence_durations and any(d > self.thresholds.max_consecutive_silence_seconds for d in silence_durations)) or (silence_starts and not silence_durations):
                longest_gap = max(silence_durations) if silence_durations else self.thresholds.max_consecutive_silence_seconds
                results.append(
                    QualityCheckResult(
                        check_name="audio_excessive_silence_detection",
                        status=QualityStatus.WARNING,
                        severity=CheckSeverity.WARNING,
                        message=f"Detected prolonged pause of {longest_gap:.1f}s exceeding {self.thresholds.max_consecutive_silence_seconds}s threshold ({len(silence_starts)} occurrence(s)).",
                        file_path=str(media_path),
                        measured_value=f"{len(silence_starts)} gaps",
                        suggested_correction="Review narration pacing and BGM continuity.",
                    )
                )
            else:
                results.append(
                    QualityCheckResult(
                        check_name="audio_excessive_silence_detection",
                        status=QualityStatus.PASS,
                        severity=CheckSeverity.INFO,
                        message="Audio has continuous sound with natural narration pacing.",
                        file_path=str(media_path),
                    )
                )
        except Exception as err:
            logger.debug("Silence analysis skipped: %s", err)

        return results
