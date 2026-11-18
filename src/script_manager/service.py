"""Script Manager orchestrator service for A Lesson With AI."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from config.settings import get_settings
from src.common.logger import setup_logger
from src.script_manager.exceptions import (
    ScriptDuplicateError,
    ScriptManagerError,
    ScriptValidationError,
)
from src.script_manager.models import (
    ContentCategory,
    Script,
    ScriptStatus,
)
from src.script_manager.parser import parse_script_file
from src.script_manager.queue import DailyScriptQueue
from src.script_manager.repository import ScriptRepository

logger = setup_logger("script_manager")


class ScriptManager:
    """Primary service coordinating script ingestion, validation, approval, and queueing."""

    def __init__(
        self,
        repository: Optional[ScriptRepository] = None,
        queue: Optional[DailyScriptQueue] = None,
    ):
        settings = get_settings()
        self.settings = settings
        self.repository = repository or ScriptRepository()
        self.queue = queue or DailyScriptQueue(self.repository)
        self.scripts_dir = settings.paths.scripts_dir

    # --- Ingestion ---

    def ingest_file(self, file_path: Union[str, Path]) -> Script:
        """Parse, validate, and store a single script file."""
        path = Path(file_path)
        logger.info("Ingesting script file: %s", path.name)

        script = parse_script_file(path)

        # Check for duplicates by content hash or ID
        existing = self.repository.find_by_hash(script.content_hash)
        if existing and existing.id != script.id:
            raise ScriptDuplicateError(
                f"Duplicate script! Content in '{path.name}' matches existing script ID '{existing.id}'."
            )

        saved = self.repository.save(script, allow_update=True)
        logger.info("Successfully ingested script '%s' (%s, Status: %s)", saved.id, saved.category.value, saved.status.value)
        return saved

    def ingest_batch(self, directory_path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
        """Scan a directory (default: data/scripts/) and ingest all supported script files."""
        target_dir = Path(directory_path) if directory_path else self.scripts_dir
        logger.info("Scanning for script batch in: %s", target_dir)

        if not target_dir.exists():
            target_dir.mkdir(parents=True, exist_ok=True)

        supported_extensions = [".md", ".json", ".yaml", ".yml", ".txt"]
        files = [
            p for p in target_dir.iterdir()
            if p.is_file() and p.suffix.lower() in supported_extensions and not p.name.startswith(".")
        ]

        results = {
            "total_files_scanned": len(files),
            "ingested": [],
            "skipped_duplicates": [],
            "errors": [],
        }

        for file in sorted(files):
            try:
                script = self.ingest_file(file)
                results["ingested"].append(script.id)
            except ScriptDuplicateError as de:
                logger.warning("Skipping duplicate in %s: %s", file.name, de)
                results["skipped_duplicates"].append({"file": file.name, "reason": str(de)})
            except Exception as err:
                logger.error("Failed to ingest %s: %s", file.name, err)
                results["errors"].append({"file": file.name, "error": str(err)})

        logger.info(
            "Batch ingestion finished: %d ingested, %d duplicates skipped, %d errors.",
            len(results["ingested"]),
            len(results["skipped_duplicates"]),
            len(results["errors"]),
        )
        return results

    # --- Approval & Status Management ---

    def approve_script(self, script_id: str, notes: Optional[str] = None) -> Script:
        """Approve a script for production (Creator Human Approval Gate)."""
        script = self.repository.get_or_raise(script_id)
        script.mark_approved(notes=notes)
        saved = self.repository.save(script)
        logger.info("Human approval granted for script '%s'. Ready for queue.", script_id)
        return saved

    def reject_script(self, script_id: str, reason: Optional[str] = None) -> Script:
        """Reject a script, removing it from production eligibility."""
        script = self.repository.get_or_raise(script_id)
        script.mark_rejected(reason=reason)
        saved = self.repository.save(script)
        logger.info("Script '%s' marked REJECTED. Reason: %s", script_id, reason)
        return saved

    def mark_as_used(self, script_id: str) -> Script:
        """Mark a script as USED following video completion to prevent reuse."""
        return self.queue.mark_completed(script_id)

    def archive_script(self, script_id: str) -> Script:
        """Archive a script."""
        script = self.repository.get_or_raise(script_id)
        script.status = ScriptStatus.ARCHIVED
        return self.repository.save(script)

    # --- Daily Queue & Selection ---

    def get_daily_queue(self, limit: int = 15) -> List[Script]:
        """Retrieve upcoming approved scripts in release queue."""
        return self.queue.get_upcoming_queue(limit=limit)

    def get_next_daily_script(
        self,
        category: Optional[ContentCategory] = None,
        mark_in_production: bool = True,
    ) -> Script:
        """Select next approved script for daily production (1 Short / 24 hours)."""
        return self.queue.select_next_for_production(
            category=category, mark_in_production=mark_in_production
        )

    def peek_next_daily_script(
        self, category: Optional[ContentCategory] = None
    ) -> Optional[Script]:
        """View the next script in line without claiming it."""
        return self.queue.peek_next(category=category)

    # --- Query & Inspection ---

    def get_script(self, script_id: str) -> Optional[Script]:
        """Get script by ID."""
        return self.repository.get(script_id)

    def get_pending_scripts(self) -> List[Script]:
        """List scripts awaiting human approval."""
        return self.repository.list_by_status(ScriptStatus.PENDING_REVIEW)

    def get_approved_scripts(self) -> List[Script]:
        """List scripts that have been approved."""
        return self.repository.list_by_status(ScriptStatus.APPROVED)

    def get_used_scripts(self) -> List[Script]:
        """List scripts that have already been used."""
        return self.repository.list_by_status(ScriptStatus.USED)

    def get_all_scripts(self) -> List[Script]:
        """List all scripts in the system."""
        return self.repository.list_all()

    def update_script(self, script: Script) -> Script:
        """Update an existing script."""
        return self.repository.save(script, allow_update=True)

    def delete_script(self, script_id: str) -> bool:
        """Delete a script from the repository."""
        return self.repository.delete(script_id)

    def get_summary(self) -> Dict[str, Any]:
        """Return high-level summary of script repository and queue state."""
        all_scripts = self.repository.list_all()
        status_counts = {}
        category_counts = {}

        for s in all_scripts:
            status_counts[s.status.value] = status_counts.get(s.status.value, 0) + 1
            category_counts[s.category.value] = category_counts.get(s.category.value, 0) + 1

        upcoming = len(self.queue.get_available_approved_scripts())
        return {
            "total_scripts": len(all_scripts),
            "approved_in_queue": upcoming,
            "days_of_content_ready": upcoming,  # 1 Short / 24h
            "by_status": status_counts,
            "by_category": category_counts,
        }

    # --- Future AI Compatibility Interfaces ---

    def get_approved_exemplars(
        self,
        category: Optional[ContentCategory] = None,
        limit: int = 5,
    ) -> List[Script]:
        """Retrieve approved scripts to serve as few-shot style exemplars for future AI."""
        # Query approved or used scripts (both represent approved creator style)
        candidates = self.repository.list_by_status(ScriptStatus.APPROVED) + self.repository.list_by_status(ScriptStatus.USED)
        if category:
            candidates = [s for s in candidates if s.category == category]

        # Prioritize recent approved scripts
        sorted_candidates = sorted(candidates, key=lambda s: s.approved_at or s.created_at, reverse=True)
        return sorted_candidates[:limit]

    def submit_ai_draft(self, script_data: Any) -> Script:
        """Interface for future AI generator to submit drafts.

        Crucially: AI drafts ALWAYS start in PENDING_REVIEW status and require human approval.
        """
        if isinstance(script_data, Script):
            data = script_data.model_dump()
        else:
            data = dict(script_data)

        # Enforce PENDING_REVIEW regardless of what is passed
        data["status"] = ScriptStatus.PENDING_REVIEW
        data["source_file"] = "ai_generated_draft"

        script = Script(**data)
        saved = self.repository.save(script, allow_update=True)
        logger.info("AI draft submitted under ID '%s'. Placed into PENDING_REVIEW.", saved.id)
        return saved
