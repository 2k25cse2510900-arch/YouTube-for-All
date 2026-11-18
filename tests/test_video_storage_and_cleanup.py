"""Automated tests for dedicated per-video storage, version replacement, and safe cleanup."""

import json
from pathlib import Path
import pytest

from src.storage_manager.asset_registry import ReusableAssetRegistry
from src.storage_manager.cleanup_manager import SafeCleanupManager
from src.storage_manager.exceptions import ProtectedFileSafetyError, SecurityPathViolationError
from src.storage_manager.security_guard import PathSecurityGuard
from src.storage_manager.video_storage import VideoFolderManager, VideoManifest, compute_file_sha256


@pytest.fixture
def temp_video_storage(tmp_path):
    """Fixture providing isolated VideoFolderManager and SafeCleanupManager in temp directory."""
    base_out = tmp_path / "output"
    videos_dir = base_out / "videos"
    manifest_dir = tmp_path / "data" / "processed" / "storage"
    journal_file = manifest_dir / "cleanup_journal.json"
    registry_file = manifest_dir / "asset_registry.json"

    base_out.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)

    v_mgr = VideoFolderManager(base_videos_dir=videos_dir)
    cleanup_mgr = SafeCleanupManager(
        output_dir=base_out,
        journal_file=journal_file,
        video_manager=v_mgr,
    )
    registry = ReusableAssetRegistry(registry_file=registry_file)

    return {
        "output_dir": base_out,
        "videos_dir": videos_dir,
        "v_mgr": v_mgr,
        "cleanup_mgr": cleanup_mgr,
        "registry": registry,
    }


def test_video_folder_initialization(temp_video_storage):
    """Verify that initialize_video_dir creates all 9 subfolders and manifest.json."""
    v_mgr = temp_video_storage["v_mgr"]
    v_dir = v_mgr.initialize_video_dir("test_short_01", title="Test Short 1")

    assert v_dir.exists()
    for sub in VideoFolderManager.SUBDIRECTORIES:
        assert (v_dir / sub).is_dir(), f"Missing subfolder {sub}"

    manifest_p = v_dir / "manifest.json"
    assert manifest_p.exists()
    manifest = v_mgr.load_manifest("test_short_01")
    assert manifest.video_id == "test_short_01"
    assert manifest.title == "Test Short 1"
    assert manifest.status == "IN_PRODUCTION"


def test_asset_registration_and_manifest_tracking(temp_video_storage, tmp_path):
    """Verify registering script, image, and audio assets copies files and tracks them in manifest."""
    v_mgr = temp_video_storage["v_mgr"]
    v_mgr.initialize_video_dir("test_short_01")

    # Create dummy source files
    script_src = tmp_path / "script.json"
    script_src.write_text(json.dumps({"text": "Hello world"}), encoding="utf-8")

    img_src = tmp_path / "scene_01.png"
    img_src.write_bytes(b"FAKE_PNG_BYTES_SCENE_01")

    aud_src = tmp_path / "scene_01.mp3"
    aud_src.write_bytes(b"FAKE_MP3_BYTES_SCENE_01")

    # Register assets
    res_script = v_mgr.register_asset("test_short_01", "script", script_src, target_filename="script.json")
    res_img = v_mgr.register_asset("test_short_01", "images", img_src, target_filename="scene_01.png")
    res_aud = v_mgr.register_asset("test_short_01", "audio", aud_src, target_filename="scene_01.mp3")

    assert res_script["rel_path"] == "script/script.json"
    assert res_img["rel_path"] == "images/scene_01.png"
    assert res_aud["rel_path"] == "audio/scene_01.mp3"

    manifest = v_mgr.load_manifest("test_short_01")
    assert manifest.script["name"] == "script.json"
    assert len(manifest.images) == 1
    assert manifest.images[0]["name"] == "scene_01.png"
    assert len(manifest.audio) == 1
    assert manifest.audio[0]["name"] == "scene_01.mp3"

    refs = v_mgr.get_referenced_paths("test_short_01")
    assert Path(res_script["full_path"]) in refs
    assert Path(res_img["full_path"]) in refs
    assert Path(res_aud["full_path"]) in refs


