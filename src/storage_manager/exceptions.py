"""Exceptions for Storage Management and Automatic Cleanup."""


class StorageManagerError(Exception):
    """Base exception for Storage Manager errors."""

    pass


class SecurityPathViolationError(StorageManagerError):
    """Raised when an operation attempts to access or delete files outside permitted directories."""

    pass


class VerificationUncertainError(StorageManagerError):
    """Raised when YouTube upload status or processing state cannot be verified with certainty."""

    pass


class ProtectedFileSafetyError(StorageManagerError):
    """Raised when an operation attempts to modify or delete protected files (scripts, dossiers, tokens)."""

    pass


class ProductionNotFoundError(StorageManagerError):
    """Raised when a specified production package is not found."""

    pass


class DuplicateUploadError(StorageManagerError):
    """Raised when an upload is attempted on a production package that is already uploading, uploaded, or uncertain."""

    pass
