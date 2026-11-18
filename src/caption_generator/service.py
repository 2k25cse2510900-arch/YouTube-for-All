"""Subtitle and Caption generator producing standardized .srt and .ass captions."""

from pathlib import Path
import textwrap
from typing import Any, List, Optional, Tuple

from src.audio_engine.exceptions import AudioEngineError
from src.audio_engine.models import TimestampBoundary
from src.caption_generator.models import CaptionFormat, CaptionItem, CaptionStyle
from src.common.logger import setup_logger

logger = setup_logger("caption_generator")


def _format_srt_timestamp(seconds: float) -> str:
    """Format seconds into SRT timestamp: HH:MM:SS,mmm"""
    millis = int(round(seconds * 1000))
    hours = millis // 3600000
    millis %= 3600000
    minutes = millis // 60000
    millis %= 60000
    secs = millis // 1000
    millis %= 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _format_ass_timestamp(seconds: float) -> str:
    """Format seconds into ASS timestamp: H:MM:SS.cc (centiseconds)"""
    centis = int(round(seconds * 100))
    hours = centis // 360000
    centis %= 360000
    minutes = centis // 6000
    centis %= 6000
    secs = centis // 100
    centis %= 100
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


class SubtitleGenerator:
    """Generates standardized subtitles using actual speech timestamp boundaries.

    CRITICAL RULE:
    Actual timestamps from voice synthesis are used directly.
    Word timings are NEVER invented or faked.
    """

    def __init__(self, default_style: Optional[CaptionStyle] = None):
        self.style = default_style or CaptionStyle()

    def build_caption_items(self, boundaries: List[TimestampBoundary]) -> List[CaptionItem]:
        """Convert speech timestamp boundaries into sequential caption items without fabricating timings.

        Enforces strict validation:
        1. Rejects inverted boundaries (end < start or negative duration).
        2. Safely skips zero-duration boundaries or sub-centisecond intervals.
        3. Safely skips fully enclosed/nested boundaries that cannot form a valid positive interval.
        4. Safely clamps partial overlaps to the previous boundary end time, preserving real end times.
        5. Never invents new speech timings.
        """
        if not boundaries:
            raise AudioEngineError("Cannot generate captions: No timestamp boundaries provided.")

        sorted_boundaries = sorted(boundaries, key=lambda b: (b.offset_ms, -b.duration_ms))
        items: List[CaptionItem] = []
        prev_end = 0.0

        for idx, b in enumerate(sorted_boundaries, start=1):
            if b.end_seconds < b.start_seconds or b.duration_ms < 0:
                raise AudioEngineError(
                    f"Invalid timestamp boundary: end time ({b.end_seconds}s) is before start time ({b.start_seconds}s)"
                )

            text = b.text.strip()
            if not text:
                continue

            start_sec = b.start_seconds
            end_sec = b.end_seconds

            # Handle zero-duration input
            if end_sec <= start_sec:
                logger.warning(
                    "Skipping zero-duration timestamp boundary at item %d ('%s'): start %.3fs == end %.3fs.",
                    idx,
                    text[:30],
                    start_sec,
                    end_sec,
                )
                continue

            # Handle overlap with preceding speech boundary
            if start_sec < prev_end:
                if end_sec <= prev_end:
                    logger.warning(
                        "Skipping fully nested/enclosed boundary at item %d ('%s'): interval [%.3fs - %.3fs] "
                        "falls entirely within preceding event span (prev end: %.3fs). "
                        "Cannot fabricate timings; skipping to prevent zero-duration subtitle event.",
                        idx,
                        text[:30],
                        start_sec,
                        end_sec,
                        prev_end,
                    )
                    continue

                logger.warning(
                    "Overlapping caption boundary detected at item %d ('%s'): start %.3fs < prev end %.3fs. "
                    "Clamping start time to %.3fs.",
                    idx,
                    text[:30],
                    start_sec,
                    prev_end,
                    prev_end,
                )
                start_sec = prev_end

            # Verify centisecond resolution for ASS and SRT rendering
            if int(round(end_sec * 100)) <= int(round(start_sec * 100)):
                logger.warning(
                    "Skipping caption event at item %d ('%s'): interval [%.3fs - %.3fs] rounds to identical "
                    "centiseconds (%s). Subtitle would have 0 display duration.",
                    idx,
                    text[:30],
                    start_sec,
                    end_sec,
                    _format_ass_timestamp(start_sec),
                )
                continue

            formatted_text = textwrap.fill(text, width=50) if len(text) > 50 and "\n" not in text else text
            items.append(
                CaptionItem(
                    index=len(items) + 1,
                    start_seconds=start_sec,
                    end_seconds=end_sec,
                    text=formatted_text,
                )
            )
            prev_end = end_sec

        if not items:
            if not any(b.text.strip() for b in sorted_boundaries):
                raise AudioEngineError("Cannot generate captions: All timestamp boundaries had empty text.")
            raise AudioEngineError(
                "Cannot generate captions: No valid positive-duration caption intervals could be constructed."
            )

        return items

    def export_srt(self, items: List[CaptionItem], output_path: Path) -> Path:
        """Export captions in SubRip (.srt) format."""
        if not items:
            raise AudioEngineError("Cannot export empty subtitle file: No caption items provided.")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        lines: List[str] = []
        exported_count = 0
        for item in items:
            start_str = _format_srt_timestamp(item.start_seconds)
            end_str = _format_srt_timestamp(item.end_seconds)
            if start_str == end_str:
                logger.warning(
                    "Skipping SRT event %d ('%s') with identical formatted timestamp: %s",
                    item.index,
                    item.text[:30],
                    start_str,
                )
                continue
            exported_count += 1
            lines.append(str(exported_count))
            lines.append(f"{start_str} --> {end_str}")
            lines.append(item.text)
            lines.append("")

        if exported_count == 0:
            raise AudioEngineError("Cannot export empty subtitle file: No valid positive-duration caption items.")

        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.info("Exported %d SRT caption events to '%s'", exported_count, out.name)
        return out

    def export_ass(
        self,
        items: List[CaptionItem],
        output_path: Path,
        style: Optional[CaptionStyle] = None,
    ) -> Path:
        """Export captions in Advanced SubStation Alpha (.ass) format styled for 9:16 Shorts."""
        if not items:
            raise AudioEngineError("Cannot export empty subtitle file: No caption items provided.")

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        st = style or self.style

        header = f"""[Script Info]
Title: A Lesson With AI - YouTube Shorts Captions
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: None
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ShortsDefault,{st.font_name},{st.font_size},{st.primary_color},{st.secondary_color},{st.outline_color},{st.back_color},{-1 if st.bold else 0},{-1 if st.italic else 0},0,0,100,100,0,0,1,{st.outline_width},{st.shadow},{st.alignment},{st.margin_l},{st.margin_r},{st.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines: List[str] = []
        for item in items:
            start_str = _format_ass_timestamp(item.start_seconds)
            end_str = _format_ass_timestamp(item.end_seconds)
            if start_str == end_str:
                logger.warning(
                    "Skipping ASS event %d ('%s') with identical formatted timestamp: %s",
                    item.index,
                    item.text[:30],
                    start_str,
                )
                continue
            # Escape newlines for ASS
            clean_text = item.text.replace("\n", "\\N")
            dialogue_lines.append(
                f"Dialogue: 0,{start_str},{end_str},ShortsDefault,,0,0,0,,{clean_text}"
            )

        if not dialogue_lines:
            raise AudioEngineError("Cannot export empty subtitle file: No valid positive-duration caption items.")

        full_content = header + "\n".join(dialogue_lines) + "\n"
        with open(out, "w", encoding="utf-8") as f:
            f.write(full_content)

        logger.info("Exported %d ASS vertical styled caption events to '%s'", len(dialogue_lines), out.name)
        return out

    def export_both(
        self,
        boundaries: List[TimestampBoundary],
        base_path_without_ext: Path,
    ) -> tuple[Path, Path]:
        """Export both .srt and .ass simultaneously."""
        items = self.build_caption_items(boundaries)
        base = Path(base_path_without_ext)
        srt_file = self.export_srt(items, base.with_suffix(".srt"))
        ass_file = self.export_ass(items, base.with_suffix(".ass"))
        return srt_file, ass_file

    def generate_and_register_captions(
        self,
        boundaries: List[TimestampBoundary],
        production_id: str,
        storyboard_id: str,
        storage_manager: Any,
        style: Optional[CaptionStyle] = None,
        is_mock_asset: bool = False,
    ) -> tuple[tuple[Path, Path], tuple[Any, Any]]:
        """Generate both .srt and .ass captions in the production folder and register them with StorageManager."""
        from src.storage_manager.models import ProductionAssetType

        package = storage_manager.get_package(production_id, storyboard_id=storyboard_id)
        if not package:
            package = storage_manager.create_production_package(
                storyboard_id=storyboard_id,
                production_id=production_id,
            )

        captions_dir = Path(package.root_dir) / "captions"
        captions_dir.mkdir(parents=True, exist_ok=True)
        base_path = captions_dir / f"captions_{storyboard_id}"

        # If custom style passed, apply it to export_ass
        items = self.build_caption_items(boundaries)
        srt_path = self.export_srt(items, base_path.with_suffix(".srt"))
        ass_path = self.export_ass(items, base_path.with_suffix(".ass"), style=style)

        srt_asset = storage_manager.register_asset(
            production_id=production_id,
            asset_type=ProductionAssetType.CAPTIONS,
            file_path=srt_path,
            storyboard_id=storyboard_id,
            is_mock_asset=is_mock_asset,
            metadata={"format": "srt", "event_count": len(items)},
        )

        ass_asset = storage_manager.register_asset(
            production_id=production_id,
            asset_type=ProductionAssetType.CAPTIONS,
            file_path=ass_path,
            storyboard_id=storyboard_id,
            is_mock_asset=is_mock_asset,
            metadata={"format": "ass", "style": "9:16 vertical shorts", "event_count": len(items)},
        )

        return (srt_path, ass_path), (srt_asset, ass_asset)