def test_update_preview_atomic_replacement(temp_video_storage, tmp_path):
    """Verify updating preview replaces outdated preview without file accumulation."""
    v_mgr = temp_video_storage["v_mgr"]
    v_dir = v_mgr.initialize_video_dir("test_preview_replace")

    prev_1 = tmp_path / "prev_v1.mp4"
    prev_1.write_bytes(b"PREVIEW_VERSION_1_BYTES")
    v_mgr.update_preview("test_preview_replace", prev_1, preview_filename="preview.mp4")

    manifest1 = v_mgr.load_manifest("test_preview_replace")
    assert manifest1.active_preview is not None
    assert manifest1.active_preview["size_bytes"] == len(b"PREVIEW_VERSION_1_BYTES")

    # Update with preview v2
    prev_2 = tmp_path / "prev_v2.mp4"
    prev_2.write_bytes(b"PREVIEW_VERSION_2_LONGER_BYTES")
    v_mgr.update_preview("test_preview_replace", prev_2, preview_filename="preview.mp4")

    manifest2 = v_mgr.load_manifest("test_preview_replace")
    assert manifest2.active_preview["size_bytes"] == len(b"PREVIEW_VERSION_2_LONGER_BYTES")

    preview_files = list((v_dir / "preview").glob("*.mp4"))
    assert len(preview_files) == 1
    assert preview_files[0].read_bytes() == b"PREVIEW_VERSION_2_LONGER_BYTES"


def test_update_master_version_retention(temp_video_storage, tmp_path):
    """Verify master replacement archives 1 previous version and enforces QA check gate."""
    v_mgr = temp_video_storage["v_mgr"]
    v_dir = v_mgr.initialize_video_dir("test_master_retention")

    master_v1 = tmp_path / "master_v1.mp4"
    master_v1.write_bytes(b"MASTER_VERSION_1_BYTES")

    # Master update with qc_passed=False must fail
    with pytest.raises(ValueError, match="Quality Checks did not pass"):
        v_mgr.update_master("test_master_retention", master_v1, qc_passed=False)

    # Master v1 initial release
    v_mgr.update_master("test_master_retention", master_v1, qc_passed=True, master_filename="master.mp4")
    m1 = v_mgr.load_manifest("test_master_retention")
    assert m1.active_master["name"] == "master.mp4"
    assert len(m1.retained_previous_masters) == 0

    # Master v2 release
    master_v2 = tmp_path / "master_v2.mp4"
    master_v2.write_bytes(b"MASTER_VERSION_2_BYTES")
    v_mgr.update_master("test_master_retention", master_v2, qc_passed=True, master_filename="master.mp4", max_retained_previous=1)

    m2 = v_mgr.load_manifest("test_master_retention")
    assert m2.active_master["size_bytes"] == len(b"MASTER_VERSION_2_BYTES")
    assert len(m2.retained_previous_masters) == 1
    assert m2.retained_previous_masters[0]["name"] == "master.previous.mp4"

    final_files = {f.name: f.read_bytes() for f in (v_dir / "final").glob("*.mp4")}
    assert "master.mp4" in final_files
    assert final_files["master.mp4"] == b"MASTER_VERSION_2_BYTES"
    assert "master.previous.mp4" in final_files
    assert final_files["master.previous.mp4"] == b"MASTER_VERSION_1_BYTES"


def test_reusable_asset_registry(temp_video_storage, tmp_path):
    """Verify cross-video deduplication registry records unique hashes and links videos."""
    registry = temp_video_storage["registry"]
    test_file = tmp_path / "shared_scene.png"
    test_file.write_bytes(b"SHARED_IMAGE_CONTENT_ABC")

    # Register under video 1
    entry1 = registry.register_file(test_file, asset_type="images", video_id="video_01", canonical=True)
    assert entry1["sha256"] == compute_file_sha256(test_file)
    assert "video_01" in entry1["used_by_videos"]

    # Register same file under video 2
    entry2 = registry.register_file(test_file, asset_type="images", video_id="video_02")
    assert entry2["sha256"] == entry1["sha256"]
    assert "video_01" in entry2["used_by_videos"]
    assert "video_02" in entry2["used_by_videos"]

    summary = registry.get_summary()
    assert summary["total_unique_assets"] == 1


def test_safe_cleanup_dry_run_and_manifest_protection(temp_video_storage, tmp_path):
    """Verify cleanup manager identifies obsolete files while strictly protecting manifest references."""
    output_dir = temp_video_storage["output_dir"]
    cleanup_mgr = temp_video_storage["cleanup_mgr"]
    v_mgr = temp_video_storage["v_mgr"]

    # Initialize a video with a registered asset
    v_dir = v_mgr.initialize_video_dir("video_protected")
    dummy_img = tmp_path / "keep_me.png"
    dummy_img.write_bytes(b"CRUCIAL_APPROVED_ASSET")
    v_mgr.register_asset("video_protected", "images", dummy_img, target_filename="keep_me.png")

    # Create temporary intermediate files that SHOULD be cleaned up
    enh_dir = output_dir / "enhanced_motion_temp"
    enh_dir.mkdir(parents=True, exist_ok=True)
    tmp_concat = enh_dir / "concat_list.txt"
    tmp_concat.write_text("file dummy.mp4", encoding="utf-8")

    tmp_pipe = output_dir / "test_pipe.mp4"
    tmp_pipe.write_bytes(b"")

    # Run dry-run cleanup
    dry_res = cleanup_mgr.run_cleanup(dry_run=True)
    assert dry_res["dry_run"] is True
    assert dry_res["candidates_found"] >= 2
    # Verify files still exist after dry-run
    assert tmp_concat.exists()
    assert tmp_pipe.exists()
    assert (v_dir / "images" / "keep_me.png").exists()

    # Run real cleanup
    exec_res = cleanup_mgr.run_cleanup(dry_run=False)
    assert exec_res["dry_run"] is False
    assert not tmp_concat.exists()
    assert not tmp_pipe.exists()
    # Manifest-referenced file MUST NOT be deleted
    assert (v_dir / "images" / "keep_me.png").exists()


