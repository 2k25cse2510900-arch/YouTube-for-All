"""Custom exceptions for Script Manager."""


class ScriptManagerError(Exception):
    """Base exception for all Script Manager errors."""


class ScriptValidationError(ScriptManagerError):
    """Raised when a script fails validation (schema, category, length)."""


class ScriptDuplicateError(ScriptManagerError):
    """Raised when an ingested script is a duplicate of an existing one."""


class ScriptNotFoundError(ScriptManagerError):
    """Raised when a requested script ID is not found."""


class ScriptApprovalRequiredError(ScriptManagerError):
    """Raised when an unapproved script is selected for production."""


class ScriptAlreadyUsedError(ScriptManagerError):
    """Raised when an already used script is re-queued or re-selected."""


class ScriptStateTransitionError(ScriptManagerError):
    """Raised when an invalid status transition is attempted."""
