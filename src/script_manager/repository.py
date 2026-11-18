"""Repository for storing, indexing, and retrieving scripts."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Dict, List, Optional

from config.settings import get_settings
from src.common.logger import setup_logger
from src.script_manager.exceptions import (
    ScriptDuplicateError,
    ScriptNotFoundError,
)
from src.script_manager.models import ContentCategory, Script, ScriptStatus

logger = setup_logger("script_repository")


class ScriptRepository:
    """Persistent storage engine for scripts in data/processed/."""

    def __init__(self, base_dir: Optional[Path] = None):
        settings = get_settings()
        self.base_dir = Path(base_dir) if base_dir else settings.paths.processed_dir
        self.scripts_dir = self.base_dir / "scripts"
        self.index_file = self.base_dir / "index.json"

        # Ensure directory structure exists
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        self._init_index()

    def _init_index(self) -> None:
        """Initialize index file if not present."""
        if not self.index_file.exists():
            initial_data = {
                "version": "1.0",
                "scripts": {},
                "hashes": {},
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_index(initial_data)

    def _read_index(self) -> Dict:
        """Read current index data."""
        try:
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to read index (%s). Rebuilding from scripts directory.", e)
            return self._rebuild_index()

    def _write_index(self, data: Dict) -> None:
        """Write index data safely."""
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp_file = self.index_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        temp_file.replace(self.index_file)

    def _rebuild_index(self) -> Dict:
        """Rebuild index by scanning scripts_dir."""
        index: Dict = {"version": "1.0", "scripts": {}, "hashes": {}}
        for file in self.scripts_dir.glob("*.json"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    s_data = json.load(f)
                    script = Script(**s_data)
                    index["scripts"][script.id] = {
                        "title": script.title,
                        "category": script.category.value,
                        "status": script.status.value,
                        "content_hash": script.content_hash,
                        "created_at": script.created_at.isoformat(),
                        "updated_at": script.updated_at.isoformat(),
                    }
                    if script.content_hash:
                        index["hashes"][script.content_hash] = script.id
            except Exception as err:
                logger.error("Error reading script file %s during rebuild: %s", file, err)

        self._write_index(index)
        return index

    def save(self, script: Script, allow_update: bool = True) -> Script:
        """Save a new script or update an existing one.

        Prevents duplicate content across different script IDs.
        """
        index = self._read_index()

        # Duplicate hash detection (if same content exists under different ID)
        existing_id_for_hash = index.get("hashes", {}).get(script.content_hash)
        if existing_id_for_hash and existing_id_for_hash != script.id:
            raise ScriptDuplicateError(
                f"Duplicate content detected! Identical script already exists under ID '{existing_id_for_hash}'."
            )

        # Check if updating an existing script
        is_existing = script.id in index.get("scripts", {})
        if is_existing and not allow_update:
            raise ScriptDuplicateError(f"Script with ID '{script.id}' already exists.")

        script.updated_at = datetime.now(timezone.utc)
        file_path = self.scripts_dir / f"{script.id}.json"

        # Persist full script JSON
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(script.model_dump_json(indent=2))

        # Update index
        index["scripts"][script.id] = {
            "title": script.title,
            "category": script.category.value,
            "status": script.status.value,
            "content_hash": script.content_hash,
            "created_at": script.created_at.isoformat(),
            "updated_at": script.updated_at.isoformat(),
        }
        if script.content_hash:
            index["hashes"][script.content_hash] = script.id

        self._write_index(index)
        logger.debug("Saved script '%s' (Status: %s)", script.id, script.status.value)
        return script

    def get(self, script_id: str) -> Optional[Script]:
        """Retrieve script by ID."""
        file_path = self.scripts_dir / f"{script_id}.json"
        if not file_path.exists():
            return None
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return Script(**data)
        except Exception as e:
            logger.error("Failed to parse script file %s: %s", file_path, e)
            return None

    def get_or_raise(self, script_id: str) -> Script:
        """Retrieve script by ID or raise ScriptNotFoundError."""
        script = self.get(script_id)
        if not script:
            raise ScriptNotFoundError(f"Script with ID '{script_id}' not found.")
        return script

    def find_by_hash(self, content_hash: str) -> Optional[Script]:
        """Find a script matching the given content hash."""
        index = self._read_index()
        script_id = index.get("hashes", {}).get(content_hash)
        if script_id:
            return self.get(script_id)
        return None

    def list_all(self) -> List[Script]:
        """List all scripts in the repository."""
        scripts = []
        index = self._read_index()
        for script_id in index.get("scripts", {}).keys():
            script = self.get(script_id)
            if script:
                scripts.append(script)
        return sorted(scripts, key=lambda s: s.created_at)

    def list_by_status(self, status: ScriptStatus) -> List[Script]:
        """List scripts filtered by status."""
        return [s for s in self.list_all() if s.status == status]

    def list_by_category(self, category: ContentCategory) -> List[Script]:
        """List scripts filtered by category."""
        return [s for s in self.list_all() if s.category == category]

    def delete(self, script_id: str) -> bool:
        """Safely delete a script file and remove from index."""
        index = self._read_index()
        file_path = self.scripts_dir / f"{script_id}.json"

        deleted = False
        if file_path.exists():
            file_path.unlink()
            deleted = True

        if script_id in index.get("scripts", {}):
            s_info = index["scripts"].pop(script_id)
            chash = s_info.get("content_hash")
            if chash and chash in index.get("hashes", {}):
                index["hashes"].pop(chash)
            self._write_index(index)
            deleted = True

        return deleted

    def exists(self, script_id: str) -> bool:
        """Check if script ID exists in repository."""
        index = self._read_index()
        return script_id in index.get("scripts", {})

    def count(self) -> int:
        """Total number of scripts stored."""
        index = self._read_index()
        return len(index.get("scripts", {}))
