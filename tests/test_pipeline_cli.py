"""Tests for Pipeline Orchestrator CLI commands and argument routing."""

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.pipeline.cli import (
    handle_list,
    handle_render,
    handle_status,
    handle_validate,
    main,
)


def test_cli_list_command(capsys):
    """Confirm pipeline list prints tracked productions without error."""
    args = argparse.Namespace(json=False)
    code = handle_list(args)
    assert code == 0
    captured = capsys.readouterr()
    assert ("Total Productions:" in captured.out or "No pipeline productions found" in captured.out)


def test_cli_status_unknown_production(capsys):
    """Confirm pipeline status for unknown ID returns error code 1."""
    args = argparse.Namespace(production_id="prod_non_existent_123", json=False)
    code = handle_status(args)
    assert code == 1
    captured = capsys.readouterr()
    assert "not found" in captured.out


@pytest.mark.skipif(not Path("data/processed/pipeline/prod_sb_anime_the_square-cube_law_and_t_corrected_5scenes_20261115_130725_f9a417_state.json").exists(), reason="Production state files excluded from repo")
def test_cli_validate_calls_gate_validator_without_attribute_error(capsys):
    """Confirm pipeline validate runs Gate C inspection without AttributeError."""
    prod_id = "prod_sb_anime_the_square-cube_law_and_t_corrected_5scenes_20261115_130725_f9a417"
    args = argparse.Namespace(production_id=prod_id)
    code = handle_validate(args)
    assert code == 0
    captured = capsys.readouterr()
    assert "Visual Asset Readiness:" in captured.out
    assert ("Ready for Video: **YES**" in captured.out or "Pending Approval" in captured.out)
    assert "Pipeline Production Report" in captured.out


@pytest.mark.skipif(not Path("data/processed/pipeline/prod_sb_anime_the_square-cube_law_and_t_corrected_5scenes_20261115_130725_f9a417_state.json").exists(), reason="Production state files excluded from repo")
def test_cli_render_blocks_missing_voiceover(capsys, monkeypatch):
    """Confirm pipeline render cleanly blocks when voiceover audio is missing instead of TypeError."""
    prod_id = "prod_sb_anime_the_square-cube_law_and_t_corrected_5scenes_20261115_130725_f9a417"
    args = argparse.Namespace(production_id=prod_id)
    real_exists = Path.exists

    def fake_exists(self, *args, **kwargs):
        if str(self).endswith("voiceover.mp3"):
            return False
        return real_exists(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    code = handle_render(args)
    assert code == 1
    captured = capsys.readouterr()
    assert "[FAIL]" in captured.out
    assert "Voiceover audio missing" in captured.out


def test_cli_resume_parser_accepts_approval_arguments():
    """Confirm pipeline resume argument parser accepts --confirm-approval and --notes."""
    exit_code = main(["resume", "-p", "prod_test", "--confirm-approval", "-n", "Human review passed", "--accept-warnings"])
    # It attempts to run handle_resume (will fail with not found prod_test, but argument parsing succeeded)
    assert exit_code == 1
