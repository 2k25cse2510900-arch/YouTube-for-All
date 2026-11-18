"""Storage Manager package exports."""

from src.storage_manager.asset_registry import ReusableAssetRegistry
from src.storage_manager.cleanup_manager import SafeCleanupManager
from src.storage_manager.exceptions import (
    ProductionNotFoundError,
    ProtectedFileSafetyError,
    SecurityPathViolationError,
    StorageManagerError,
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
from src.storage_manager.service import StorageManager
from src.storage_manager.verifier import YouTubeUploadVerifier
from src.storage_manager.video_storage import VideoFolderManager, VideoManifest

__all__ = [
    "StorageManager",
    "VideoFolderManager",
    "VideoManifest",
    "SafeCleanupManager",
    "ReusableAssetRegistry",
    "PathSecurityGuard",
    "YouTubeUploadVerifier",
    "ProductionPackage",
    "ProductionAsset",
    "ProductionAssetType",
    "UploadRecord",
    "RetainedMetadata",
    "CleanupReport",
    "UploadStatus",
    "ProcessingStatus",
    "CleanupStatus",
    "StorageManagerError",
    "SecurityPathViolationError",
    "VerificationUncertainError",
    "ProtectedFileSafetyError",
    "ProductionNotFoundError",
]
