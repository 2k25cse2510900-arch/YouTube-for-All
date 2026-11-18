"""Safe automatic cleanup manager with dry-run default, manifest protection, and recovery journaling."""

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Set
import uuid

from config.settings import get_settings
from src.common.logger import setup_logger
from src.storage_manager.exceptions import (
    ProtectedFileSafetyError,
    SecurityPathViolationError,
)
from src.storage_manager.security_guard import PathSecurityGuard
from src.storage_manager.video_storage import VideoFolderManager

logger = setup_logger("safe_cleanup_manager")


class SafeCleanupManager:
    """Orchestrates safe disk reclamation without endangering approved creative work or active manifests."""

    def __init__(
        self,
        output_dir: Optional[Path] = None,
        journal_file: Optional[Path] = None,
        video_manager: Optional[VideoFolderManager] = None,
    ):
        settings = get_settings()
        self.output_dir = Path(output_dir or settings.paths.output_dir)
        self.journal_file = Path(
            journal_file or (settings.paths.storage_manifest_dir / "cleanup_journal.json")
        )
        self.journal_file.parent.mkdir(parents=True, exist_ok=True)
        self.video_manager = video_manager or VideoFolderManager()

    def _load_journal(self) -> List[Dict[str, Any]]:
        if self.journal_file.exists():
            try:
                with open(self.journal_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def _append_to_journal(self, entry: Dict[str, Any]) -> None:
        entries = self._load_journal()
        entries.append(entry)
        tmp = self.journal_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        if self.journal_file.exists():
            self.journal_file.unlink()
        tmp.rename(self.journal_file)

    def get_all_active_manifest_references(self) -> Set[Path]:
        """Collect all file paths referenced across all existing video manifests."""
        all_refs: Set[Path] = set()
        videos_dir = self.video_manager.base_videos_dir
        if videos_dir.exists():
            for v_dir in videos_dir.iterdir():
                if v_dir.is_dir() and not v_dir.name.startswith("."):
                    refs = self.video_manager.get_referenced_paths(v_dir.name)
                    all_refs.update(p.resolve() for p in refs if p.exists())
        return all_refs

    def identify_cleanup_candidates(
        self,
        include_ffmpeg_intermediates: bool = True,
        include_obsolete_frames: bool = True,
        include_superseded_productions: bool = False,
        include_superseded_masters: bool = False,
    ) -> List[Dict[str, Any]]:
        """Identify obsolete, temporary, or unreferenced files eligible for safe deletion."""
        protected_refs = self.get_all_active_manifest_references()
        candidates: List[Dict[str, Any]] = []

        # 1. Temporary FFmpeg / intermediate files
        if include_ffmpeg_intermediates:
            for pat in ["concat_list.txt", "test_pipe.mp4", "*.tmp"]:
                for p in self.output_dir.glob(pat):
                    if p.is_file() and p.resolve() not in protected_refs:
                        candidates.append({
                            "path": str(p),
                            "reason": "Temporary FFmpeg intermediate file",
                            "category": "ffmpeg_intermediate",
                            "size_bytes": p.stat().st_size,
                        })

            # Check enhanced_motion_temp
            enh_temp = self.output_dir / "enhanced_motion_temp"
            if enh_temp.exists():
                for p in enh_temp.rglob("*"):
                    if p.is_file() and p.resolve() not in protected_refs:
                        candidates.append({
                            "path": str(p),
                            "reason": "Temporary scene render intermediate",
                            "category": "ffmpeg_intermediate",
                            "size_bytes": p.stat().st_size,
                        })

            # Check temp_smoke_test
            smoke_temp = self.output_dir / "temp_smoke_test"
            if smoke_temp.exists():
                for p in smoke_temp.rglob("*"):
                    if p.is_file() and p.resolve() not in protected_refs:
                        candidates.append({
                            "path": str(p),
                            "reason": "Synthetic smoke test file",
                            "category": "test_intermediate",
                            "size_bytes": p.stat().st_size,
                        })

            # Check temp
            temp_dir = self.output_dir / "temp"
            if temp_dir.exists():
                for p in temp_dir.rglob("*"):
                    if p.is_file() and p.resolve() not in protected_refs:
                        candidates.append({
                            "path": str(p),
                            "reason": "Temporary voice eval scratch file",
                            "category": "scratch_audio",
                            "size_bytes": p.stat().st_size,
                        })

        # 2. Obsolete unreferenced frame dumps in output/final/
        if include_obsolete_frames:
            final_dir = self.output_dir / "final"
            if final_dir.exists():
                for sub in final_dir.iterdir():
                    if sub.is_dir() and sub.name.startswith("frames_") and sub.name != "frames_12shots_master":
                        # Legacy frame extraction folders
                        for p in sub.rglob("*"):
                            if p.is_file() and p.resolve() not in protected_refs:
                                candidates.append({
                                    "path": str(p),
                                    "reason": f"Obsolete temporary frame dump in {sub.name}",
                                    "category": "obsolete_frames",
                                    "size_bytes": p.stat().st_size,
                                })

        # 3. Superseded unreferenced masters in output/final/
        if include_superseded_masters:
            final_dir = self.output_dir / "final"
            if final_dir.exists():
                for p in final_dir.glob("*.mp4"):
                    if p.is_file() and p.resolve() not in protected_refs:
                        candidates.append({
                            "path": str(p),
                            "reason": "Superseded master video outside active manifest",
                            "category": "superseded_master",
                            "size_bytes": p.stat().st_size,
                        })

        return candidates

    def run_cleanup(
        self,
        dry_run: bool = True,
        allow_master_deletion: bool = False,
        include_ffmpeg_intermediates: bool = True,
        include_obsolete_frames: bool = True,
        include_superseded_masters: bool = False,
    ) -> Dict[str, Any]:
        """Execute cleanup with dry-run safety and security enforcement."""
        candidates = self.identify_cleanup_candidates(
            include_ffmpeg_intermediates=include_ffmpeg_intermediates,
            include_obsolete_frames=include_obsolete_frames,
            include_superseded_masters=include_superseded_masters,
        )

        protected_refs = self.get_all_active_manifest_references()
        tx_id = f"clean_tx_{uuid.uuid4().hex[:8]}"
        operation_log = {
            "transaction_id": tx_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dry_run": dry_run,
            "allow_master_deletion": allow_master_deletion,
            "candidates_found": len(candidates),
            "files_deleted": [],
            "skipped_protected": [],
            "reclaimed_bytes": 0,
            "reclaimed_mb": 0.0,
            "status": "COMPLETED",
        }

        reclaimed = 0

        for item in candidates:
            target = Path(item["path"])
            if not target.exists():
                continue

            # Protection 1: Check against manifest references
            if target.resolve() in protected_refs:
                operation_log["skipped_protected"].append({
                    "path": str(target),
                    "reason": "Referenced in active video manifest",
                })
                continue

            # Protection 2: Check for master videos
            if ("master" in target.name.lower() or "final" in target.name.lower() or item["category"] == "superseded_master") and target.suffix.lower() == ".mp4":
                if not allow_master_deletion:
                    operation_log["skipped_protected"].append({
                        "path": str(target),
                        "reason": "Master MP4 video requires explicit allow_master_deletion=True",
                    })
                    continue

            # Protection 3: PathSecurityGuard
            try:
                PathSecurityGuard.assert_safe_to_delete(target, self.output_dir)
            except (ProtectedFileSafetyError, SecurityPathViolationError) as e:
                operation_log["skipped_protected"].append({
                    "path": str(target),
                    "reason": f"PathSecurityGuard blocked deletion: {e}",
                })
                continue

            # Eligible for deletion
            size = target.stat().st_size
            if not dry_run:
                try:
                    target.unlink()
                    operation_log["files_deleted"].append({
                        "path": str(target),
                        "size_bytes": size,
                        "category": item["category"],
                    })
                    reclaimed += size
                    logger.info("Deleted obsolete file [%s]: %s", item['category'], target)
                except Exception as e:
                    logger.error("Failed to delete %s: %s", target, e)
            else:
                operation_log["files_deleted"].append({
                    "path": str(target),
                    "size_bytes": size,
                    "category": item["category"],
                    "dry_run": True,
                })
                reclaimed += size

        # Cleanup empty directories if not dry_run
        if not dry_run:
            self._prune_empty_dirs(self.output_dir)

        operation_log["reclaimed_bytes"] = reclaimed
        operation_log["reclaimed_mb"] = round(reclaimed / (1024 * 1024), 2)

        self._append_to_journal(operation_log)
        return operation_log

    def _prune_empty_dirs(self, root: Path) -> None:
        """Remove empty subdirectories within output except protected roots."""
        for d in sorted(root.rglob("*"), reverse=True):
            if d.is_dir() and not d.name.startswith("."):
                # Don't delete output/videos or its subdirectories
                if "videos" in d.parts:
                    continue
                try:
                    if not any(d.iterdir()):
                        d.rmdir()
                except Exception:
                    pass
