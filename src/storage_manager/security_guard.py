"""Security guard preventing accidental or unauthorized file deletions."""

from pathlib import Path
from typing import Set

from config.settings import get_settings
from src.common.logger import setup_logger
from src.storage_manager.exceptions import (
    ProtectedFileSafetyError,
    SecurityPathViolationError,
)

logger = setup_logger("storage_security_guard")


class PathSecurityGuard:
    """Enforces strict file deletion boundaries and protects irreplaceable assets.

    PROTECTED PATHS (NEVER DELETED):
    - Raw user scripts (data/scripts/)
    - Processed scripts repository (data/processed/scripts/)
    - Approved storyboards (data/processed/storyboards/)
    - Research dossiers (data/processed/research/)
    - Upload history & storage manifests (data/processed/storage/)
    - Secrets, credentials, tokens (secrets/, token.json, client_secret.json, .env)
    - Source code & configuration (src/, config/, tests/, .git/, .venv/)
    """

    PROTECTED_EXTENSIONS: Set[str] = {
        ".py",
        ".env",
        ".key",
        ".pem",
    }

    PROTECTED_FILENAMES: Set[str] = {
        "client_secret.json",
        "token.json",
        ".env",
        ".env.example",
        "index.json",
        "upload_history.json",
        "README.md",
        ".gitkeep",
    }

    @classmethod
    def assert_safe_to_delete(cls, target_path: Path, allowed_root: Path) -> None:
        """Validate that a target file is strictly safe and permitted for deletion."""
        settings = get_settings()
        target = Path(target_path).resolve()
        root = Path(allowed_root).resolve()

        project_root = settings.paths.project_root.resolve()
        output_root = settings.paths.output_dir.resolve()

        # 1. Enforce that the allowed_root itself is inside output_dir or a temporary test directory
        # (Must never allow passing project root, data/scripts, or system folders as root)
        is_in_output = root == output_root or output_root in root.parents
        # Allow pytest temporary directories in tests (e.g. tmp_path)
        is_in_temp = "pytest" in str(root).lower() or "temp" in str(root).lower() or "tmp" in str(root).lower()

        if not (is_in_output or is_in_temp):
            msg = (
                f"SECURITY VIOLATION: Root folder '{root}' is outside designated output directories. "
                f"Deletion is restricted exclusively to output/ or temporary staging paths."
            )
            logger.critical(msg)
            raise SecurityPathViolationError(msg)

        # 2. Enforce that the target is strictly inside allowed_root
        try:
            target.relative_to(root)
        except ValueError:
            msg = (
                f"SECURITY VIOLATION: Target file '{target}' is not within the production folder '{root}'. "
                f"Path traversal or out-of-bounds deletion attempt detected."
            )
            logger.critical(msg)
            raise SecurityPathViolationError(msg)

        # 3. Check for protected file names
        if target.name in cls.PROTECTED_FILENAMES:
            msg = f"PROTECTION ERROR: File '{target.name}' is an essential project asset and must NEVER be deleted."
            logger.critical(msg)
            raise ProtectedFileSafetyError(msg)

        # 4. Check for protected file extensions
        if target.suffix.lower() in cls.PROTECTED_EXTENSIONS:
            msg = f"PROTECTION ERROR: Files with extension '{target.suffix}' are protected code or configuration."
            logger.critical(msg)
            raise ProtectedFileSafetyError(msg)

        # 5. Check against protected directory segments
        target_str = str(target).replace("\\", "/").lower()
        protected_segments = [
            "/data/scripts",
            "/data/processed/scripts",
            "/data/processed/storyboards",
            "/data/processed/research",
            "/data/processed/storage",
            "/secrets",
            "/src/",
            "/config/",
            "/.git",
            "/.venv",
        ]
        for seg in protected_segments:
            if seg in target_str:
                msg = f"PROTECTION ERROR: Target '{target}' is inside protected directory '{seg}'. Deletion strictly forbidden."
                logger.critical(msg)
                raise ProtectedFileSafetyError(msg)

        logger.debug("PathSecurityGuard approved deletion safety for '%s'", target.name)