def test_master_deletion_protection(temp_video_storage):
    """Verify master MP4 files cannot be deleted without explicit allow_master_deletion=True."""
    output_dir = temp_video_storage["output_dir"]
    cleanup_mgr = temp_video_storage["cleanup_mgr"]

    fake_final = output_dir / "final"
    fake_final.mkdir(parents=True, exist_ok=True)
    orphan_master = fake_final / "orphan_master.mp4"
    orphan_master.write_bytes(b"ORPHAN_MASTER_VIDEO_BYTES")

    # Running cleanup with allow_master_deletion=False must NOT delete master
    res = cleanup_mgr.run_cleanup(dry_run=False, allow_master_deletion=False, include_superseded_masters=True)
    assert orphan_master.exists()
    skipped_paths = [s["path"] for s in res["skipped_protected"]]
    assert str(orphan_master) in skipped_paths

    # Running cleanup with allow_master_deletion=True can delete orphaned superseded master
    res_allow = cleanup_mgr.run_cleanup(dry_run=False, allow_master_deletion=True, include_superseded_masters=True)
    assert not orphan_master.exists()
    deleted_paths = [s["path"] for s in res_allow["files_deleted"]]
    assert str(orphan_master) in deleted_paths


def test_path_security_guard_enforcement(tmp_path):
    """Verify PathSecurityGuard blocks attempts to delete protected files or out-of-bounds paths."""
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Attempting to delete protected filename like .env must raise ProtectedFileSafetyError
    env_file = out_dir / ".env"
    env_file.write_text("SECRET=123", encoding="utf-8")
    with pytest.raises(ProtectedFileSafetyError):
        PathSecurityGuard.assert_safe_to_delete(env_file, out_dir)

    # Attempting path traversal outside root must raise SecurityPathViolationError
    outside_file = tmp_path / "secrets" / "client_secret.json"
    outside_file.parent.mkdir(parents=True, exist_ok=True)
    outside_file.write_text("{}", encoding="utf-8")
    with pytest.raises(SecurityPathViolationError):
        PathSecurityGuard.assert_safe_to_delete(outside_file, out_dir)


@pytest.mark.skipif(True, reason="Specific live production video output directory excluded from repo")
def test_live_colossal_titan_manifest_integrity():
    """Verify the actual on-disk output/videos/colossal_titan/ directory structure and manifest."""
    manager = VideoFolderManager()
    v_dir = manager.get_video_dir("colossal_titan")
    assert v_dir.exists(), "colossal_titan video directory does not exist!"

    for sub in VideoFolderManager.SUBDIRECTORIES:
        assert (v_dir / sub).is_dir(), f"Missing subfolder {sub}"

    manifest = manager.load_manifest("colossal_titan")
    assert manifest.video_id == "colossal_titan"
    assert manifest.status in ["APPROVED_MASTER", "PUBLISHED_PUBLIC"]

    # Verify active master
    assert manifest.active_master is not None
    master_p = v_dir / manifest.active_master["rel_path"]
    assert master_p.exists()
    assert master_p.stat().st_size == manifest.active_master["size_bytes"]
    assert manifest.active_master["probe"]["duration"] > 30.0

    # Verify active preview
    assert manifest.active_preview is not None
    preview_p = v_dir / manifest.active_preview["rel_path"]
    assert preview_p.exists()
    assert preview_p.stat().st_size < 19 * 1024 * 1024  # Fast-start preview <19MB limit

    # Verify 12 scene images
    scene_images = [img for img in manifest.images if img.get("role") == "scene_image"]
    assert len(scene_images) == 12
    for img in scene_images:
        p = v_dir / img["rel_path"]
        assert p.exists()
        assert p.stat().st_size > 500_000

    # Verify audio
    assert len(manifest.audio) >= 6
    for aud in manifest.audio:
        p = v_dir / aud["rel_path"]
        assert p.exists()

    # Verify script
    assert manifest.script is not None
    script_p = v_dir / manifest.script["rel_path"]
    assert script_p.exists()
