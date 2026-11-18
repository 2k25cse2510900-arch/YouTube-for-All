"""Daily script release queue and used-script tracking."""

from typing import List, Optional

from config.settings import get_settings
from src.common.logger import setup_logger
from src.script_manager.exceptions import (
    ScriptAlreadyUsedError,
    ScriptApprovalRequiredError,
)
from src.script_manager.models import ContentCategory, Script, ScriptStatus
from src.script_manager.repository import ScriptRepository

logger = setup_logger("script_queue")


class DailyScriptQueue:
    """Manages the daily production release queue and safeguards."""

    def __init__(self, repository: ScriptRepository):
        self.repository = repository
        self.settings = get_settings()

    def get_available_approved_scripts(
        self, category: Optional[ContentCategory] = None
    ) -> List[Script]:
        """Return all approved scripts that have not been used or archived."""
        approved_scripts = self.repository.list_by_status(ScriptStatus.APPROVED)

        if category:
            approved_scripts = [s for s in approved_scripts if s.category == category]

        # Sort by creation time (FIFO)
        return sorted(approved_scripts, key=lambda s: s.created_at)

    def get_upcoming_queue(self, limit: int = 15) -> List[Script]:
        """View upcoming queue of approved scripts ready for production."""
        return self.get_available_approved_scripts()[:limit]

    def peek_next(
        self, category: Optional[ContentCategory] = None
    ) -> Optional[Script]:
        """Inspect the next script in line without modifying its state."""
        available = self.get_available_approved_scripts(category=category)
        return available[0] if available else None

    def select_next_for_production(
        self,
        category: Optional[ContentCategory] = None,
        mark_in_production: bool = True,
    ) -> Script:
        """Select the next approved script for daily production.

        Enforces:
        1. Human Approval Gate: Unapproved scripts cannot be selected.
        2. Duplicate Prevention: Used scripts cannot be selected.
        """
        available = self.get_available_approved_scripts(category=category)

        if not available:
            # Check if there are scripts pending review
            pending = self.repository.list_by_status(ScriptStatus.PENDING_REVIEW)
            if pending:
                raise ScriptApprovalRequiredError(
                    f"No approved scripts available for production! "
                    f"There are {len(pending)} script(s) waiting for human approval."
                )
            raise RuntimeError(
                "No scripts available in the daily queue! Please provide a new batch in data/scripts/."
            )

        script = available[0]

        # Double safeguard on human approval
        if self.settings.publishing.require_human_approval and script.status != ScriptStatus.APPROVED:
            raise ScriptApprovalRequiredError(
                f"Human approval safeguard blocked script '{script.id}'. Status is {script.status.value}."
            )

        # Double safeguard on used scripts
        if script.status == ScriptStatus.USED:
            raise ScriptAlreadyUsedError(
                f"Duplicate prevention safeguard triggered: Script '{script.id}' was already used."
            )

        if mark_in_production:
            script.status = ScriptStatus.IN_PRODUCTION
            self.repository.save(script)
            logger.info("Script '%s' transitioned to IN_PRODUCTION.", script.id)

        return script

    def mark_completed(self, script_id: str) -> Script:
        """Mark a script as USED once its video has completed production/publishing."""
        script = self.repository.get_or_raise(script_id)
        if script.status == ScriptStatus.USED:
            raise ScriptAlreadyUsedError(f"Script '{script_id}' is already marked as USED.")

        script.mark_used()
        self.repository.save(script)
        logger.info("Script '%s' marked as USED. It will not be selected again.", script_id)
        return script
