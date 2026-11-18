"""Automated tests for Storage Management, Verification, and Automatic Cleanup."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from src.storage_manager.exceptions import (
    ProductionNotFoundError,
    ProtectedFileSafetyError,
    SecurityPathViolationError,
    VerificationUncertainError,
)
from src.storage_manager.models import (
    CleanupStatus,
    ProcessingStatus,
    ProductionAssetType,
    UploadStatus,
)
from src.storage_manager.security_guard import PathSecurityGuard
from src.storage_manager.service import StorageManager
from src.storage_manager.verifier import YouTubeUploadVerifier


@pytest.fixture
def temp_storage(tmp_path):
    """Isolated StorageManager instance with temporary directories."""
    prod_dir = tmp_path / "output" / "productions"
    manifest_dir = tmp_path / "data" / "processed" / "storage"
    return StorageManager(base_productions_dir=prod_dir, manifest_dir=manifest_dir)


def _create_mock_youtube_client(upload_status="processed", privacy_status="private", title="Senku Time Science"):
    """Create a mock YouTube API client for unit testing."""
    client = MagicMock()
    videos_resource = MagicMock()
    list_request = MagicMock()

    list_request.execute.return_value = {
        "items": [
            {
                "id": "12345678901",
                "status": {
                    "uploadStatus": upload_status,
                    "privacyStatus": privacy_status,
                },
                "snippet": {
                    "title": title,
                },
            }
        ]
    }
    videos_resource.list.return_value = list_request
    client.videos.return_value = videos_resource
    return client


# --- 1. Production Package Organization Tests ---

def test_create_production_package_organization(temp_storage):
    """Verify that packages are organized by storyboard_id and production_id with required subdirectories."""
    pkg = temp_storage.create_production_package(storyboard_id="sb_anime_senku_01")

    root = Path(pkg.root_dir)
    assert root.exists()
    assert (root / "images").is_dir()
    assert (root / "audio").is_dir()
    assert (root / "captions").is_dir()
    assert (root / "intermediate").is_dir()
    assert (root / "video").is_dir()
    assert (root / "package_manifest.json").exists()

    assert pkg.upload_record.upload_status == UploadStatus.PENDING
    assert pkg.upload_record.cleanup_status == CleanupStatus.PENDING


def test_asset_registration_and_checksum(temp_storage):
    """Verify asset registration records file size, sha256 checksum, and metadata."""
    pkg = temp_storage.create_production_package(storyboard_id="sb_anime_senku_01")

    # Create dummy video file
    video_file = Path(pkg.root_dir) / "video" / "final_short.mp4"
    video_file.write_bytes(b"DUMMY_MP4_CONTENT_12345")

    asset = temp_storage.register_asset(
        production_id=pkg.production_id,
        asset_type=ProductionAssetType.FINAL_VIDEO,
        file_path=video_file,
    )

    assert asset.asset_type == ProductionAssetType.FINAL_VIDEO
    assert asset.file_size_bytes == len(b"DUMMY_MP4_CONTENT_12345")
    assert asset.file_hash != ""
    assert asset.is_temporary is True

    # Reload package
    reloaded = temp_storage.get_package(pkg.production_id)
    assert len(reloaded.assets) == 1
    assert reloaded.total_bytes == len(b"DUMMY_MP4_CONTENT_12345")


# --- 2. Successful Upload Verification & Automatic Cleanup Tests ---

def test_successful_upload_verification_and_cleanup(temp_storage):
    """Verify that after YouTube confirms uploadStatus == 'processed', temporary files are deleted and metadata is retained."""
    pkg = temp_storage.create_production_package(storyboard_id="sb_anime_senku_01")
    root = Path(pkg.root_dir)

    # Create temporary files
    img_file = root / "images" / "scene_01.png"
    audio_file = root / "audio" / "voiceover.wav"
    video_file = root / "video" / "short.mp4"

    img_file.write_bytes(b"PNG_CONTENT")
    audio_file.write_bytes(b"WAV_CONTENT")
    video_file.write_bytes(b"MP4_CONTENT")

    temp_storage.register_asset(pkg.production_id, ProductionAssetType.SCENE_IMAGE, img_file)
    temp_storage.register_asset(pkg.production_id, ProductionAssetType.VOICEOVER_AUDIO, audio_file)
    temp_storage.register_asset(pkg.production_id, ProductionAssetType.FINAL_VIDEO, video_file)

    # Mark upload started with valid YouTube ID
    video_id = "abc123xyz89"
    temp_storage.record_upload_started(
        production_id=pkg.production_id,
        video_id=video_id,
        video_url=f"https://youtu.be/{video_id}",
    )

    # Mock YouTube returning 'processed'
    yt_client = _create_mock_youtube_client(upload_status="processed", title="Senku Time Science")

    report = temp_storage.verify_and_cleanup(
        production_id=pkg.production_id,
        dry_run=False,
        youtube_client=yt_client,
        retained_title="Senku Time Science",
        retained_topic="Neuroscience",
    )

    # 1. Report shows cleanup succeeded
    assert report.eligible is True
    assert report.status == CleanupStatus.CLEANED
    assert len(report.files_deleted) == 3
    assert report.bytes_reclaimed > 0

    # 2. Temporary files were actually deleted from disk
    assert not img_file.exists()
    assert not audio_file.exists()
    assert not video_file.exists()

    # 3. Permanent metadata was retained and preserved
    assert (root / "retained_metadata.json").exists()
    assert (root / "package_manifest.json").exists()
    assert temp_storage.upload_history_path.exists()

    # Verify upload record state
    updated_pkg = temp_storage.get_package(pkg.production_id)
    assert updated_pkg.upload_record.upload_status == UploadStatus.VERIFIED
    assert updated_pkg.upload_record.cleanup_status == CleanupStatus.CLEANED
    assert updated_pkg.upload_record.retained_metadata is not None
    assert updated_pkg.upload_record.retained_metadata.youtube_video_id == video_id


# --- 3. Failed Upload & Incomplete Processing Preservation Tests ---

def test_failed_upload_preserves_all_files(temp_storage):
    """Verify that if an upload fails, all local assets are strictly preserved."""
    pkg = temp_storage.create_production_package(storyboard_id="sb_anime_senku_01")
    root = Path(pkg.root_dir)

    video_file = root / "video" / "short.mp4"
    video_file.write_bytes(b"IMPORTANT_UNUPLOADED_VIDEO")
    temp_storage.register_asset(pkg.production_id, ProductionAssetType.FINAL_VIDEO, video_file)

    # Record upload failure
    temp_storage.record_upload_failed(
        production_id=pkg.production_id,
        error_message="Connection timed out during chunked upload",
    )

    report = temp_storage.verify_and_cleanup(production_id=pkg.production_id)

    assert report.eligible is False
    assert report.status == CleanupStatus.PRESERVED
    assert len(report.files_deleted) == 0
    # Video file must STILL exist
    assert video_file.exists()


def test_youtube_processing_incomplete_preserves_files(temp_storage):
    """Verify that if video is still 'uploaded' or 'processing' on YouTube, files are preserved."""
    pkg = temp_storage.create_production_package(storyboard_id="sb_anime_senku_01")
    root = Path(pkg.root_dir)

    video_file = root / "video" / "short.mp4"
    video_file.write_bytes(b"VIDEO_PROCESSING_ON_YOUTUBE")
    temp_storage.register_asset(pkg.production_id, ProductionAssetType.FINAL_VIDEO, video_file)

    video_id = "testvid1234"
    temp_storage.record_upload_started(
        production_id=pkg.production_id,
        video_id=video_id,
        video_url=f"https://youtu.be/{video_id}",
    )

    # YouTube reports 'processing' (not finished transcode yet)
    yt_client = _create_mock_youtube_client(upload_status="processing")

    report = temp_storage.verify_and_cleanup(
        production_id=pkg.production_id,
        youtube_client=yt_client,
    )

    assert report.eligible is False
    assert report.status == CleanupStatus.PRESERVED
    assert video_file.exists()


def test_verification_network_uncertainty_preserves_files(temp_storage):
    """Verify that any network or API error during verification preserves files."""
    pkg = temp_storage.create_production_package(storyboard_id="sb_anime_senku_01")
    root = Path(pkg.root_dir)

    video_file = root / "video" / "short.mp4"
    video_file.write_bytes(b"VIDEO_DATA")
    temp_storage.register_asset(pkg.production_id, ProductionAssetType.FINAL_VIDEO, video_file)

    temp_storage.record_upload_started(
        production_id=pkg.production_id,
        video_id="testvid1234",
        video_url="https://youtu.be/testvid1234",
    )

    # Client that raises a network connection error
    failing_client = MagicMock()
    failing_client.videos().list().execute.side_effect = RuntimeError("Network connection lost")

    report = temp_storage.verify_and_cleanup(
        production_id=pkg.production_id,
        youtube_client=failing_client,
    )

    assert report.eligible is False
    assert report.status == CleanupStatus.PRESERVED
    assert "uncertain" in report.reason.lower()
    assert video_file.exists()


# --- 4. Dry-Run Cleanup Mode Tests ---

def test_dry_run_cleanup_mode_does_not_delete(temp_storage):
    """Verify that dry_run=True accurately reports files to delete without modifying the filesystem."""
    pkg = temp_storage.create_production_package(storyboard_id="sb_anime_senku_01")
    root = Path(pkg.root_dir)

    video_file = root / "video" / "short.mp4"
    video_file.write_bytes(b"VIDEO_CONTENT_DRY_RUN")
    temp_storage.register_asset(pkg.production_id, ProductionAssetType.FINAL_VIDEO, video_file)

    video_id = "dryrunvid12"
    temp_storage.record_upload_started(
        production_id=pkg.production_id,
        video_id=video_id,
        video_url=f"https://youtu.be/{video_id}",
    )

    yt_client = _create_mock_youtube_client(upload_status="processed")

    report = temp_storage.verify_and_cleanup(
        production_id=pkg.production_id,
        dry_run=True,  # DRY RUN ACTIVE
        youtube_client=yt_client,
    )

    assert report.dry_run is True
    assert report.eligible is True
    assert len(report.files_targeted) == 1
    assert len(report.files_deleted) == 0  # Nothing was deleted!
    assert report.bytes_reclaimed == len(b"VIDEO_CONTENT_DRY_RUN")

    # File must STILL exist on disk
    assert video_file.exists()


# --- 5. Crash Recovery Tests ---

def test_crash_recovery_resets_inflight_uploads_safely(temp_storage):
    """Verify that an interrupted upload left in UPLOADING status recovers to PENDING and preserves files."""
    pkg = temp_storage.create_production_package(storyboard_id="sb_anime_senku_01")
    root = Path(pkg.root_dir)

    video_file = root / "video" / "short.mp4"
    video_file.write_bytes(b"INFLIGHT_CRASH_DATA")
    temp_storage.register_asset(pkg.production_id, ProductionAssetType.FINAL_VIDEO, video_file)

    # Simulate app crash while upload was in progress
    pkg.upload_record.upload_status = UploadStatus.UPLOADING
    temp_storage._save_package(pkg)

    # Perform crash recovery
    recovered = temp_storage.recover_from_crash()

    assert len(recovered) == 1
    assert recovered[0].production_id == pkg.production_id
    assert recovered[0].upload_status == UploadStatus.PENDING
    assert recovered[0].cleanup_status == CleanupStatus.PRESERVED

    # File was not deleted during recovery
    assert video_file.exists()


# --- 6. Security & Protected File Preservation Tests ---

def test_security_guard_blocks_deleting_protected_paths(tmp_path):
    """Verify that scripts, tokens, and code cannot be deleted even if requested."""
    allowed_root = tmp_path / "output" / "productions" / "p1"
    allowed_root.mkdir(parents=True, exist_ok=True)

    # Protected paths
    protected_cases = [
        tmp_path / "data" / "scripts" / "my_script.md",
        tmp_path / "secrets" / "client_secret.json",
        tmp_path / "token.json",
        tmp_path / ".env",
        tmp_path / "src" / "main.py",
        tmp_path / "data" / "processed" / "storyboards" / "sb_01.json",
    ]

    for p in protected_cases:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("protected content", encoding="utf-8")
        with pytest.raises((ProtectedFileSafetyError, SecurityPathViolationError)):
            PathSecurityGuard.assert_safe_to_delete(p, allowed_root)


def test_security_guard_blocks_path_traversal(tmp_path):
    """Verify that path traversal outside allowed_root raises SecurityPathViolationError."""
    allowed_root = tmp_path / "output" / "productions" / "p1"
    allowed_root.mkdir(parents=True, exist_ok=True)

    outside_file = tmp_path / "output" / "other_production" / "other.mp4"
    outside_file.parent.mkdir(parents=True, exist_ok=True)
    outside_file.write_bytes(b"OTHER_DATA")

    with pytest.raises(SecurityPathViolationError):
        PathSecurityGuard.assert_safe_to_delete(outside_file, allowed_root)


# --- 7. Retention Policy Cleanup Tests ---

def test_cleanup_abandoned_staging_after_retention_period(temp_storage):
    """Verify that stale abandoned packages past the retention threshold are identified for cleanup."""
    pkg = temp_storage.create_production_package(storyboard_id="sb_anime_senku_01")
    root = Path(pkg.root_dir)

    asset_file = root / "intermediate" / "clip.ts"
    asset_file.write_bytes(b"STALE_INTERMEDIATE_CLIP")
    temp_storage.register_asset(pkg.production_id, ProductionAssetType.INTERMEDIATE_RENDER, asset_file)

    # Reload package to get updated assets, then backdate past 24 hours
    pkg = temp_storage.get_package(pkg.production_id)
    pkg.created_at = datetime.now(timezone.utc) - timedelta(hours=36)
    pkg.upload_record.created_at = pkg.created_at
    pkg.upload_record.upload_status = UploadStatus.ABANDONED
    temp_storage._save_package(pkg)

    # Run cleanup with 24 hour threshold (dry-run)
    reports = temp_storage.cleanup_abandoned_or_failed(max_abandoned_hours=24, dry_run=True)

    assert len(reports) >= 1
    target_report = next(r for r in reports if r.production_id == pkg.production_id)
    assert target_report.eligible is True
    assert target_report.bytes_reclaimed == len(b"STALE_INTERMEDIATE_CLIP")
    assert asset_file.exists()  # Dry run leaves file intact
