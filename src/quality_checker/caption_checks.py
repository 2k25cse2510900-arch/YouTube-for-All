"""Caption and subtitle validation checks for YouTube Shorts quality assurance."""

from pathlib import Path
import re
from typing import List, Optional

from src.common.logger import setup_logger
from src.quality_checker.models import (
    CheckSeverity,
    QualityCheckResult,
    QualityStatus,
    QualityThresholds,
)

logger = setup_logger("quality_checker_caption")


class CaptionChecker:
    """Validates subtitle files (.srt and .ass) for timing, syntax, and Hindi/English preservation."""

    def __init__(self, thresholds: Optional[QualityThresholds] = None):
        self.thresholds = thresholds or QualityThresholds()

    def run_checks(
        self,
        caption_path: Optional[Path],
        video_duration: Optional[float] = None,
        is_burned_in: bool = False,
        allow_no_captions: bool = False,
        confirmed_burned_in_visually: bool = False,
    ) -> List[QualityCheckResult]:
        """Execute complete caption inspection suite."""
        results: List[QualityCheckResult] = []

        if not caption_path:
            if allow_no_captions:
                results.append(
                    QualityCheckResult(
                        check_name="captions_presence",
                        status=QualityStatus.WARNING,
                        severity=CheckSeverity.WARNING,
                        message="Captions omitted via explicit policy override (allow_no_captions=True).",
                        suggested_correction="Subtitles are strongly recommended for YouTube Shorts mobile viewer retention.",
                    )
                )
                return results

            if is_burned_in and confirmed_burned_in_visually:
                results.append(
                    QualityCheckResult(
                        check_name="captions_presence",
                        status=QualityStatus.WARNING,
                        severity=CheckSeverity.WARNING,
                        message="Burned-in captions visually confirmed by creator, but source subtitle file was not provided for programmatic timing/text validation.",
                        suggested_correction="Supply source .ass/.srt file to enable automated text and timing validation.",
                    )
                )
                return results

            # Missing captions FAIL by default
            results.append(
                QualityCheckResult(
                    check_name="captions_presence",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message="Missing caption file. Subtitles are required for YouTube Shorts retention. Provide source .ass/.srt file.",
                    suggested_correction="Generate subtitles using SubtitleGenerator before running quality check.",
                )
            )
            return results

        path = Path(caption_path).resolve()
        str_path = str(path)

        # 1. Existence
        if not path.exists():
            results.append(
                QualityCheckResult(
                    check_name="captions_file_exists",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Subtitle file not found at '{path}'.",
                    file_path=str_path,
                )
            )
            return results

        # 2. Readability & Encoding (Must be UTF-8 preserving Devanagari Hindi)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError as err:
            results.append(
                QualityCheckResult(
                    check_name="captions_utf8_encoding",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Subtitle file is not valid UTF-8: {err}. Devanagari Hindi text will be corrupted.",
                    file_path=str_path,
                    suggested_correction="Save captions strictly in UTF-8 encoding.",
                )
            )
            return results
        except Exception as err:
            results.append(
                QualityCheckResult(
                    check_name="captions_readable",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message=f"Cannot read subtitle file: {err}",
                    file_path=str_path,
                )
            )
            return results

        results.append(
            QualityCheckResult(
                check_name="captions_utf8_encoding",
                status=QualityStatus.PASS,
                severity=CheckSeverity.INFO,
                message="Subtitle file is valid UTF-8.",
                file_path=str_path,
            )
        )

        # 3. Non-empty
        if not content.strip():
            results.append(
                QualityCheckResult(
                    check_name="captions_non_empty",
                    status=QualityStatus.FAIL,
                    severity=CheckSeverity.CRITICAL,
                    message="Subtitle file is empty (0 characters).",
                    file_path=str_path,
                    suggested_correction="Verify voiceover alignment and SubtitleGenerator output.",
                )
            )
            return results

        results.append(
            QualityCheckResult(
                check_name="captions_non_empty",
                status=QualityStatus.PASS,
                severity=CheckSeverity.INFO,
                message=f"Subtitles loaded ({len(content)} characters).",
                file_path=str_path,
            )
        )

        # 4. Check for Hindi / Devanagari characters
        has_devanagari = bool(re.search(r"[\u0900-\u097F]", content))
        if has_devanagari:
            results.append(
                QualityCheckResult(
                    check_name="captions_hindi_devanagari_preserved",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message="Devanagari script detected and verified intact.",
                    file_path=str_path,
                )
            )

        # 5. Parse Subtitle events (supports .srt and .ass)
        suffix = path.suffix.lower()
        if suffix == ".srt":
            events = self._parse_srt(content)
        elif suffix == ".ass":
            events = self._parse_ass(content)
        else:
            events = []

        if not events:
            results.append(
                QualityCheckResult(
                    check_name="captions_event_parsing",
                    status=QualityStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message=f"No dialogue/caption events could be parsed from '{suffix}' file.",
                    file_path=str_path,
                )
            )
            return results

        # 6. Validate Timestamps & Durations
        invalid_timing = False
        excessive_overlap = False
        exceeds_video = False
        prev_end = 0.0

        for idx, (start, end, text) in enumerate(events):
            if end <= start:
                invalid_timing = True
                results.append(
                    QualityCheckResult(
                        check_name="captions_valid_timing",
                        status=QualityStatus.FAIL,
                        severity=CheckSeverity.CRITICAL,
                        message=f"Event #{idx+1} has non-positive duration ({start:.2f}s -> {end:.2f}s).",
                        file_path=str_path,
                        measured_value=f"start={start}, end={end}",
                    )
                )
                break

            # Overlap check
            if start < (prev_end - 0.20):  # Overlap greater than 200ms
                excessive_overlap = True

            # Exceeding video duration
            if video_duration and end > (video_duration + 1.0):
                exceeds_video = True

            prev_end = max(prev_end, end)

        if not invalid_timing:
            results.append(
                QualityCheckResult(
                    check_name="captions_valid_timing",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message=f"All {len(events)} caption events have valid positive durations.",
                    file_path=str_path,
                )
            )

        if excessive_overlap:
            results.append(
                QualityCheckResult(
                    check_name="captions_excessive_overlap",
                    status=QualityStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message="Detected overlapping subtitle time spans.",
                    file_path=str_path,
                    suggested_correction="Verify speech boundary timestamps.",
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="captions_excessive_overlap",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message="No unexpected subtitle overlaps.",
                    file_path=str_path,
                )
            )

        if exceeds_video:
            results.append(
                QualityCheckResult(
                    check_name="captions_within_video_duration",
                    status=QualityStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message=f"Subtitle events extend beyond the video duration ({video_duration:.1f}s).",
                    file_path=str_path,
                    suggested_correction="Clip trailing subtitles to match video end.",
                )
            )

        # Check line length for mobile 9:16 readability (individual lines should not exceed 80 chars)
        def _max_line_len(text: str) -> int:
            sublines = [l.strip() for l in text.replace("\\N", "\n").splitlines() if l.strip()]
            return max((len(l) for l in sublines), default=len(text))

        long_captions = [f"#{idx+1} ({_max_line_len(t)} chars)" for idx, (s, e, t) in enumerate(events) if _max_line_len(t) > 80]
        if long_captions:
            results.append(
                QualityCheckResult(
                    check_name="captions_line_length",
                    status=QualityStatus.WARNING,
                    severity=CheckSeverity.WARNING,
                    message=f"Detected {len(long_captions)} caption line(s) exceeding 80 characters. May cause truncation or overflow on vertical 9:16 mobile displays.",
                    file_path=str_path,
                    measured_value=", ".join(long_captions[:3]),
                    suggested_correction="Break long sentences into shorter subtitle chunks.",
                )
            )
        else:
            results.append(
                QualityCheckResult(
                    check_name="captions_line_length",
                    status=QualityStatus.PASS,
                    severity=CheckSeverity.INFO,
                    message="All subtitle lines are concise (<= 80 characters) for mobile screens.",
                    file_path=str_path,
                )
            )

        return results

    def _parse_srt(self, content: str) -> List[tuple[float, float, str]]:
        """Extract (start_sec, end_sec, text) from SRT content."""
        pattern = re.compile(
            r"(\d+)\s*\n(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)",
            re.DOTALL,
        )
        events = []
        for match in pattern.finditer(content):
            sh, sm, ss, sms = (int(x) for x in match.group(2, 3, 4, 5))
            eh, em, es, ems = (int(x) for x in match.group(6, 7, 8, 9))
            start = sh * 3600 + sm * 60 + ss + sms / 1000.0
            end = eh * 3600 + em * 60 + es + ems / 1000.0
            text = match.group(10).strip()
            events.append((start, end, text))
        return events

    def _parse_ass(self, content: str) -> List[tuple[float, float, str]]:
        """Extract (start_sec, end_sec, text) from ASS Dialogue lines."""
        events = []
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("Dialogue:"):
                # Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
                parts = line.split(",", 9)
                if len(parts) >= 10:
                    start_str = parts[1].strip()
                    end_str = parts[2].strip()
                    text = parts[9].strip()

                    try:
                        start = self._ass_time_to_seconds(start_str)
                        end = self._ass_time_to_seconds(end_str)
                        events.append((start, end, text))
                    except Exception:
                        pass
        return events

    @staticmethod
    def _ass_time_to_seconds(time_str: str) -> float:
        # Format: H:MM:SS.cs
        h, m, s = time_str.split(":")
        sec, cs = s.split(".")
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(cs) / 100.0
