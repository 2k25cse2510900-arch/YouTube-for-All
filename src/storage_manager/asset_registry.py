"""Global reusable asset registry for cross-video deduplication and storage efficiency."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from config.settings import get_settings
from src.common.logger import setup_logger

logger = setup_logger("asset_registry")


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 for asset file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class ReusableAssetRegistry:
    """Tracks unique asset hashes across all video productions to prevent duplication and save storage."""

    def __init__(self, registry_file: Optional[Path] = None):
        settings = get_settings()
        self.registry_file = Path(
            registry_file or (settings.paths.storage_manifest_dir / "asset_registry.json")
        )
        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        self.index: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.registry_file.exists():
            try:
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    self.index = json.load(f)
            except Exception as e:
                logger.warning("Could not read asset registry from %s: %s", self.registry_file, e)
                self.index = {}
        else:
            self.index = {}

    def _save(self) -> None:
        tmp_file = self.registry_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, indent=2)
        if self.registry_file.exists():
            self.registry_file.unlink()
        tmp_file.rename(self.registry_file)

    def register_file(
        self,
        file_path: Path,
        asset_type: str,
        video_id: Optional[str] = None,
        canonical: bool = False,
    ) -> Dict[str, Any]:
        """Register a file in the global index by SHA-256 checksum."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Cannot register non-existent file: {path}")

        sha256 = compute_sha256(path)
        st = path.stat()
        settings = get_settings()
        try:
            rel_path = str(path.relative_to(settings.paths.project_root)).replace("\\", "/")
        except ValueError:
            rel_path = str(path).replace("\\", "/")

        if sha256 in self.index:
            entry = self.index[sha256]
            if video_id and video_id not in entry.get("used_by_videos", []):
                entry.setdefault("used_by_videos", []).append(video_id)
            if canonical:
                entry["canonical_path"] = rel_path
            entry["last_referenced"] = datetime.now(timezone.utc).isoformat()
            self._save()
            return entry

        entry = {
            "sha256": sha256,
            "canonical_path": rel_path,
            "asset_type": asset_type,
            "size_bytes": st.st_size,
            "size_mb": round(st.st_size / (1024 * 1024), 3),
            "used_by_videos": [video_id] if video_id else [],
            "first_registered": datetime.now(timezone.utc).isoformat(),
            "last_referenced": datetime.now(timezone.utc).isoformat(),
        }
        self.index[sha256] = entry
        self._save()
        return entry

    def find_by_hash(self, sha256: str) -> Optional[Dict[str, Any]]:
        """Find an asset entry by its SHA-256 hash."""
        return self.index.get(sha256)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary metrics of registered unique assets."""
        total_unique_assets = len(self.index)
        total_unique_bytes = sum(item.get("size_bytes", 0) for item in self.index.values())
        types_breakdown: Dict[str, int] = {}
        for item in self.index.values():
            t = item.get("asset_type", "unknown")
            types_breakdown[t] = types_breakdown.get(t, 0) + 1

        return {
            "total_unique_assets": total_unique_assets,
            "total_unique_bytes": total_unique_bytes,
            "total_unique_mb": round(total_unique_bytes / (1024 * 1024), 2),
            "asset_types": types_breakdown,
        }
