"""Foundation tests verifying project configuration, directory structure, and modules."""

import importlib
from pathlib import Path

from config.settings import get_settings
from src.common.logger import setup_logger


def test_settings_defaults():
    """Verify default configuration safeguards."""
    settings = get_settings()

    # Publishing safeguards
    assert settings.publishing.require_human_approval is True
    assert settings.publishing.publish_interval_hours == 24
    assert settings.publishing.default_privacy_status == "private"

    # Shorts video specifications
    assert settings.video.width == 1080
    assert settings.video.height == 1920
    assert settings.video.fps == 30
    assert settings.video.max_duration_seconds == 60


def test_directory_structure_exists():
    """Verify that all architectural project directories exist."""
    settings = get_settings()
    root = settings.paths.project_root

    required_dirs = [
        root / "config",
        root / "data" / "scripts",
        root / "data" / "processed",
        root / "src" / "script_manager",
        root / "src" / "video_generator",
        root / "src" / "audio_generator",
        root / "src" / "caption_generator",
        root / "src" / "video_editor",
        root / "src" / "quality_checker",
        root / "src" / "youtube_uploader",
        root / "src" / "comment_manager",
        root / "src" / "analytics",
        root / "src" / "common",
        root / "output" / "videos",
        root / "output" / "thumbnails",
        root / "logs",
        root / "tests",
    ]

    for directory in required_dirs:
        assert directory.exists(), f"Missing required directory: {directory}"
        assert directory.is_dir(), f"Expected directory but found file: {directory}"


def test_submodules_importable():
    """Verify all architectural packages import without error."""
    modules = [
        "config.settings",
        "src.common",
        "src.common.logger",
        "src.script_manager",
        "src.research_engine",
        "src.storyboard_generator",
        "src.video_generator",
        "src.audio_generator",
        "src.caption_generator",
        "src.video_editor",
        "src.quality_checker",
        "src.youtube_uploader",
        "src.comment_manager",
        "src.analytics",
    ]

    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        assert mod is not None, f"Failed to import {mod_name}"


import pytest

@pytest.mark.skipif(
    not get_settings().paths.client_secret_file.exists(),
    reason="OAuth client secret is excluded from public open-source repository",
)
def test_secrets_and_credentials_preserved():
    """Verify OAuth credentials and tokens exist without exposing contents."""
    settings = get_settings()

    assert settings.paths.client_secret_file.exists(), (
        "secrets/client_secret.json missing!"
    )
    assert settings.paths.token_file.exists(), "token.json missing!"


def test_logger_initialization(tmp_path):
    """Verify logger setup."""
    logger = setup_logger("test_foundation_logger")
    assert logger is not None
    assert logger.name == "test_foundation_logger"


def test_type_annotations_evaluate_cleanly():
    """Regression test: verify key critical services have valid type annotations without NameError."""
    import typing
    import src.youtube_uploader.approval
    import src.storyboard_generator.pacing
    import src.storyboard_generator.prompts

    hints_app = typing.get_type_hints(src.youtube_uploader.approval.UploadApprovalGate.create_approval_record)
    assert "script" in hints_app

    hints_pace = typing.get_type_hints(src.storyboard_generator.pacing.check_narration_duration_limits)
    assert "return" in hints_pace

    hints_prompt = typing.get_type_hints(src.storyboard_generator.prompts.build_storyboard_from_script_prompt)
    assert "script" in hints_prompt
