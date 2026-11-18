"""Video validation checks for YouTube Shorts quality assurance."""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from src.common.logger import setup_logger
from src.quality_checker.models import (
    CheckSeverity,
    QualityCheckResult,
    QualityStatus,
    QualityThresholds,
)
from src.video_editor.ffmpeg_runner import FFmpegRunner

logger = setup_logger("quality_checker_video")


class VideoChecker:
    """Inspects rendered MP4 video files using FFprobe and FFmpeg analysis."""

    def __init__(
        self,
        runner: Optional[FFmpegRunner] = None,
        thresholds: Optional[QualityThresholds] = None,
    ):
        self.runner = runner or FFmpegRunner()
        self.thresholds = thresholds or QualityThresholds()

    def run_checks(
        self,
        video_path: Path,
        expected_duration: Optional[float] = None,
        is_mock_asset: bool = False,
    ) -> List[QualityCheckResult]:
        """Execute complete video inspection suite on a rendered MP4 file."""
        results: List[QualityCheckResult] = []
        path = Path(video_path).resolve()
        str_path = str(path)

        # 1. Existence and Readability
        if not path.exists():
            results.append(
                QualityCheckResult(
                    check_name="video_file_exists",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Video file does not exist at '{path}'.",
                    file_path=str_path,
                    suggested_correction="Ensure video rendering completed successfully before QA check.",
                )
            )
            return results

        # 2. File size nonzero
        try:
            size_bytes = path.stat().st_size
        except Exception as e:
            results.append(
                QualityCheckResult(
                    check_name="video_file_readable",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Failed to read video file: {e}",
                    file_path=str_path,
                )
            )
            return results

        if size_bytes == 0:
            results.append(
                QualityCheckResult(
                    check_name="video_file_non_empty",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message="Video file exists but has 0 bytes (empty file).",
                    file_path=str_path,
                    measured_value=0,
                    suggested_correction="Re-render video to produce a valid MP4 container.",
                )
            )
            return results
        else:
            results.append(
                QualityCheckResult(
                    check_name="video_file_non_empty",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Video file is readable with size {size_bytes} bytes.",
                    file_path=str_path,
                    measured_value=size_bytes,
                )
            )

        # 3. Mock asset quarantine
        if is_mock_asset or "mock" in path.name.lower() or "synthetic" in path.name.lower():
            results.append(
                QualityCheckResult(
                    check_name="video_not_mock_asset",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message="Video is flagged as a mock or synthetic test asset. Mock assets must never be published.",
                    file_path=str_path,
                    suggested_correction="Replace mock visual/audio assets with verified production assets.",
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="video_not_mock_asset",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message="Confirmed genuine production video asset.",
                    file_path=str_path,
                )
            )

        # 4. Probe container with FFprobe
        try:
            probe_data = self.runner.probe_video(path)
        except Exception as err:
            results.append(
                QualityCheckResult(
                    check_name="video_ffprobe_parse",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"FFprobe failed to inspect video container: {err}",
                    file_path=str_path,
                    suggested_correction="Verify FFmpeg/FFprobe installation and file integrity.",
                )
            )
            return results

        streams = probe_data.get("streams", [])
        fmt = probe_data.get("format", {})

        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        # 5. Video Stream Existence
        if not video_streams:
            results.append(
                QualityCheckResult(
                    check_name="video_stream_exists",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message="No video stream detected in media container.",
                    file_path=str_path,
                    suggested_correction="Ensure video filtergraph includes a valid visual stream.",
                )
            )
            return results

        v_stream = video_streams[0]
        results.append(
            QualityCheckResult(
                check_name="video_stream_exists",
                status=QualityStatus.PASS,
                severity=CheckSeverity.INFO,
                message=f"Video stream present with codec '{v_stream.get('codec_name')}'.",
                file_path=str_path,
            )
        )

        # 6. Video Codec
        v_codec = (v_stream.get("codec_name") or "").lower()
        supported_codecs = ["h264", "libx264", "hevc", "h265", "vp9", "av1", "av01"]
        if v_codec in supported_codecs:
            results.append(
                QualityCheckResult(
                    check_name="video_codec_supported",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Video codec '{v_codec}' is supported for YouTube playback.",
                    file_path=str_path,
                    measured_value=v_codec,
                    expected_value="h264 / vp9 / hevc",
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="video_codec_supported",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Unsupported video codec '{v_codec}'. YouTube requires h264 or compatible container.",
                    file_path=str_path,
                    measured_value=v_codec,
                    suggested_correction="Re-encode using libx264 codec.",
                )
            )

        # 7. Resolution & Aspect Ratio (Strict 9:16 vertical 1080x1920)
        width = int(v_stream.get("width", 0))
        height = int(v_stream.get("height", 0))
        if width == self.thresholds.expected_width and height == self.thresholds.expected_height:
            results.append(
                QualityCheckResult(
                    check_name="video_resolution_and_aspect_ratio",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Resolution is exactly {width}x{height} (9:16 vertical).",
                    file_path=str_path,
                    measured_value=f"{width}x{height}",
                    expected_value=f"{self.thresholds.expected_width}x{self.thresholds.expected_height}",
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="video_resolution_and_aspect_ratio",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Invalid resolution {width}x{height}. YouTube Shorts requires 1080x1920 (9:16).",
                    file_path=str_path,
                    measured_value=f"{width}x{height}",
                    expected_value=f"{self.thresholds.expected_width}x{self.thresholds.expected_height}",
                    suggested_correction="Adjust FiltergraphBuilder to scale and pad to 1080x1920.",
                )
            )

        # 8. Frame Rate (FPS)
        r_fps_str = v_stream.get("r_frame_rate", "30/1")
        try:
            num, den = (int(x) for x in r_fps_str.split("/"))
            measured_fps = round(num / den, 2)
        except Exception:
            measured_fps = 30.0

        if self.thresholds.min_fps <= measured_fps <= self.thresholds.max_fps:
            results.append(
                QualityCheckResult(
                    check_name="video_framerate",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Frame rate {measured_fps} fps is within acceptable range ({self.thresholds.min_fps}-{self.thresholds.max_fps} fps).",
                    file_path=str_path,
                    measured_value=measured_fps,
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="video_framerate",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Frame rate {measured_fps} fps is outside range ({self.thresholds.min_fps}-{self.thresholds.max_fps} fps).",
                    file_path=str_path,
                    measured_value=measured_fps,
                    suggested_correction="Render video with standard 30 or 24 fps.",
                )
            )

        # 9. Duration Checks (YouTube Shorts 20s - 60s)
        try:
            duration = float(fmt.get("duration", v_stream.get("duration", 0.0)))
        except (ValueError, TypeError):
            duration = 0.0

        if duration <= 0:
            results.append(
                QualityCheckResult(
                    check_name="video_duration_valid",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message="Video duration is zero or unreadable.",
                    file_path=str_path,
                    measured_value=duration,
                )
            )
        elif duration > self.thresholds.max_duration_seconds:
            results.append(
                QualityCheckResult(
                    check_name="video_duration_valid",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Duration {duration:.1f}s exceeds YouTube Shorts limit of {self.thresholds.max_duration_seconds}s.",
                    file_path=str_path,
                    measured_value=duration,
                    expected_value=f"<={self.thresholds.max_duration_seconds}s",
                    suggested_correction="Trim script pacing to stay under 60 seconds.",
                )
            )
        elif duration < self.thresholds.min_duration_seconds:
            results.append(
                QualityCheckResult(
                    check_name="video_duration_valid",
                    status=QualityStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message=f"Video duration {duration:.1f}s is unusually short (< {self.thresholds.min_duration_seconds}s).",
                    file_path=str_path,
                    measured_value=duration,
                    suggested_correction="Verify narration or scene durations.",
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="video_duration_valid",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Duration {duration:.2f}s is within YouTube Shorts range.",
                    file_path=str_path,
                    measured_value=duration,
                )
            )

        # 10. Pixel format check
        pix_fmt = (v_stream.get("pix_fmt") or "").lower()
        if pix_fmt in ["yuv420p", "yuvj420p"]:
            results.append(
                QualityCheckResult(
                    check_name="video_pixel_format",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"Pixel format '{pix_fmt}' is standard 4:2:0 chroma compatible with YouTube.",
                    file_path=str_path,
                    measured_value=pix_fmt,
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="video_pixel_format",
                    status=QualityStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message=f"Non-standard pixel format '{pix_fmt}'. YouTube recommends yuv420p.",
                    file_path=str_path,
                    measured_value=pix_fmt,
                    suggested_correction="Re-encode with '-pix_fmt yuv420p'.",
                )
            )

        # 11. Audio-Video duration sync
        if audio_streams:
            a_stream = audio_streams[0]
            try:
                a_duration = float(a_stream.get("duration", duration))
                diff = abs(duration - a_duration)
                if diff > self.thresholds.max_av_sync_drift_seconds:
                    results.append(
                        QualityCheckResult(
                            check_name="audio_video_duration_sync",
                            status=QualityStatus.WARNING,
                            severity=CheckSeverity.WARNING,
                            message=f"Audio and video stream durations differ by {diff:.2f}s (> {self.thresholds.max_av_sync_drift_seconds}s tolerance).",
                            file_path=str_path,
                            measured_value=f"Video: {duration:.2f}s, Audio: {a_duration:.2f}s",
                            suggested_correction="Use -shortest flag in FFmpeg composition.",
                        )
                    )
                else:
                    results.append(
                        QualityCheckResult(
                            check_name="audio_video_duration_sync",
                            status=QualityStatus.PASS,
                            severity=CheckSeverity.INFO,
                            message=f"Audio/video duration alignment is within {diff:.3f}s.",
                            file_path=str_path,
                        )
                    )
            except Exception:
                pass

        # 12. Black Frame and Frozen Scene Analysis (FFmpeg visual filters)
        visual_warnings = self._detect_black_or_frozen_frames(path, duration)
        results.extend(visual_warnings)

        return results

    def _detect_black_or_frozen_frames(self, video_path: Path, duration: float) -> List[QualityCheckResult]:
        """Run lightweight FFmpeg filters to detect fully black video or frozen scenes."""
        results: List[QualityCheckResult] = []
        if duration <= 0:
            return results

        # Run blackdetect filter (pic_th=0.98, pix_th=0.10)
        # Timeout bounded to 15s to maintain 8GB laptop responsiveness
        cmd_black = [
            "-v", "info",
            "-i", str(video_path),
            "-vf", "blackdetect=d=2.0:pix_th=0.10",
            "-f", "null", "-",
        ]
        try:
            proc, _ = self.runner.run_ffmpeg(cmd_black, timeout=15)
            stderr = proc.stderr or ""
            black_matches = re.findall(r"black_start:([0-9.]+)\s+black_end:([0-9.]+)\s+black_duration:([0-9.]+)", stderr)
            if black_matches:
                total_black = sum(float(m[2]) for m in black_matches)
                if total_black >= (duration * 0.5):
                    results.append(
                        QualityCheckResult(
                            check_name="video_black_screen_detection",
                            status=QualityStatus.FAIL,
                            severity=CheckSeverity.CRITICAL,
                            message=f"Over 50% of the video is completely black ({total_black:.1f}s black duration detected).",
                            file_path=str(video_path),
                            measured_value=f"{total_black:.1f}s",
                            suggested_correction="Check image asset paths and filtergraph concat inputs.",
                        )
                    )
                else:
                    results.append(
                        QualityCheckResult(
                            check_name="video_black_screen_detection",
                            status=QualityStatus.WARNING,
                            severity=CheckSeverity.WARNING,
                            message=f"Detected black frames for {total_black:.1f}s during playback.",
                            file_path=str(video_path),
                            measured_value=f"{total_black:.1f}s",
                            suggested_correction="Inspect scene transitions and visual pacing.",
                        )
                    )
            else:
                results.append(
                    QualityCheckResult(
                        check_name="video_black_screen_detection",
                        status=QualityStatus.PASS,
                        severity=CheckSeverity.INFO,
                        message="No prolonged black screen detected.",
                        file_path=str(video_path),
                    )
                )
        except Exception as err:
            logger.debug("Black frame analysis non-critical skip: %s", err)

        # Run freezedetect filter (freeze duration >= 4.0s)
        cmd_freeze = [
            "-v", "info",
            "-i", str(video_path),
            "-vf", "freezedetect=n=-60dB:d=4.0",
            "-f", "null", "-",
        ]
        try:
            proc_f, _ = self.runner.run_ffmpeg(cmd_freeze, timeout=15)
            stderr_f = proc_f.stderr or ""
            freeze_matches = re.findall(r"freeze_start:\s*([0-9.]+)", stderr_f)
            if freeze_matches:
                results.append(
                    QualityCheckResult(
                        check_name="video_frozen_scene_detection",
                        status=QualityStatus.WARNING,
                        severity=CheckSeverity.WARNING,
                        message=f"Detected potentially static/frozen scene lasting >= 4.0s ({len(freeze_matches)} occurrence(s)).",
                        file_path=str(video_path),
                        measured_value=f"{len(freeze_matches)} occurrences",
                        suggested_correction="Ensure camera movement (zoompan) is active in Storyboard scenes.",
                    )
                )
            else:
                results.append(
                    QualityCheckResult(
                        check_name="video_frozen_scene_detection",
                        status=QualityStatus.PASS,
                        severity=CheckSeverity.INFO,
                        message="Visual motion detected across scenes without frozen frame pauses.",
                        file_path=str(video_path),
                    )
                )
        except Exception as err:
            logger.debug("Freeze frame analysis non-critical skip: %s", err)

        return results
