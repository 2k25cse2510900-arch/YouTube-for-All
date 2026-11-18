"""Top-level Anime Motion Pipeline orchestrator coordinating the entire creative and technical lifecycle."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.anime_motion.animation_sequence import AnimationSequenceSynthesizer
from src.anime_motion.character_bible import CharacterBible, CharacterSpecification
from src.anime_motion.image_to_video_provider import (
    BaseImageToVideoProvider,
    HybridSequentialMotionProvider,
    MockMotionProvider,
    MotionClipMetadata,
)
from src.anime_motion.keyframe_generator import KeyframeGenerator
from src.anime_motion.motion_planner import MotionStoryboardPlan
from src.anime_motion.motion_quality_checker import MotionQualityChecker, MotionQualityReport
from src.common.logger import setup_logger

logger = setup_logger("anime_pipeline")


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


class AnimeMotionPipeline:
    """End-to-end coordinator for producing anime motion Shorts."""

    def __init__(
        self,
        video_id: str,
        base_dir: Optional[Path] = None,
        provider: Optional[BaseImageToVideoProvider] = None,
    ):
        self.video_id = video_id
        project_root = Path(__file__).resolve().parent.parent.parent
        self.video_dir = Path(base_dir) if base_dir else project_root / "output" / "videos" / video_id
        self.provider = provider or HybridSequentialMotionProvider()

        # Create isolated subdirectories
        self.dirs = {
            "root": self.video_dir,
            "source": self.video_dir / "source",
            "script": self.video_dir / "script",
            "storyboard": self.video_dir / "storyboard",
            "characters": self.video_dir / "characters",
            "images": self.video_dir / "images",
            "keyframes": self.video_dir / "keyframes",
            "animation_clips": self.video_dir / "animation_clips",
            "audio": self.video_dir / "audio",
            "captions": self.video_dir / "captions",
            "frames": self.video_dir / "frames",
            "preview": self.video_dir / "preview",
            "final": self.video_dir / "final",
            "reports": self.video_dir / "reports",
        }
        for d in self.dirs.values():
            d.mkdir(parents=True, exist_ok=True)

    def execute_production(
        self,
        character_bible: CharacterBible,
        storyboard: MotionStoryboardPlan,
        narration_audio_path: Optional[Path] = None,
        bgm_audio_path: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Execute end-to-end animation synthesis, video assembly, QA, and manifest registration."""
        logger.info("Starting anime motion production for '%s'...", self.video_id)

        # 1. Save Character Bible & Storyboard Plan
        bible_path = self.dirs["characters"] / "character_bible.json"
        character_bible.save_to_file(bible_path)

        storyboard_path = self.dirs["storyboard"] / "motion_storyboard.json"
        storyboard.save_to_file(storyboard_path)

        # 2. Keyframe Generation
        kf_gen = KeyframeGenerator(character_bible, self.dirs["keyframes"])
        clip_metadata_list = []

        logger.info("Generating keyframes and rendering motion clips for %d shots...", len(storyboard.shots))
        for shot in storyboard.shots:
            # Generate start pose keyframe
            start_kf = kf_gen.generate_shot_keyframe(shot, pose_type="start")
            
            # Generate optional end pose for genuine animation shots
            end_kf = None
            if shot.motion_type.value == "genuine_ai_animation":
                end_kf = kf_gen.generate_shot_keyframe(shot, pose_type="end")

            # Render motion clip via provider (or reuse existing valid render)
            clip_name = f"{shot.shot_idx:02d}_{shot.shot_id}_motion.mp4"
            out_clip_path = self.dirs["animation_clips"] / clip_name

            if out_clip_path.exists() and out_clip_path.stat().st_size > 5000:
                logger.info("Reusing existing motion clip: %s (%.2f KB)", out_clip_path.name, out_clip_path.stat().st_size / 1024)
                clip_meta = MotionClipMetadata(
                    shot_id=shot.shot_id,
                    clip_path=str(out_clip_path),
                    duration_seconds=shot.duration,
                    motion_type=shot.motion_type,
                    provider_used=self.provider.provider_name,
                    estimated_cost_usd=0.0,
                )
            else:
                clip_meta = self.provider.generate_motion_clip(
                    shot=shot,
                    start_image_path=start_kf,
                    output_clip_path=out_clip_path,
                    end_image_path=end_kf,
                    duration_seconds=shot.duration,
                )
            clip_metadata_list.append(clip_meta)

        # 3. Assemble Master Video & Lightweight Preview
        synthesizer = AnimationSequenceSynthesizer(self.dirs["final"])
        master_mp4 = self.dirs["final"] / f"{self.video_id}_master.mp4"
        preview_mp4 = self.dirs["preview"] / f"{self.video_id}_preview.mp4"

        assembly_result = synthesizer.assemble_master_video(
            storyboard=storyboard,
            clip_metadata_list=clip_metadata_list,
            master_output_path=master_mp4,
            preview_output_path=preview_mp4,
            narration_audio_path=narration_audio_path,
            bgm_audio_path=bgm_audio_path,
        )

        # 4. Forensic Motion Quality Audit
        qa_report = MotionQualityChecker.audit_production(
            production_id=self.video_id,
            master_video_path=master_mp4,
            storyboard=storyboard,
        )

        # 5. Save Structured QA Data and Markdown Report
        qa_json_path = self.dirs["reports"] / "motion_test_data.json"
        with open(qa_json_path, "w", encoding="utf-8") as f:
            f.write(qa_report.model_dump_json(indent=2))

        # 6. Generate Manifest
        manifest_path = self.dirs["root"] / "manifest.json"
        manifest_payload = {
            "video_id": self.video_id,
            "title": storyboard.title,
            "version": "1.0.0",
            "status": "PRIVATE_TEST_ONLY",
            "language": storyboard.language,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "active_master": {
                "name": master_mp4.name,
                "rel_path": f"final/{master_mp4.name}",
                "size_bytes": master_mp4.stat().st_size,
                "size_mb": round(master_mp4.stat().st_size / (1024 * 1024), 2),
                "sha256": compute_file_sha256(master_mp4),
            },
            "active_preview": {
                "name": preview_mp4.name,
                "rel_path": f"preview/{preview_mp4.name}",
                "size_bytes": preview_mp4.stat().st_size,
                "size_mb": round(preview_mp4.stat().st_size / (1024 * 1024), 2),
                "sha256": compute_file_sha256(preview_mp4),
            },
            "storyboard_summary": {
                "total_shots": storyboard.total_shots,
                "genuine_animation_shots": storyboard.genuine_animation_shots,
                "computed_duration": storyboard.computed_duration,
            },
            "qa_status": qa_report.overall_status,
            "publication_guard": "STRICT_STOP_NO_UPLOAD",
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_payload, f, indent=2)

        logger.info("Anime motion production complete: %s (Status: %s)", master_mp4.name, qa_report.overall_status)

        return {
            "video_id": self.video_id,
            "master_mp4": str(master_mp4),
            "preview_mp4": str(preview_mp4),
            "manifest_path": str(manifest_path),
            "qa_report": qa_report,
            "assembly_result": assembly_result,
        }
