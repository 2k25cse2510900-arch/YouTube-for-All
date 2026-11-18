"""Script Manager Module.

Responsibilities:
- Ingest and parse manual batch scripts (10–15 day batches) from `data/scripts/`.
- Validate script formatting, timing constraints, and scene breakdowns.
- Maintain selection queue and state for daily Short selection (1 Short / 24 hours).
- Archive and prepare approved scripts into `data/processed/`.
- In future phases: Provide training and preference signals for the AI script generator.
"""

from src.script_manager.exceptions import (
    ScriptAlreadyUsedError,
    ScriptApprovalRequiredError,
    ScriptDuplicateError,
    ScriptManagerError,
    ScriptNotFoundError,
    ScriptStateTransitionError,
    ScriptValidationError,
)
from src.script_manager.models import (
    ContentCategory,
    ResearchReference,
    SceneBreakdown,
    Script,
    ScriptStatus,
)
from src.script_manager.parser import parse_script_file
from src.script_manager.queue import DailyScriptQueue
from src.script_manager.repository import ScriptRepository
from src.script_manager.service import ScriptManager

__all__ = [
    "ScriptManager",
    "ScriptRepository",
    "DailyScriptQueue",
    "Script",
    "ContentCategory",
    "ScriptStatus",
    "SceneBreakdown",
    "ResearchReference",
    "parse_script_file",
    "ScriptManagerError",
    "ScriptValidationError",
    "ScriptDuplicateError",
    "ScriptNotFoundError",
    "ScriptApprovalRequiredError",
    "ScriptAlreadyUsedError",
    "ScriptStateTransitionError",
]

