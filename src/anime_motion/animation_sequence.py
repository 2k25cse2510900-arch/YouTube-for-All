"""Animation Sequence Synthesizer assembling multi-shot clips, transitions, and audio."""

from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional
from src.anime_motion.image_to_video_provider import MotionClipMetadata
from src.anime_motion.motion_planner import MotionStoryboardPlan
from src.common.logger import setup_logger

logger = setup_logger("animation_sequence")


class AnimationSequenceSynthesizer:
    """Concatenates rendered animation clips and synchronizes master multi-track audio."""

    def __init__(self, output_dir: Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def assemble_master_video(
        self,
        storyboard: MotionStoryboardPlan,
        clip_metadata_list: List[MotionClipMetadata],
        master_output_path: Path,
        preview_output_path: Path,
        narration_audio_path: Optional[Path] = None,
        bgm_audio_path: Optional[Path] = None,
        sfx_tracks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Assemble all clips into a unified 1080x1920 30fps master Short."""
        master_path = Path(master_output_path)
        preview_path = Path(preview_output_path)
        master_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.parent.mkdir(parents=True, exist_ok=True)

        if master_path.exists() and master_path.stat().st_size > 1000000 and preview_path.exists() and preview_path.stat().st_size > 500000:
            logger.info("Reusing existing valid master and preview videos: %s, %s", master_path.name, preview_path.name)
            return {
                "master_path": str(master_path),
                "master_size_mb": round(master_path.stat().st_size / (1024 * 1024), 2),
                "preview_path": str(preview_path),
                "preview_size_mb": round(preview_path.stat().st_size / (1024 * 1024), 2),
                "total_duration": storyboard.computed_duration,
            }

        # 1. Create FFmpeg concat demuxer file
        concat_txt = self.output_dir / "concat_clips.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for item in clip_metadata_list:
                escaped_path = item.clip_path.replace("\\", "/")
                f.write(f"file '{escaped_path}'\n")

        # 2. Build FFmpeg command with audio mixing
        # Prepare inputs
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_txt),
        ]

        filter_complex = []
        audio_inputs_count = 0

        # Input 1: Narration (if provided)
        if narration_audio_path and Path(narration_audio_path).exists():
            cmd.extend(["-i", str(narration_audio_path)])
            audio_inputs_count += 1
            # Normal narration track
            filter_complex.append(f"[{audio_inputs_count}:a]volume=1.0[narration]")

        # Input 2: BGM (if provided)
        if bgm_audio_path and Path(bgm_audio_path).exists():
            cmd.extend(["-stream_loop", "-1", "-i", str(bgm_audio_path)])
            audio_inputs_count += 1
            # BGM ducked under voiceover
            filter_complex.append(f"[{audio_inputs_count}:a]volume=0.25[bgm]")

        # Mix audio tracks
        if audio_inputs_count == 2:
            filter_complex.append("[narration][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]")
            audio_map = ["[aout]"]
        elif audio_inputs_count == 1:
            audio_map = ["[narration]"]
        else:
            # Generate silent audio track if no voiceover
            filter_complex.append("aevalsrc=0:d=45:s=48000[aout]")
            audio_map = ["[aout]"]

        total_duration = storyboard.computed_duration

        cmd.extend([
            "-filter_complex", ";".join(filter_complex),
            "-map", "0:v",
            "-map", audio_map[0],
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            "-t", f"{total_duration:.2f}",
            str(master_path)
        ])

        logger.info("Executing master video assembly FFmpeg pipeline...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            logger.error("Master video assembly failed: %s", res.stderr)
            raise RuntimeError(f"FFmpeg assembly failed: {res.stderr[:300]}")

        # 3. Generate Lightweight Preview (<19 MB, 720x1280)
        logger.info("Generating lightweight preview MP4...")
        cmd_prev = [
            "ffmpeg", "-y",
            "-i", str(master_path),
            "-vf", "scale=720:1280",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(preview_path)
        ]
        subprocess.run(cmd_prev, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        master_size = master_path.stat().st_size
        prev_size = preview_path.stat().st_size

        logger.info("Master generated: %s (%.2f MB)", master_path.name, master_size / (1024*1024))
        logger.info("Preview generated: %s (%.2f MB)", preview_path.name, prev_size / (1024*1024))

        return {
            "master_path": str(master_path),
            "master_size_mb": round(master_size / (1024 * 1024), 2),
            "preview_path": str(preview_path),
            "preview_size_mb": round(prev_size / (1024 * 1024), 2),
            "total_duration": total_duration,
        }
