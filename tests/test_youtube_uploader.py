"""Offline Unit Tests for YouTube Upload Engine.

Covers Scenarios 21-45+:
- Resumable chunked upload
- OAuth authentication & token refresh
- Error handling (401, 403 quota, 429 rate limit, 5xx, network drops)
- Strict human approval gating and cryptographic integrity verification
- YouTube processing status verification and StorageManager cleanup gating
Strictly offline: all Google API calls are mock-tested.
"""

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from googleapiclient.errors import HttpError
import httplib2

from src.quality_checker.models import CheckSeverity, QualityCheckResult, QualityReport, QualityStatus
from src.storage_manager.models import CleanupStatus, ProcessingStatus, ProductionAssetType, ProductionPackage, UploadStatus
from src.storage_manager.service import StorageManager
from src.storage_manager.verifier import YouTubeUploadVerifier
from src.youtube_uploader.approval import UploadApprovalGate
from src.youtube_uploader.client import YouTubeClientFactory
from src.youtube_uploader.exceptions import (
    ApprovalRequiredError,
    AuthenticationError,
    DuplicateUploadError,
    QuotaExceededError,
    UploadIntegrityError,
    YouTubeUploadError,
)
from src.youtube_uploader.metadata import MetadataBuilder
from src.youtube_uploader.models import (
    PrivacyStatus,
    UploadApprovalRecord,
    UploadMetadata,
    UploadProgress,
    UploadResponse,
)
from src.youtube_uploader.retry import execute_with_retry
from src.youtube_uploader.upload_service import YouTubeUploader
from src.youtube_uploader.verification import RemoteProcessingVerifier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_video_file(tmp_path):
    """Create a sample valid MP4 video on disk."""
    v_path = tmp_path / "final_production_video.mp4"
    v_path.write_bytes(b"\x00\x00\x00\x20ftypmp42\x00\x00\x00\x00dummy_mp4_content_for_upload")
    return v_path


@pytest.fixture
def sample_metadata():
    """Create standard valid YouTube Shorts metadata."""
    return UploadMetadata(
        title="Senku Stone Time Counter",
        description="Factual science of time measurement in Dr. Stone #Shorts",
        tags=["#Shorts", "Science", "Anime"],
        category_id="28",
        default_language="hi",
        default_audio_language="hi",
        privacy_status=PrivacyStatus.PRIVATE,
        made_for_kids=False,
    )


@pytest.fixture
def sample_quality_report():
    """Create a passing QualityReport."""
    return QualityReport(
        production_id="prod_yt_test_01",
        overall_status=QualityStatus.PASS,
        checks=[],
    )


@pytest.fixture
def sample_approval_record(sample_video_file, sample_metadata, sample_quality_report):
    """Create an approved UploadApprovalRecord."""
    return UploadApprovalGate.create_approval_record(
        production_id="prod_yt_test_01",
        video_path=sample_video_file,
        metadata=sample_metadata,
        quality_report=sample_quality_report,
        approver_notes="Human reviewed video and factual Hinglish script. Approved for private upload.",
        requested_privacy=PrivacyStatus.PRIVATE,
    )


@pytest.fixture
def mock_storage_manager(tmp_path):
    """Provide an isolated StorageManager instance with an existing production package."""
    sm = StorageManager(
        base_productions_dir=tmp_path / "storage_root",
        manifest_dir=tmp_path / "manifests",
    )
    pkg = sm.create_production_package("sb_test_storyboard", production_id="prod_yt_test_01")
    return sm


@pytest.fixture
def mock_youtube_client():
    """Create a mock YouTube API client mimicking videos().insert and videos().list."""
    client = MagicMock()

    # Mock insert request and execution
    mock_insert_request = MagicMock()
    # next_chunk returns (status, response)
    # When done, returns (None, {"id": "yt_vid_1234", "snippet": {"title": "..."}, "status": {"uploadStatus": "uploaded"}})
    mock_insert_request.next_chunk.return_value = (
        None,
        {
            "id": "yt_vid_1234",
            "snippet": {"title": "Senku Stone Time Counter"},
            "status": {"uploadStatus": "uploaded", "privacyStatus": "private"},
        },
    )
    client.videos().insert.return_value = mock_insert_request

    # Mock videos().list for processing verification
    mock_list_request = MagicMock()
    mock_list_request.execute.return_value = {
        "items": [
            {
                "id": "yt_vid_1234",
                "snippet": {"title": "Senku Stone Time Counter"},
                "status": {"uploadStatus": "processed", "privacyStatus": "private"},
            }
        ]
    }
    client.videos().list.return_value = mock_list_request

    return client


