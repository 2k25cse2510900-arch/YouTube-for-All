"""Storage Manager service coordinating asset organization, verification, and automatic cleanup."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional
import uuid

from config.settings import get_settings
from src.common.logger import setup_logger
from src.storage_manager.exceptions import (
    DuplicateUploadError,
    ProductionNotFoundError,
    VerificationUncertainError,
)
from src.storage_manager.models import (
    CleanupReport,
    CleanupStatus,
    ProcessingStatus,
    ProductionAsset,
    ProductionAssetType,
    ProductionPackage,
    RetainedMetadata,
    UploadRecord,
    UploadStatus,
)
from src.storage_manager.security_guard import PathSecurityGuard
from src.storage_manager.verifier import YouTubeUploadVerifier

logger = setup_logger("storage_manager")


class StorageManager:
    """Coordinates local asset storage, YouTube upload verification, and automatic cleanup."""

    def __init__(
        self,
        base_productions_dir: Optional[Path] = None,
        manifest_dir: Optional[Path] = None,
    ):
        settings = get_settings()
        self.settings = settings
        self.productions_dir = Path(base_productions_dir or settings.paths.productions_output_dir)
        self.manifest_dir = Path(manifest_dir or settings.paths.storage_manifest_dir)

        self.productions_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        self.upload_history_path = self.manifest_dir / "upload_history.json"
        self._init_upload_history()

    def _init_upload_history(self) -> None:
        """Initialize upload history index file if not present."""
        if not self.upload_history_path.exists():
            with open(self.upload_history_path, "w", encoding="utf-8") as f:
                json.dump({"records": []}, f, indent=2)

    def _append_to_upload_history(self, retained: RetainedMetadata) -> None:
        """Record permanent retained metadata in the master upload history index."""
        try:
            with open(self.upload_history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {"records": []}

        # Avoid duplicate records
        data["records"] = [r for r in data.get("records", []) if r.get("production_id") != retained.production_id]
        data["records"].append(retained.model_dump(mode="json"))

        with open(self.upload_history_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def create_production_package(
        self,
        storyboard_id: str,
        production_id: Optional[str] = None,
    ) -> ProductionPackage:
        """Create an organized directory tree for a single Short production run."""
        if not production_id:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            short_id = uuid.uuid4().hex[:6]
            production_id = f"prod_{storyboard_id}_{timestamp}_{short_id}"

        root_folder = self.productions_dir / storyboard_id / production_id
        for subdir in ["images", "audio", "captions", "intermediate", "video"]:
            (root_folder / subdir).mkdir(parents=True, exist_ok=True)

        upload_rec = UploadRecord(
            production_id=production_id,
            storyboard_id=storyboard_id,
            upload_status=UploadStatus.PENDING,
            processing_status=ProcessingStatus.UNKNOWN,
            cleanup_status=CleanupStatus.PENDING,
        )

        package = ProductionPackage(
            production_id=production_id,
            storyboard_id=storyboard_id,
            root_dir=str(root_folder),
            assets=[],
            upload_record=upload_rec,
        )

        self._save_package(package)
        logger.info("Initialized production package '%s' in '%s'", production_id, root_folder)
        return package

    def _save_package(self, package: ProductionPackage) -> None:
        """Save package manifest inside the production folder."""
        manifest_file = Path(package.root_dir) / "package_manifest.json"
        with open(manifest_file, "w", encoding="utf-8") as f:
            f.write(package.model_dump_json(indent=2))

    def get_package(self, production_id: str, storyboard_id: Optional[str] = None) -> Optional[ProductionPackage]:
        """Load an existing production package by ID."""
        # Check direct path if storyboard_id is known
        if storyboard_id:
            direct_path = self.productions_dir / storyboard_id / production_id / "package_manifest.json"
            if direct_path.exists():
                with open(direct_path, "r", encoding="utf-8") as f:
                    return ProductionPackage(**json.load(f))

        # Search within productions_dir
        if self.productions_dir.exists():
            for sb_dir in self.productions_dir.iterdir():
                if sb_dir.is_dir():
                    candidate = sb_dir / production_id / "package_manifest.json"
                    if candidate.exists():
                        with open(candidate, "r", encoding="utf-8") as f:
                            return ProductionPackage(**json.load(f))
        return None

    def load_production_package(self, production_id: str, storyboard_id: Optional[str] = None) -> Optional[ProductionPackage]:
        """Alias for get_package for pipeline convenience."""
        return self.get_package(production_id, storyboard_id=storyboard_id)

    def save_storyboard_dossier(self, dossier: Any) -> Path:
        """Save a storyboard dossier JSON in the storyboards directory."""
        from src.storyboard_generator.service import StoryboardGenerator
        sg = StoryboardGenerator()
        return sg._save_storyboard_file(dossier)

    def load_storyboard_dossier(self, storyboard_id: str) -> Optional[Any]:
        """Load a persisted storyboard dossier by ID."""
        from src.storyboard_generator.service import StoryboardGenerator
        sg = StoryboardGenerator()
        return sg.get_storyboard(storyboard_id)

    def find_storyboards_for_script(self, script_id: str) -> List[Any]:
        """Find storyboards associated with a script."""
        from src.storyboard_generator.service import StoryboardGenerator
        sg = StoryboardGenerator()
        sb = sg.get_storyboard(f"sb_{script_id}")
        return [sb] if sb else []

    def register_asset(
        self,
        production_id: str,
        asset_type: ProductionAssetType,
        file_path: Path,
        storyboard_id: Optional[str] = None,
        is_mock_asset: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProductionAsset:
        """Register a temporary production file into the package manifest."""
        package = self.get_package(production_id, storyboard_id=storyboard_id)
        if not package:
            raise ProductionNotFoundError(f"Production package '{production_id}' not found.")

        target_file = Path(file_path).resolve()
        if not target_file.exists():
            raise FileNotFoundError(f"Asset file does not exist: {target_file}")

        file_size = target_file.stat().st_size
        with open(target_file, "rb") as f:
            checksum = hashlib.sha256(f.read()).hexdigest()

        asset_id = f"{asset_type.value}_{target_file.stem}_{uuid.uuid4().hex[:4]}"
        asset = ProductionAsset(
            asset_id=asset_id,
            asset_type=asset_type,
            file_path=str(target_file),
            file_size_bytes=file_size,
            file_hash=checksum,
            is_temporary=True,
            is_mock_asset=is_mock_asset,
            metadata=metadata or {},
            created_at=datetime.now(timezone.utc),
        )

        package.add_asset(asset)
        self._save_package(package)
        logger.info("Registered asset '%s' (%s, %d bytes) in package '%s'", asset.asset_id, asset_type.value, file_size, production_id)
        return asset

    def record_upload_initiating(
        self,
        production_id: str,
        resumable_session_uri: Optional[str] = None,
        storyboard_id: Optional[str] = None,
    ) -> UploadRecord:
        """Atomically transition package to UPLOADING state and enforce concurrency guards.

        Raises:
            ProductionNotFoundError: If package does not exist.
            DuplicateUploadError: If upload is already in-progress, completed, verified, or uncertain.
        """
        package = self.get_package(production_id, storyboard_id=storyboard_id)
        if not package:
            raise ProductionNotFoundError(f"Production package '{production_id}' not found.")

        current_status = package.upload_record.upload_status
        if current_status == UploadStatus.UPLOADING:
            raise DuplicateUploadError(
                f"Concurrent upload blocked: Production '{production_id}' is already in UPLOADING state."
            )
        if current_status in [UploadStatus.UPLOADED, UploadStatus.VERIFIED]:
            existing_vid = package.upload_record.youtube_video_id
            raise DuplicateUploadError(
                f"Production '{production_id}' has already been uploaded with Video ID '{existing_vid}'."
            )
        if current_status == UploadStatus.UNCERTAIN:
            raise DuplicateUploadError(
                f"Production '{production_id}' is in UNCERTAIN state following a prior network interruption. "
                "Manual review or explicit session recovery is required before initiating another upload."
            )

        package.upload_record.upload_status = UploadStatus.UPLOADING
        package.upload_record.resumable_session_uri = resumable_session_uri
        package.upload_record.upload_initiated_at = datetime.now(timezone.utc)
        package.upload_record.cleanup_status = CleanupStatus.PRESERVED

        self._save_package(package)
        logger.info("Upload initiating for production '%s'. Status set to UPLOADING.", production_id)
        return package.upload_record

    def record_upload_started(
        self,
        production_id: str,
        video_id: str,
        video_url: str,
        storyboard_id: Optional[str] = None,
    ) -> UploadRecord:
        """Record that a YouTube upload has completed and received a video ID."""
        package = self.get_package(production_id, storyboard_id=storyboard_id)
        if not package:
            raise ProductionNotFoundError(f"Production package '{production_id}' not found.")

        package.upload_record.youtube_video_id = video_id
        package.upload_record.youtube_url = video_url
        package.upload_record.upload_status = UploadStatus.UPLOADED
        package.upload_record.uploaded_at = datetime.now(timezone.utc)

        self._save_package(package)
        logger.info("Upload recorded for production '%s': Video ID '%s'", production_id, video_id)
        return package.upload_record

    def record_upload_completed(
        self,
        production_id: str,
        video_id: str,
        video_url: str,
        storyboard_id: Optional[str] = None,
    ) -> UploadRecord:
        """Alias for record_upload_started to reflect post-upload completion state."""
        return self.record_upload_started(production_id, video_id, video_url, storyboard_id=storyboard_id)

    def record_upload_uncertain(
        self,
        production_id: str,
        error_message: str,
        resumable_session_uri: Optional[str] = None,
        storyboard_id: Optional[str] = None,
    ) -> UploadRecord:
        """Record that an upload's remote state is uncertain following network timeout or disconnect."""
        package = self.get_package(production_id, storyboard_id=storyboard_id)
        if not package:
            raise ProductionNotFoundError(f"Production package '{production_id}' not found.")

        package.upload_record.upload_status = UploadStatus.UNCERTAIN
        package.upload_record.cleanup_status = CleanupStatus.PRESERVED
        package.upload_record.error_message = error_message
        if resumable_session_uri:
            package.upload_record.resumable_session_uri = resumable_session_uri

        self._save_package(package)
        logger.warning(
            "Upload uncertain for production '%s': %s. All local files preserved.",
            production_id,
            error_message,
        )
        return package.upload_record

    def record_upload_failed(
        self,
        production_id: str,
        error_message: str,
        storyboard_id: Optional[str] = None,
    ) -> UploadRecord:
        """Record that an upload failed. Local files MUST be preserved for investigation."""
        package = self.get_package(production_id, storyboard_id=storyboard_id)
        if not package:
            raise ProductionNotFoundError(f"Production package '{production_id}' not found.")

        package.upload_record.upload_status = UploadStatus.FAILED
        package.upload_record.cleanup_status = CleanupStatus.PRESERVED
        package.upload_record.error_message = error_message

        self._save_package(package)
        logger.warning("Upload failed for production '%s': %s. All local files preserved.", production_id, error_message)
        return package.upload_record

    def verify_and_cleanup(
        self,
        production_id: str,
        storyboard_id: Optional[str] = None,
        dry_run: bool = False,
        youtube_client: Optional[Any] = None,
        retained_title: Optional[str] = None,
        retained_topic: Optional[str] = None,
        bgm_track: Optional[Any] = None,
    ) -> CleanupReport:
        """Verify video state on YouTube and execute cleanup of local temporary files.

        CRITICAL SAFEGUARDS:
        1. If upload failed or status is failed -> PRESERVE all files.
        2. If YouTube processing is incomplete or uncertain -> PRESERVE all files.
        3. Only when uploadStatus == 'processed' -> proceed to cleanup.
        4. In dry-run mode -> report without deleting anything on disk.
        5. Never delete scripts, approved storyboards, or essential metadata.
        """
        package = self.get_package(production_id, storyboard_id=storyboard_id)
        if not package:
            raise ProductionNotFoundError(f"Production package '{production_id}' not found.")

        upload_rec = package.upload_record
        root_path = Path(package.root_dir).resolve()

        # Rule 1: Upload failed or uncertain -> Preserve
        if upload_rec.upload_status in [UploadStatus.FAILED, UploadStatus.UNCERTAIN]:
            msg = f"Upload status is {upload_rec.upload_status.value.upper()} ({upload_rec.error_message}). Preserving all local assets."
            upload_rec.cleanup_status = CleanupStatus.PRESERVED
            self._save_package(package)
            return CleanupReport(
                production_id=production_id,
                storyboard_id=package.storyboard_id,
                dry_run=dry_run,
                eligible=False,
                status=CleanupStatus.PRESERVED,
                reason=msg,
            )

        if not upload_rec.youtube_video_id:
            msg = "No YouTube video ID associated with production. Cannot verify upload."
            upload_rec.cleanup_status = CleanupStatus.PRESERVED
            self._save_package(package)
            return CleanupReport(
                production_id=production_id,
                storyboard_id=package.storyboard_id,
                dry_run=dry_run,
                eligible=False,
                status=CleanupStatus.PRESERVED,
                reason=msg,
            )

        # Rule 2: Verify on YouTube
        try:
            is_eligible, proc_status, details = YouTubeUploadVerifier.verify_remote_status(
                video_id=upload_rec.youtube_video_id,
                video_url=upload_rec.youtube_url,
                youtube_client=youtube_client,
            )
            upload_rec.processing_status = proc_status
        except VerificationUncertainError as vue:
            msg = f"YouTube verification uncertain: {vue}. Preserving local assets."
            upload_rec.cleanup_status = CleanupStatus.PRESERVED
            self._save_package(package)
            return CleanupReport(
                production_id=production_id,
                storyboard_id=package.storyboard_id,
                dry_run=dry_run,
                eligible=False,
                status=CleanupStatus.PRESERVED,
                reason=msg,
            )

        if not is_eligible:
            msg = f"Video has not reached PROCESSED state on YouTube (Current: {proc_status.value}). Preserving files."
            upload_rec.cleanup_status = CleanupStatus.PRESERVED
            self._save_package(package)
            return CleanupReport(
                production_id=production_id,
                storyboard_id=package.storyboard_id,
                dry_run=dry_run,
                eligible=False,
                status=CleanupStatus.PRESERVED,
                reason=msg,
            )

        # Rule 3: Verification Succeeded -> Proceed to Cleanup
        upload_rec.upload_status = UploadStatus.VERIFIED
        upload_rec.verified_at = datetime.now(timezone.utc)
        upload_rec.cleanup_status = CleanupStatus.ELIGIBLE

        # Archive permanent retained metadata
        retained = RetainedMetadata(
            storyboard_id=package.storyboard_id,
            production_id=production_id,
            title=retained_title or details.get("title") or "YouTube Short",
            topic=retained_topic or "Anime Science",
            youtube_video_id=upload_rec.youtube_video_id,
            youtube_url=upload_rec.youtube_url or f"https://youtu.be/{upload_rec.youtube_video_id}",
            uploaded_at=upload_rec.uploaded_at,
            verified_at=upload_rec.verified_at,
            cleaned_at=datetime.now(timezone.utc) if not dry_run else None,
            privacy_status=details.get("privacy_status", "private"),
            bgm_title=getattr(bgm_track, "title", None) if bgm_track else None,
            bgm_artist=getattr(bgm_track, "artist", None) if bgm_track else None,
            bgm_source=getattr(bgm_track, "source", None) if bgm_track else None,
            bgm_license=getattr(bgm_track, "license", None) if bgm_track else None,
            bgm_attribution_text=getattr(bgm_track, "attribution_text", None) if bgm_track else None,
        )
        upload_rec.retained_metadata = retained
        self._append_to_upload_history(retained)

        # Write retained metadata into package folder
        retained_file = root_path / "retained_metadata.json"
        with open(retained_file, "w", encoding="utf-8") as f:
            f.write(retained.model_dump_json(indent=2))

        # Identify files for cleanup
        files_targeted: List[str] = []
        files_deleted: List[str] = []
        bytes_reclaimed = 0

        for asset in package.assets:
            target_path = Path(asset.file_path).resolve()
            files_targeted.append(str(target_path))

            if dry_run:
                if target_path.exists():
                    bytes_reclaimed += target_path.stat().st_size
            else:
                # Security Check: assert file is safe to delete
                PathSecurityGuard.assert_safe_to_delete(target_path, root_path)
                if target_path.exists():
                    size = target_path.stat().st_size
                    target_path.unlink()
                    files_deleted.append(str(target_path))
                    bytes_reclaimed += size

        if not dry_run:
            # Clean empty subdirectories inside production folder
            for sub in ["images", "audio", "captions", "intermediate", "video"]:
                folder = root_path / sub
                if folder.exists() and not any(folder.iterdir()):
                    shutil.rmtree(folder)

            upload_rec.cleanup_status = CleanupStatus.CLEANED
            upload_rec.cleaned_at = datetime.now(timezone.utc)
            self._save_package(package)
            logger.info("Cleanup completed for '%s': %d files deleted, %d bytes reclaimed.", production_id, len(files_deleted), bytes_reclaimed)

        return CleanupReport(
            production_id=production_id,
            storyboard_id=package.storyboard_id,
            dry_run=dry_run,
            eligible=True,
            status=CleanupStatus.CLEANED if not dry_run else CleanupStatus.ELIGIBLE,
            files_targeted=files_targeted,
            files_deleted=files_deleted if not dry_run else [],
            protected_files_preserved=[str(retained_file)],
            bytes_reclaimed=bytes_reclaimed,
            retained_metadata_path=str(retained_file),
            reason="Verified YouTube publication; temporary production assets cleaned." if not dry_run else "Dry-run verification succeeded; assets marked eligible for cleanup.",
        )

    def recover_from_crash(self) -> List[UploadRecord]:
        """Crash recovery: safely inspect in-flight uploads and ensure unverified assets are preserved.

        Guarantees:
        - In-flight uploads (UPLOADING) are reset to PENDING or FAILED.
        - Never deletes unverified files during recovery.
        """
        logger.info("Running storage crash recovery inspection...")
        recovered: List[UploadRecord] = []

        if not self.productions_dir.exists():
            return recovered

        for sb_dir in self.productions_dir.iterdir():
            if not sb_dir.is_dir():
                continue
            for prod_dir in sb_dir.iterdir():
                manifest_path = prod_dir / "package_manifest.json"
                if manifest_path.exists():
                    try:
                        with open(manifest_path, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            pkg = ProductionPackage(**data)

                        rec = pkg.upload_record
                        # If app crashed during upload, it was left in UPLOADING state
                        if rec.upload_status == UploadStatus.UPLOADING:
                            logger.warning(
                                "Found interrupted in-flight upload for production '%s'. Safely setting status to PENDING.",
                                pkg.production_id,
                            )
                            rec.upload_status = UploadStatus.PENDING
                            rec.cleanup_status = CleanupStatus.PRESERVED
                            self._save_package(pkg)
                            recovered.append(rec)
                    except Exception as err:
                        logger.error("Error reading manifest '%s' during crash recovery: %s", manifest_path, err)

        logger.info("Crash recovery completed: %d interrupted production(s) recovered safely.", len(recovered))
        return recovered

    def cleanup_abandoned_or_failed(
        self,
        max_failed_days: Optional[int] = None,
        max_abandoned_hours: Optional[int] = None,
        dry_run: bool = True,
    ) -> List[CleanupReport]:
        """Scan for stale failed or abandoned temporary productions based on retention policies."""
        failed_days = max_failed_days if max_failed_days is not None else self.settings.storage.failed_retention_days
        abandoned_hours = max_abandoned_hours if max_abandoned_hours is not None else self.settings.storage.abandoned_retention_hours

        now = datetime.now(timezone.utc)
        failed_threshold = now - timedelta(days=failed_days)
        abandoned_threshold = now - timedelta(hours=abandoned_hours)

        reports: List[CleanupReport] = []

        for sb_dir in self.productions_dir.iterdir():
            if not sb_dir.is_dir():
                continue
            for prod_dir in sb_dir.iterdir():
                manifest_path = prod_dir / "package_manifest.json"
                if not manifest_path.exists():
                    continue

                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        pkg = ProductionPackage(**json.load(f))
                except Exception:
                    continue

                rec = pkg.upload_record
                should_clean = False
                reason = ""

                # Stale failed upload retention expired
                if rec.upload_status == UploadStatus.FAILED and rec.created_at < failed_threshold:
                    should_clean = True
                    reason = f"Failed upload retention expired ({failed_days} days)."

                # Stale abandoned staging retention expired
                if rec.upload_status in [UploadStatus.PENDING, UploadStatus.ABANDONED] and rec.created_at < abandoned_threshold:
                    should_clean = True
                    reason = f"Abandoned staging retention expired ({abandoned_hours} hours)."

                if should_clean:
                    files_targeted = [a.file_path for a in pkg.assets]
                    files_deleted = []
                    bytes_reclaimed = 0

                    for asset in pkg.assets:
                        p = Path(asset.file_path).resolve()
                        if p.exists():
                            bytes_reclaimed += p.stat().st_size
                            if not dry_run:
                                PathSecurityGuard.assert_safe_to_delete(p, Path(pkg.root_dir).resolve())
                                p.unlink()
                                files_deleted.append(str(p))

                    if not dry_run:
                        rec.cleanup_status = CleanupStatus.CLEANED
                        self._save_package(pkg)

                    reports.append(
                        CleanupReport(
                            production_id=pkg.production_id,
                            storyboard_id=pkg.storyboard_id,
                            dry_run=dry_run,
                            eligible=True,
                            status=CleanupStatus.CLEANED if not dry_run else CleanupStatus.ELIGIBLE,
                            files_targeted=files_targeted,
                            files_deleted=files_deleted,
                            bytes_reclaimed=bytes_reclaimed,
                            reason=reason,
                        )
                    )

        return reports
