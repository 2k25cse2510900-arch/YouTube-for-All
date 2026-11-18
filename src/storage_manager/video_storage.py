"""Dedicated per-video folder structure and version replacement management."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field
from config.settings import get_settings
from src.common.logger import setup_logger
from src.storage_manager.exceptions import SecurityPathViolationError
from src.storage_manager.security_guard import PathSecurityGuard

logger = setup_logger("video_storage")


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 checksum for a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class VideoManifest(BaseModel):
    """Manifest tracking all component assets, active master, preview, and metadata for a video."""

    video_id: str = Field(..., description="Stable unique identifier for the video (e.g. 'colossal_titan')")
    title: str = Field(default="", description="Human-readable title of the video")
    version: str = Field(default="1.0.0", description="Semantic version of current master")
    status: str = Field(default="IN_PRODUCTION", description="Lifecycle status (DRAFT, IN_PRODUCTION, APPROVED_MASTER, PUBLISHED)")
    language: str = Field(default="hi-IN", description="Primary spoken language")
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    active_master: Optional[Dict[str, Any]] = Field(default=None, description="Current approved master MP4 metadata")
    active_preview: Optional[Dict[str, Any]] = Field(default=None, description="Current lightweight preview MP4 metadata (<20MB)")
    retained_previous_masters: List[Dict[str, Any]] = Field(default_factory=list, description="Recoverable previous masters under retention policy")

    script: Optional[Dict[str, Any]] = Field(default=None, description="Approved narration script metadata")
    images: List[Dict[str, Any]] = Field(default_factory=list, description="Approved visual image assets")
    audio: List[Dict[str, Any]] = Field(default_factory=list, description="Approved audio narration and stems")
    captions: List[Dict[str, Any]] = Field(default_factory=list, description="Caption and subtitle assets")
    frames: List[Dict[str, Any]] = Field(default_factory=list, description="Audit and motion frame assets")
    source_assets: List[Dict[str, Any]] = Field(default_factory=list, description="Source files, contact sheets, and references")
    reports: List[Dict[str, Any]] = Field(default_factory=list, description="Forensic audit and QA reports")

    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary production metadata")


class VideoFolderManager:
    """Manages dedicated per-video folders, atomic version replacement, and storage efficiency."""

    SUBDIRECTORIES = [
        "source",
        "script",
        "images",
        "audio",
        "captions",
        "frames",
        "preview",
        "final",
        "reports",
    ]

    def __init__(self, base_videos_dir: Optional[Path] = None):
        settings = get_settings()
        self.base_videos_dir = Path(base_videos_dir or settings.paths.videos_output_dir)
        self.base_videos_dir.mkdir(parents=True, exist_ok=True)

    def get_video_dir(self, video_id: str) -> Path:
        """Get the root folder for a video by ID."""
        clean_id = video_id.strip().lower().replace(" ", "_")
        return self.base_videos_dir / clean_id

    def initialize_video_dir(self, video_id: str, title: str = "") -> Path:
        """Create dedicated folder structure for a video with all 9 subdirectories and manifest."""
        video_dir = self.get_video_dir(video_id)
        video_dir.mkdir(parents=True, exist_ok=True)

        for sub in self.SUBDIRECTORIES:
            (video_dir / sub).mkdir(parents=True, exist_ok=True)

        manifest_path = video_dir / "manifest.json"
        if not manifest_path.exists():
            manifest = VideoManifest(
                video_id=video_id,
                title=title or video_id.replace("_", " ").title(),
            )
            self.save_manifest(video_id, manifest)
            logger.info("Initialized video folder structure for '%s' at %s", video_id, video_dir)

        return video_dir

    def load_manifest(self, video_id: str) -> VideoManifest:
        """Load the video manifest from disk."""
        video_dir = self.get_video_dir(video_id)
        manifest_path = video_dir / "manifest.json"
        if not manifest_path.exists():
            return VideoManifest(video_id=video_id)
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return VideoManifest(**data)

    def save_manifest(self, video_id: str, manifest: VideoManifest) -> None:
        """Save the video manifest atomically to disk."""
        video_dir = self.get_video_dir(video_id)
        video_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = video_dir / "manifest.json"
        tmp_path = video_dir / "manifest.json.tmp"

        manifest.updated_at = datetime.now(timezone.utc).isoformat()
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(manifest.model_dump_json(indent=2))

        # Atomic replace
        if manifest_path.exists():
            manifest_path.unlink()
        tmp_path.rename(manifest_path)
        logger.debug("Saved manifest for video '%s'", video_id)

    def register_asset(
        self,
        video_id: str,
        subfolder: str,
        source_path: Path,
        target_filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        copy_file: bool = True,
    ) -> Dict[str, Any]:
        """Register and optionally copy an asset into the video's dedicated subfolder."""
        if subfolder not in self.SUBDIRECTORIES:
            raise ValueError(f"Invalid subfolder '{subfolder}'. Must be one of {self.SUBDIRECTORIES}")

        video_dir = self.initialize_video_dir(video_id)
        dest_dir = video_dir / subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)

        source_p = Path(source_path)
        if not source_p.exists():
            raise FileNotFoundError(f"Source asset not found: {source_p}")

        dest_name = target_filename or source_p.name
        dest_path = dest_dir / dest_name

        if copy_file and source_p.resolve() != dest_path.resolve():
            shutil.copy2(source_p, dest_path)

        st = dest_path.stat()
        sha256 = compute_file_sha256(dest_path)
        rel_path = f"{subfolder}/{dest_name}"

        asset_info = {
            "name": dest_name,
            "rel_path": rel_path,
            "full_path": str(dest_path),
            "size_bytes": st.st_size,
            "size_mb": round(st.st_size / (1024 * 1024), 3),
            "sha256": sha256,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        # Update manifest
        manifest = self.load_manifest(video_id)
        collection = getattr(manifest, subfolder, None)
        if collection is not None and isinstance(collection, list):
            # Replace existing if same name or rel_path
            new_list = [item for item in collection if item.get("name") != dest_name and item.get("rel_path") != rel_path]
            new_list.append(asset_info)
            setattr(manifest, subfolder, new_list)
        elif subfolder == "script":
            manifest.script = asset_info

        self.save_manifest(video_id, manifest)
        return asset_info

    def update_preview(
        self,
        video_id: str,
        new_preview_file: Path,
        preview_filename: str = "preview.mp4",
    ) -> Dict[str, Any]:
        """Atomically replace the outdated preview with the newly generated preview."""
        video_dir = self.initialize_video_dir(video_id)
        preview_dir = video_dir / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)

        new_preview = Path(new_preview_file)
        if not new_preview.exists():
            raise FileNotFoundError(f"New preview file does not exist: {new_preview}")

        target_path = preview_dir / preview_filename
        tmp_target = preview_dir / f"{preview_filename}.tmp"

        # Copy to temp target first
        shutil.copy2(new_preview, tmp_target)

        # Atomic replacement of old preview
        if target_path.exists():
            target_path.unlink()
        tmp_target.rename(target_path)

        st = target_path.stat()
        sha256 = compute_file_sha256(target_path)

        # Gather video properties
        probe_meta = self._probe_media(target_path)

        preview_info = {
            "name": target_path.name,
            "rel_path": f"preview/{target_path.name}",
            "full_path": str(target_path),
            "size_bytes": st.st_size,
            "size_mb": round(st.st_size / (1024 * 1024), 2),
            "sha256": sha256,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "probe": probe_meta,
        }

        manifest = self.load_manifest(video_id)
        manifest.active_preview = preview_info
        self.save_manifest(video_id, manifest)

        logger.info("Updated preview for video '%s': %s (%s MB)", video_id, preview_info['rel_path'], preview_info['size_mb'])
        return preview_info

    def update_master(
        self,
        video_id: str,
        new_master_file: Path,
        qc_passed: bool = True,
        master_filename: str = "master.mp4",
        max_retained_previous: int = 1,
    ) -> Dict[str, Any]:
        """Replace the active master video, keeping at most `max_retained_previous` recoverable versions."""
        if not qc_passed:
            raise ValueError(f"Cannot update master video for '{video_id}' because Quality Checks did not pass.")

        video_dir = self.initialize_video_dir(video_id)
        final_dir = video_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)

        new_master = Path(new_master_file)
        if not new_master.exists():
            raise FileNotFoundError(f"New master file does not exist: {new_master}")

        target_path = final_dir / master_filename
        manifest = self.load_manifest(video_id)

        # If a previous master exists and we need to retain it
        if target_path.exists():
            # Archive existing master to previous
            prev_name = f"{Path(master_filename).stem}.previous.mp4"
            prev_path = final_dir / prev_name
            if prev_path.exists():
                prev_path.unlink()
            target_path.rename(prev_path)

            prev_st = prev_path.stat()
            prev_sha = compute_file_sha256(prev_path)
            prev_info = {
                "name": prev_name,
                "rel_path": f"final/{prev_name}",
                "full_path": str(prev_path),
                "size_bytes": prev_st.st_size,
                "size_mb": round(prev_st.st_size / (1024 * 1024), 2),
                "sha256": prev_sha,
                "archived_at": datetime.now(timezone.utc).isoformat(),
            }
            manifest.retained_previous_masters = [prev_info][:max_retained_previous]

        # Stage new master
        tmp_target = final_dir / f"{master_filename}.tmp"
        shutil.copy2(new_master, tmp_target)
        if target_path.exists():
            target_path.unlink()
        tmp_target.rename(target_path)

        st = target_path.stat()
        sha256 = compute_file_sha256(target_path)
        probe_meta = self._probe_media(target_path)

        master_info = {
            "name": target_path.name,
            "rel_path": f"final/{target_path.name}",
            "full_path": str(target_path),
            "size_bytes": st.st_size,
            "size_mb": round(st.st_size / (1024 * 1024), 2),
            "sha256": sha256,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "probe": probe_meta,
        }

        manifest.active_master = master_info
        manifest.status = "APPROVED_MASTER"
        self.save_manifest(video_id, manifest)

        logger.info("Updated active master for video '%s': %s (%s MB)", video_id, master_info['rel_path'], master_info['size_mb'])
        return master_info

    def get_referenced_paths(self, video_id: str) -> Set[Path]:
        """Return all absolute file paths currently referenced by the video manifest."""
        manifest = self.load_manifest(video_id)
        video_dir = self.get_video_dir(video_id)
        refs: Set[Path] = {video_dir / "manifest.json"}

        if manifest.active_master and "rel_path" in manifest.active_master:
            refs.add(video_dir / manifest.active_master["rel_path"])
        for prev in manifest.retained_previous_masters:
            if "rel_path" in prev:
                refs.add(video_dir / prev["rel_path"])
        if manifest.active_preview and "rel_path" in manifest.active_preview:
            refs.add(video_dir / manifest.active_preview["rel_path"])
        if manifest.script and "rel_path" in manifest.script:
            refs.add(video_dir / manifest.script["rel_path"])

        for category in ["images", "audio", "captions", "frames", "source_assets", "reports"]:
            items = getattr(manifest, category, [])
            for it in items:
                if isinstance(it, dict) and "rel_path" in it:
                    refs.add(video_dir / it["rel_path"])

        return refs

    def get_storage_report(self, video_id: Optional[str] = None) -> Dict[str, Any]:
        """Compute disk usage per subfolder for a given video or all videos."""
        if video_id:
            videos = [video_id]
        else:
            videos = [
                d.name for d in self.base_videos_dir.iterdir()
                if d.is_dir() and not d.name.startswith(".")
            ]

        report: Dict[str, Any] = {"videos": {}, "total_bytes": 0, "total_mb": 0.0, "total_files": 0}

        for vid in sorted(videos):
            v_dir = self.get_video_dir(vid)
            if not v_dir.exists():
                continue
            v_report: Dict[str, Any] = {"subfolders": {}, "total_bytes": 0, "total_mb": 0.0, "file_count": 0}
            
            for sub in self.SUBDIRECTORIES:
                s_dir = v_dir / sub
                if s_dir.exists():
                    sub_files = [f for f in s_dir.rglob("*") if f.is_file()]
                    sub_bytes = sum(f.stat().st_size for f in sub_files)
                    v_report["subfolders"][sub] = {
                        "file_count": len(sub_files),
                        "bytes": sub_bytes,
                        "mb": round(sub_bytes / (1024 * 1024), 2),
                    }
                    v_report["total_bytes"] += sub_bytes
                    v_report["file_count"] += len(sub_files)

            manifest_path = v_dir / "manifest.json"
            if manifest_path.exists():
                v_report["manifest_bytes"] = manifest_path.stat().st_size
                v_report["total_bytes"] += v_report["manifest_bytes"]
                v_report["file_count"] += 1

            v_report["total_mb"] = round(v_report["total_bytes"] / (1024 * 1024), 2)
            report["videos"][vid] = v_report
            report["total_bytes"] += v_report["total_bytes"]
            report["total_files"] += v_report["file_count"]

        report["total_mb"] = round(report["total_bytes"] / (1024 * 1024), 2)
        return report

    def _probe_media(self, path: Path) -> Dict[str, Any]:
        """Internal helper to probe media file via ffprobe."""
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                d = json.loads(res.stdout)
                fmt = d.get("format", {})
                video = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
                audio = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), None)
                return {
                    "duration": float(fmt.get("duration", 0)),
                    "format_name": fmt.get("format_name"),
                    "video_codec": video.get("codec_name") if video else None,
                    "resolution": f"{video.get('width')}x{video.get('height')}" if video else None,
                    "fps": eval(video["r_frame_rate"]) if video and "r_frame_rate" in video else None,
                    "audio_codec": audio.get("codec_name") if audio else None,
                }
        except Exception as e:
            logger.warning("ffprobe failed on %s: %s", path, e)
        return {}