# ---------------------------------------------------------------------------
# Upload Core & Progress Tests (Scenarios 21 - 22, 30)
# ---------------------------------------------------------------------------

def test_successful_private_upload(
    sample_video_file, sample_metadata, sample_approval_record, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Scenario 21: Verify successful private upload with StorageManager recording."""
    uploader = YouTubeUploader(
        youtube_client=mock_youtube_client,
        storage_manager=mock_storage_manager,
    )

    response = uploader.upload_short(
        production_id="prod_yt_test_01",
        video_path=sample_video_file,
        metadata=sample_metadata,
        approval=sample_approval_record,
        quality_report=sample_quality_report,
    )

    assert response.video_id == "yt_vid_1234"
    assert response.video_url == "https://youtu.be/yt_vid_1234"
    assert response.privacy_status == "private"

    # Confirm StorageManager registered the upload
    pkg = mock_storage_manager.get_package("prod_yt_test_01")
    assert pkg.upload_record.youtube_video_id == "yt_vid_1234"
    assert pkg.upload_record.upload_status in [UploadStatus.UPLOADING, UploadStatus.UPLOADED]


def test_upload_progress_tracking(
    sample_video_file, sample_metadata, sample_approval_record, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Scenario 22 & 30: Multi-chunk resumable upload tracking progress via callback."""
    # Simulate 2 chunks: chunk 1 progress, chunk 2 completion
    mock_status_chunk1 = MagicMock()
    mock_status_chunk1.resumable_progress = 20
    mock_status_chunk1.total_size = 40

    mock_insert_request = MagicMock()
    mock_insert_request.next_chunk.side_effect = [
        (mock_status_chunk1, None),
        (None, {"id": "yt_chunk_test", "snippet": {"title": "Test"}, "status": {"uploadStatus": "uploaded"}}),
    ]
    mock_youtube_client.videos().insert.return_value = mock_insert_request

    progress_events = []

    def progress_callback(p: UploadProgress):
        progress_events.append(p.percentage)

    uploader = YouTubeUploader(
        youtube_client=mock_youtube_client,
        storage_manager=mock_storage_manager,
    )

    response = uploader.upload_short(
        production_id="prod_yt_test_01",
        video_path=sample_video_file,
        metadata=sample_metadata,
        approval=sample_approval_record,
        quality_report=sample_quality_report,
        on_progress=progress_callback,
    )

    assert response.video_id == "yt_chunk_test"
    assert len(progress_events) == 1
    assert progress_events[0] > 0.0


# ---------------------------------------------------------------------------
# Authentication Tests (Scenarios 23 - 24)
# ---------------------------------------------------------------------------

def test_authentication_failure_missing_secret(tmp_path):
    """Scenario 23: Missing client_secret.json raises AuthenticationError."""
    with pytest.raises(AuthenticationError, match="OAuth client secrets file not found"):
        YouTubeClientFactory.get_authenticated_service(
            client_secret_path=tmp_path / "non_existent_secret.json",
            token_path=tmp_path / "token.json",
            interactive=False,
        )


def test_expired_token_handling_refreshes_successfully(tmp_path):
    """Scenario 24: Expired token with refresh_token is refreshed and saved."""
    secret_file = tmp_path / "client_secret.json"
    secret_file.write_text('{"installed": {"client_id": "test", "client_secret": "test"}}', encoding="utf-8")

    token_file = tmp_path / "token.json"
    token_file.write_text('{"token": "old", "refresh_token": "valid_refresh"}', encoding="utf-8")

    mock_creds = MagicMock()
    mock_creds.valid = False
    mock_creds.expired = True
    mock_creds.refresh_token = "valid_refresh"
    mock_creds.to_json.return_value = '{"token": "new_refreshed_token"}'

    with patch("google.oauth2.credentials.Credentials.from_authorized_user_file", return_value=mock_creds), \
         patch("src.youtube_uploader.client.build") as mock_build:
        mock_build.return_value = MagicMock()

        service = YouTubeClientFactory.get_authenticated_service(
            client_secret_path=secret_file,
            token_path=token_file,
            interactive=False,
        )

        assert mock_creds.refresh.called
        assert service is not None


# ---------------------------------------------------------------------------
# Network & HTTP Error Handling (Scenarios 25 - 29, 32 - 33)
# ---------------------------------------------------------------------------

def test_http_401_raises_youtube_upload_error():
    """Scenario 25: HTTP 401 Unauthorized raises AuthenticationError without endless retries."""
    resp = httplib2.Response({"status": "401"})
    err = HttpError(resp, b"Unauthorized")

    def failing_call():
        raise err

    with pytest.raises(AuthenticationError, match="HTTP 401"):
        execute_with_retry(failing_call, max_retries=2, initial_delay=0.01)


def test_http_403_quota_exceeded_raises_immediately():
    """Scenario 33: HTTP 403 with 'quotaExceeded' raises QuotaExceededError on first attempt."""
    resp = httplib2.Response({"status": "403"})
    err = HttpError(resp, b"The request cannot be completed because you have exceeded your quotaExceeded.")

    call_count = 0
    def failing_call():
        nonlocal call_count
        call_count += 1
        raise err

    with pytest.raises(QuotaExceededError, match="YouTube API daily quota exceeded"):
        execute_with_retry(failing_call, max_retries=3, initial_delay=0.01)

    assert call_count == 1  # Never retried!


def test_http_429_rate_limit_retries_and_recovers():
    """Scenario 27: HTTP 429 rate limit is retried with backoff and succeeds on retry."""
    resp_429 = httplib2.Response({"status": "429"})
    err_429 = HttpError(resp_429, b"Too Many Requests")

    attempts = 0
    def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise err_429
        return "success_recovered"

    result = execute_with_retry(flaky_call, max_retries=3, initial_delay=0.01)
    assert result == "success_recovered"
    assert attempts == 2


def test_server_500_error_retries_and_recovers():
    """Scenario 28: HTTP 500 server error retries and succeeds."""
    resp_500 = httplib2.Response({"status": "500"})
    err_500 = HttpError(resp_500, b"Internal Server Error")

    attempts = 0
    def flaky_call():
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise err_500
        return "server_recovered"

    result = execute_with_retry(flaky_call, max_retries=3, initial_delay=0.01)
    assert result == "server_recovered"
    assert attempts == 2


def test_network_interruption_retries():
    """Scenario 29: ConnectionError is retried and succeeds."""
    attempts = 0
    def flaky_net():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("Network interface reset")
        return "connection_restored"

    result = execute_with_retry(flaky_net, max_retries=3, initial_delay=0.01)
    assert result == "connection_restored"
    assert attempts == 2


def test_unknown_upload_outcome_records_failure_in_storage(
    sample_video_file, sample_metadata, sample_approval_record, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Scenario 32: Incomplete or malformed API response records failure in StorageManager."""
    mock_insert_request = MagicMock()
    # Response without "id"
    mock_insert_request.next_chunk.return_value = (None, {"kind": "youtube#video"})
    mock_youtube_client.videos().insert.return_value = mock_insert_request

    uploader = YouTubeUploader(youtube_client=mock_youtube_client, storage_manager=mock_storage_manager)

    with pytest.raises(YouTubeUploadError, match="incomplete response without video ID"):
        uploader.upload_short(
            production_id="prod_yt_test_01",
            video_path=sample_video_file,
            metadata=sample_metadata,
            approval=sample_approval_record,
            quality_report=sample_quality_report,
        )

    pkg = mock_storage_manager.get_package("prod_yt_test_01")
    assert pkg.upload_record.upload_status == UploadStatus.FAILED
    assert pkg.upload_record.cleanup_status == CleanupStatus.PRESERVED


# ---------------------------------------------------------------------------
# Duplicate Upload Prevention (Scenario 31)
# ---------------------------------------------------------------------------

def test_duplicate_upload_prevention(
    sample_video_file, sample_metadata, sample_approval_record, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Scenario 31: Attempting to re-upload an already uploaded production raises DuplicateUploadError."""
    pkg = mock_storage_manager.get_package("prod_yt_test_01")
    pkg.upload_record.upload_status = UploadStatus.UPLOADED
    pkg.upload_record.youtube_video_id = "yt_already_uploaded"
    mock_storage_manager._save_package(pkg)

    uploader = YouTubeUploader(youtube_client=mock_youtube_client, storage_manager=mock_storage_manager)

    with pytest.raises(DuplicateUploadError, match="already been uploaded with Video ID 'yt_already_uploaded'"):
        uploader.upload_short(
            production_id="prod_yt_test_01",
            video_path=sample_video_file,
            metadata=sample_metadata,
            approval=sample_approval_record,
            quality_report=sample_quality_report,
        )


# ---------------------------------------------------------------------------
# Human Approval & Security Integrity Gating (Scenarios 34 - 39)
# ---------------------------------------------------------------------------

def test_missing_human_approval_blocks_upload(
    sample_video_file, sample_metadata, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Scenario 35: Upload attempt with approval=None raises ApprovalRequiredError."""
    uploader = YouTubeUploader(youtube_client=mock_youtube_client, storage_manager=mock_storage_manager)

    with pytest.raises(ApprovalRequiredError, match="No human approval record provided"):
        uploader.upload_short(
            production_id="prod_yt_test_01",
            video_path=sample_video_file,
            metadata=sample_metadata,
            approval=None,  # Missing approval
            quality_report=sample_quality_report,
        )


def test_changed_video_after_approval_fails_integrity(
    sample_video_file, sample_metadata, sample_approval_record, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Scenario 36: Modifying the video file after approval raises UploadIntegrityError."""
    uploader = YouTubeUploader(youtube_client=mock_youtube_client, storage_manager=mock_storage_manager)

    # Mutate video bytes after approval
    sample_video_file.write_bytes(b"tampered_bytes_after_human_sign_off")

    with pytest.raises(UploadIntegrityError, match="Video file was modified after approval"):
        uploader.upload_short(
            production_id="prod_yt_test_01",
            video_path=sample_video_file,
            metadata=sample_metadata,
            approval=sample_approval_record,
            quality_report=sample_quality_report,
        )


def test_changed_metadata_after_approval_fails_integrity(
    sample_video_file, sample_metadata, sample_approval_record, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Scenario 37: Modifying metadata after approval raises UploadIntegrityError."""
    uploader = YouTubeUploader(youtube_client=mock_youtube_client, storage_manager=mock_storage_manager)

    # Mutate metadata after approval
    tampered_metadata = sample_metadata.model_copy(update={"title": "Completely Different Title"})

    with pytest.raises(UploadIntegrityError, match="Upload metadata was modified after approval"):
        uploader.upload_short(
            production_id="prod_yt_test_01",
            video_path=sample_video_file,
            metadata=tampered_metadata,
            approval=sample_approval_record,
            quality_report=sample_quality_report,
        )


def test_public_upload_blocked_by_default(sample_metadata):
    """Scenario 38: Requesting public upload without allow_public=True raises YouTubeUploadError."""
    public_metadata = sample_metadata.model_copy(update={"privacy_status": PrivacyStatus.PUBLIC})

    with pytest.raises(YouTubeUploadError, match="Public upload blocked by security safeguard"):
        MetadataBuilder.build_resource_payload(public_metadata, allow_public=False)

    # When allow_public=True, it succeeds
    payload = MetadataBuilder.build_resource_payload(public_metadata, allow_public=True)
    assert payload["status"]["privacyStatus"] == "public"


# ---------------------------------------------------------------------------
# YouTube Processing Verification & Storage Cleanup Gating (Scenarios 40 - 45)
# ---------------------------------------------------------------------------

def test_youtube_processing_verification_success(mock_youtube_client):
    """Scenario 40: Processing state 'processed' returns success and details."""
    verifier = RemoteProcessingVerifier(poll_interval_seconds=0.01, max_timeout_seconds=1.0)
    is_processed, status, details = verifier.wait_until_processed("yt_vid_1234", mock_youtube_client)

    assert is_processed is True
    assert status == ProcessingStatus.PROCESSED
    assert details["upload_status"] == "processed"


def test_youtube_processing_verification_failure(mock_youtube_client):
    """Scenario 41: Processing state 'rejected' or 'failed' returns False."""
    mock_list_request = MagicMock()
    mock_list_request.execute.return_value = {
        "items": [
            {
                "id": "yt_vid_1234",
                "status": {"uploadStatus": "rejected", "rejectionReason": "copyright"},
            }
        ]
    }
    mock_youtube_client.videos().list.return_value = mock_list_request

    verifier = RemoteProcessingVerifier(poll_interval_seconds=0.01, max_timeout_seconds=1.0)
    is_processed, status, details = verifier.wait_until_processed("yt_vid_1234", mock_youtube_client)

    assert is_processed is False
    assert status == ProcessingStatus.FAILED
    assert details["upload_status"] == "rejected"


def test_youtube_processing_verification_timeout(mock_youtube_client):
    """Scenario 42: Continuous 'processing' state times out gracefully without raising."""
    mock_list_request = MagicMock()
    mock_list_request.execute.return_value = {
        "items": [
            {
                "id": "yt_vid_1234",
                "status": {"uploadStatus": "processing"},
            }
        ]
    }
    mock_youtube_client.videos().list.return_value = mock_list_request

    verifier = RemoteProcessingVerifier(poll_interval_seconds=0.01, max_timeout_seconds=0.05)
    is_processed, status, details = verifier.wait_until_processed("yt_vid_1234", mock_youtube_client)

    assert is_processed is False
    assert status == ProcessingStatus.PROCESSING
    assert "Verification timeout" in details.get("error", "")


def test_storage_cleanup_blocked_when_verification_uncertain(mock_storage_manager, mock_youtube_client):
    """Scenario 44: When verification is uncertain, StorageManager preserves all local files."""
    pkg = mock_storage_manager.get_package("prod_yt_test_01")
    pkg.upload_record.upload_status = UploadStatus.UPLOADED
    pkg.upload_record.youtube_video_id = "yt_vid_1234"
    mock_storage_manager._save_package(pkg)

    # Simulate network exception during verification
    mock_youtube_client.videos().list.side_effect = ConnectionError("Timeout contacting YouTube")

    report = mock_storage_manager.verify_and_cleanup(
        production_id="prod_yt_test_01",
        youtube_client=mock_youtube_client,
    )

    assert report.eligible is False
    assert report.status == CleanupStatus.PRESERVED


def test_storage_cleanup_allowed_only_after_verified_processing(mock_storage_manager, mock_youtube_client):
    """Scenario 45: Cleanup proceeds and deletes temporary files only after status is PROCESSED."""
    pkg = mock_storage_manager.get_package("prod_yt_test_01")
    pkg.upload_record.upload_status = UploadStatus.UPLOADED
    pkg.upload_record.youtube_video_id = "yt_vid_1234"
    mock_storage_manager._save_package(pkg)

    # Create dummy temp asset file in package
    temp_file = Path(pkg.root_dir) / "video" / "final_test.mp4"
    temp_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file.write_bytes(b"temporary_video_render_bytes")
    mock_storage_manager.register_asset("prod_yt_test_01", ProductionAssetType.FINAL_VIDEO, temp_file)

    # Remote status is processed
    mock_list_request = MagicMock()
    mock_list_request.execute.return_value = {
        "items": [
            {
                "id": "yt_vid_1234",
                "status": {"uploadStatus": "processed", "privacyStatus": "private"},
                "snippet": {"title": "Verified Title"},
            }
        ]
    }
    mock_youtube_client.videos().list.return_value = mock_list_request

    report = mock_storage_manager.verify_and_cleanup(
        production_id="prod_yt_test_01",
        youtube_client=mock_youtube_client,
        dry_run=False,
    )

    assert report.eligible is True
    assert report.status == CleanupStatus.CLEANED
    # Assert temp file was deleted
    assert not temp_file.exists()


def test_warning_in_quality_report_requires_explicit_acceptance(sample_video_file, sample_metadata):
    """Quality report with warnings requires accept_warnings=True for human approval."""
    warn_report = QualityReport(
        production_id="prod_yt_warn_01",
        overall_status=QualityStatus.WARNING,
        checks=[
            QualityCheckResult(
                check_name="audio_clipping_detection",
                category="audio",
                status=QualityStatus.WARNING,
                severity=CheckSeverity.WARNING,
                message="Potential clipping at 0.0 dB",
            )
        ],
    )

    # 1. Without accept_warnings -> raises ApprovalRequiredError
    with pytest.raises(ApprovalRequiredError, match="unacknowledged warning"):
        UploadApprovalGate.create_approval_record(
            production_id="prod_yt_warn_01",
            video_path=sample_video_file,
            metadata=sample_metadata,
            quality_report=warn_report,
            approver_notes="Approved",
            accept_warnings=False,
        )

    # 2. With accept_warnings=True -> succeeds and records accepted_warnings
    record = UploadApprovalGate.create_approval_record(
        production_id="prod_yt_warn_01",
        video_path=sample_video_file,
        metadata=sample_metadata,
        quality_report=warn_report,
        approver_notes="Approved with warning acknowledged",
        accept_warnings=True,
    )
    assert len(record.accepted_warnings) == 1
    assert "Potential clipping at 0.0 dB" in record.accepted_warnings[0]


def test_approval_ttl_expiration_blocks_upload(sample_video_file, sample_metadata, sample_quality_report):
    """Expired approval record (> approval_ttl_hours) fails integrity validation."""
    record = UploadApprovalGate.create_approval_record(
        production_id="prod_yt_ttl_01",
        video_path=sample_video_file,
        metadata=sample_metadata,
        quality_report=sample_quality_report,
        approver_notes="Approved long ago",
        approval_ttl_hours=24,
    )

    # Backdate approved_at past 24 hours
    record.approved_at = datetime.now(timezone.utc) - timedelta(hours=25)

    is_valid, reason = record.verify_integrity(sample_video_file, sample_metadata)
    assert is_valid is False
    assert "Approval record has expired" in reason


def test_concurrent_upload_in_flight_blocks_duplicate(
    sample_video_file, sample_metadata, sample_approval_record, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Production already in UPLOADING state blocks another concurrent upload attempt."""
    pkg = mock_storage_manager.get_package("prod_yt_test_01")
    pkg.upload_record.upload_status = UploadStatus.UPLOADING
    mock_storage_manager._save_package(pkg)

    uploader = YouTubeUploader(youtube_client=mock_youtube_client, storage_manager=mock_storage_manager)

    with pytest.raises(DuplicateUploadError, match="Concurrent upload blocked"):
        uploader.upload_short(
            production_id="prod_yt_test_01",
            video_path=sample_video_file,
            metadata=sample_metadata,
            approval=sample_approval_record,
            quality_report=sample_quality_report,
        )


def test_uncertain_status_blocks_duplicate_upload(
    sample_video_file, sample_metadata, sample_approval_record, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Production in UNCERTAIN state blocks re-upload until explicitly resolved."""
    pkg = mock_storage_manager.get_package("prod_yt_test_01")
    pkg.upload_record.upload_status = UploadStatus.UNCERTAIN
    mock_storage_manager._save_package(pkg)

    uploader = YouTubeUploader(youtube_client=mock_youtube_client, storage_manager=mock_storage_manager)

    with pytest.raises(DuplicateUploadError, match="UNCERTAIN state"):
        uploader.upload_short(
            production_id="prod_yt_test_01",
            video_path=sample_video_file,
            metadata=sample_metadata,
            approval=sample_approval_record,
            quality_report=sample_quality_report,
        )


def test_network_disconnect_during_upload_sets_uncertain_status(
    sample_video_file, sample_metadata, sample_approval_record, sample_quality_report, mock_storage_manager, mock_youtube_client
):
    """Network connection drop during chunk streaming sets status to UNCERTAIN and preserves files."""
    mock_insert_request = MagicMock()
    mock_insert_request.resumable_uri = "https://youtube.googleapis.com/upload/session/test_session_1234"
    mock_insert_request.next_chunk.side_effect = ConnectionResetError("Remote host reset connection")
    mock_youtube_client.videos().insert.return_value = mock_insert_request

    uploader = YouTubeUploader(youtube_client=mock_youtube_client, storage_manager=mock_storage_manager)

    with pytest.raises(YouTubeUploadError, match="failed after 3 network attempts"):
        uploader.upload_short(
            production_id="prod_yt_test_01",
            video_path=sample_video_file,
            metadata=sample_metadata,
            approval=sample_approval_record,
            quality_report=sample_quality_report,
        )

    pkg = mock_storage_manager.get_package("prod_yt_test_01")
    assert pkg.upload_record.upload_status == UploadStatus.UNCERTAIN
    assert pkg.upload_record.cleanup_status == CleanupStatus.PRESERVED
    assert "uncertain" in pkg.upload_record.error_message.lower()
