"""Automated tests for Script Manager & Ingestion module."""

import json
from pathlib import Path
import pytest

from src.script_manager.exceptions import (
    ScriptAlreadyUsedError,
    ScriptApprovalRequiredError,
    ScriptDuplicateError,
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
from src.script_manager.service import ScriptManager


@pytest.fixture
def temp_repo(tmp_path):
    """Isolated ScriptRepository backed by temporary directory."""
    return ScriptRepository(base_dir=tmp_path / "processed")


@pytest.fixture
def temp_manager(tmp_path, temp_repo):
    """Isolated ScriptManager using temporary paths."""
    queue = DailyScriptQueue(temp_repo)
    manager = ScriptManager(repository=temp_repo, queue=queue)
    manager.scripts_dir = tmp_path / "scripts"
    manager.scripts_dir.mkdir(parents=True, exist_ok=True)
    return manager


# --- 1. Ingestion & Format Tests ---

def test_markdown_frontmatter_ingestion(tmp_path, temp_manager):
    """Verify ingestion of Markdown scripts with YAML frontmatter."""
    md_content = """---
id: test_anime_01
title: Dummy Science Topic
category: anime_science
tags: ["#Anime", "#Science"]
target_duration_seconds: 40
---

## Hook
Dummy hook questioning a physical principle.

## Body
Dummy body explaining real physics and mathematical equations in a test context.

## Takeaway
Dummy takeaway summarizing the lesson.
"""
    file_path = tmp_path / "test_script.md"
    file_path.write_text(md_content, encoding="utf-8")

    script = temp_manager.ingest_file(file_path)
    assert script.id == "test_anime_01"
    assert script.category == ContentCategory.ANIME_SCIENCE
    assert script.status == ScriptStatus.PENDING_REVIEW
    assert "Dummy hook" in script.hook
    assert "Dummy body" in script.body
    assert "Dummy takeaway" in script.takeaway
    assert script.content_hash != ""


def test_json_script_ingestion(tmp_path, temp_manager):
    """Verify ingestion of structured JSON scripts."""
    data = {
        "id": "test_motivational_01",
        "title": "Dummy Story of Growth",
        "category": "motivational_story",
        "hook": "Dummy opening line about patience.",
        "body": "Dummy story describing persistence under pressure.",
        "takeaway": "Dummy moral of the lesson.",
        "tags": ["#Patience", "#Discipline"],
    }
    file_path = tmp_path / "test_script.json"
    file_path.write_text(json.dumps(data), encoding="utf-8")

    script = temp_manager.ingest_file(file_path)
    assert script.id == "test_motivational_01"
    assert script.category == ContentCategory.MOTIVATIONAL_STORY
    assert script.status == ScriptStatus.PENDING_REVIEW


def test_yaml_script_ingestion(tmp_path, temp_manager):
    """Verify ingestion of YAML format scripts."""
    yaml_content = """
id: test_yaml_01
title: Dummy YAML Science
category: anime_science
hook: Dummy YAML hook sentence.
body: Dummy YAML body explanation.
takeaway: Dummy YAML takeaway conclusion.
"""
    file_path = tmp_path / "test_script.yaml"
    file_path.write_text(yaml_content, encoding="utf-8")

    script = temp_manager.ingest_file(file_path)
    assert script.id == "test_yaml_01"
    assert script.category == ContentCategory.ANIME_SCIENCE


def test_plain_text_ingestion(tmp_path, temp_manager):
    """Verify ingestion of plain text script format."""
    txt_content = """Title: Dummy Plain Text
Category: motivational_story
Hook: Dummy text hook.
Body: Dummy text body story spanning lines.
Takeaway: Dummy text takeaway.
"""
    file_path = tmp_path / "test_script.txt"
    file_path.write_text(txt_content, encoding="utf-8")

    script = temp_manager.ingest_file(file_path)
    assert script.category == ContentCategory.MOTIVATIONAL_STORY
    assert script.hook == "Dummy text hook."


# --- 2. Category & Metadata Validation Tests ---

def test_category_validation_valid(tmp_path):
    """Verify both supported categories pass validation."""
    for cat in ["anime_science", "motivational_story"]:
        file_path = tmp_path / f"test_{cat}.json"
        file_path.write_text(
            json.dumps({
                "id": f"test_{cat}",
                "title": "Test Title",
                "category": cat,
                "hook": "Test hook text",
                "body": "Test body text",
                "takeaway": "Test takeaway text",
            }),
            encoding="utf-8",
        )
        script = parse_script_file(file_path)
        assert script.category.value == cat


def test_category_validation_invalid(tmp_path):
    """Verify invalid category raises ScriptValidationError."""
    file_path = tmp_path / "invalid_cat.json"
    file_path.write_text(
        json.dumps({
            "id": "test_invalid_cat",
            "title": "Invalid Category Script",
            "category": "unsupported_genre",
            "hook": "Hook",
            "body": "Body",
            "takeaway": "Takeaway",
        }),
        encoding="utf-8",
    )
    with pytest.raises(ScriptValidationError) as exc:
        parse_script_file(file_path)
    assert "Invalid category" in str(exc.value)


def test_missing_required_sections_raises_validation_error(tmp_path):
    """Verify missing hook/body/takeaway fails validation."""
    file_path = tmp_path / "missing_hook.json"
    file_path.write_text(
        json.dumps({
            "id": "missing_hook_test",
            "title": "Missing Hook",
            "category": "anime_science",
            "body": "Body without hook",
            "takeaway": "Takeaway without hook",
        }),
        encoding="utf-8",
    )
    with pytest.raises(ScriptValidationError) as exc:
        parse_script_file(file_path)
    assert "hook" in str(exc.value).lower()


# --- 3. Duplicate Detection Tests ---

def test_duplicate_detection_by_content_hash(tmp_path, temp_manager):
    """Verify identical text across different file names / IDs is rejected as duplicate."""
    script1 = {
        "id": "script_a",
        "title": "First Version",
        "category": "anime_science",
        "hook": "Identical hook for test.",
        "body": "Identical body content explaining facts.",
        "takeaway": "Identical takeaway.",
    }
    script2 = {
        "id": "script_b",  # Different ID, but identical content
        "title": "Second Version with Different ID",
        "category": "anime_science",
        "hook": "Identical hook for test.",
        "body": "Identical body content explaining facts.",
        "takeaway": "Identical takeaway.",
    }

    f1 = tmp_path / "f1.json"
    f2 = tmp_path / "f2.json"
    f1.write_text(json.dumps(script1), encoding="utf-8")
    f2.write_text(json.dumps(script2), encoding="utf-8")

    temp_manager.ingest_file(f1)

    with pytest.raises(ScriptDuplicateError) as exc:
        temp_manager.ingest_file(f2)
    assert "Duplicate script" in str(exc.value)


# --- 4. Human Approval Gate Tests ---

def test_human_approval_restriction(tmp_path, temp_manager):
    """Verify that unapproved scripts cannot enter production."""
    script_data = {
        "id": "unapproved_script_01",
        "title": "Awaiting Review",
        "category": "motivational_story",
        "hook": "Dummy hook.",
        "body": "Dummy body.",
        "takeaway": "Dummy takeaway.",
    }
    f = tmp_path / "unapproved.json"
    f.write_text(json.dumps(script_data), encoding="utf-8")

    temp_manager.ingest_file(f)

    # Status must start as PENDING_REVIEW
    stored = temp_manager.get_script("unapproved_script_01")
    assert stored.status == ScriptStatus.PENDING_REVIEW

    # Attempting to select from queue must raise ScriptApprovalRequiredError
    with pytest.raises(ScriptApprovalRequiredError) as exc:
        temp_manager.get_next_daily_script()
    assert "waiting for human approval" in str(exc.value)


def test_approval_and_rejection_workflows(tmp_path, temp_manager):
    """Verify explicit human approval and rejection operations."""
    script_data = {
        "id": "workflow_test_01",
        "title": "Workflow Test",
        "category": "anime_science",
        "hook": "Dummy hook for workflow.",
        "body": "Dummy body for workflow.",
        "takeaway": "Dummy takeaway for workflow.",
    }
    f = tmp_path / "workflow.json"
    f.write_text(json.dumps(script_data), encoding="utf-8")

    temp_manager.ingest_file(f)

    # Approve
    approved = temp_manager.approve_script("workflow_test_01", notes="Checked by creator")
    assert approved.status == ScriptStatus.APPROVED
    assert approved.approved_at is not None
    assert approved.approval_notes == "Checked by creator"

    # Reject another
    script_data_2 = {
        "id": "workflow_test_02",
        "title": "Reject Test",
        "category": "motivational_story",
        "hook": "Hook 2.",
        "body": "Body 2.",
        "takeaway": "Takeaway 2.",
    }
    f2 = tmp_path / "workflow2.json"
    f2.write_text(json.dumps(script_data_2), encoding="utf-8")
    temp_manager.ingest_file(f2)

    rejected = temp_manager.reject_script("workflow_test_02", reason="Tone needs adjustment")
    assert rejected.status == ScriptStatus.REJECTED
    assert rejected.rejection_reason == "Tone needs adjustment"


# --- 5. Daily Queue & Used Script Tracking Tests ---

def test_daily_queue_selection_and_used_tracking(tmp_path, temp_manager):
    """Verify FIFO queue ordering, production transition, and duplicate prevention via USED status."""
    for i in range(1, 4):
        f = tmp_path / f"day_{i}.json"
        f.write_text(
            json.dumps({
                "id": f"script_day_{i}",
                "title": f"Day {i} Topic",
                "category": "anime_science" if i % 2 == 1 else "motivational_story",
                "hook": f"Hook for day {i}.",
                "body": f"Body content for day {i}.",
                "takeaway": f"Takeaway for day {i}.",
            }),
            encoding="utf-8",
        )
        temp_manager.ingest_file(f)
        temp_manager.approve_script(f"script_day_{i}")

    # Check upcoming queue count
    queue = temp_manager.get_daily_queue()
    assert len(queue) == 3
    assert queue[0].id == "script_day_1"

    # Select day 1 for production
    selected = temp_manager.get_next_daily_script()
    assert selected.id == "script_day_1"
    assert selected.status == ScriptStatus.IN_PRODUCTION

    # Mark day 1 as used (video published)
    completed = temp_manager.mark_as_used("script_day_1")
    assert completed.status == ScriptStatus.USED
    assert completed.used_at is not None

    # Next daily selection should yield day 2
    next_selected = temp_manager.get_next_daily_script()
    assert next_selected.id == "script_day_2"

    # Completed script cannot be reused
    with pytest.raises(ScriptAlreadyUsedError):
        temp_manager.mark_as_used("script_day_1")


# --- 6. Future AI Compatibility Tests ---

def test_approved_exemplars_interface(tmp_path, temp_manager):
    """Verify that approved scripts can be queried as few-shot style exemplars for future AI."""
    f = tmp_path / "approved_ex.json"
    f.write_text(
        json.dumps({
            "id": "exemplar_01",
            "title": "Exemplar Script",
            "category": "anime_science",
            "hook": "Exemplar hook.",
            "body": "Exemplar body.",
            "takeaway": "Exemplar takeaway.",
        }),
        encoding="utf-8",
    )
    temp_manager.ingest_file(f)
    temp_manager.approve_script("exemplar_01")

    exemplars = temp_manager.get_approved_exemplars(category=ContentCategory.ANIME_SCIENCE)
    assert len(exemplars) == 1
    assert exemplars[0].id == "exemplar_01"


def test_future_ai_draft_submission_safeguard(temp_manager):
    """Verify AI-submitted drafts always start in PENDING_REVIEW and require approval."""
    draft_data = {
        "id": "future_ai_draft_01",
        "title": "AI Draft Proposal",
        "category": "motivational_story",
        "hook": "AI generated hook test.",
        "body": "AI generated body test.",
        "takeaway": "AI generated takeaway test.",
        "status": "approved",  # Attacking the safeguard: AI attempts to mark itself as approved!
    }

    # The manager must override and force PENDING_REVIEW
    draft = temp_manager.submit_ai_draft(draft_data)
    assert draft.status == ScriptStatus.PENDING_REVIEW

    # Must fail daily production queue selection until human signs off
    with pytest.raises(ScriptApprovalRequiredError):
        temp_manager.get_next_daily_script()


# --- 7. Additional Operations & Batch Ingestion Tests ---

def test_pure_markdown_without_frontmatter(tmp_path, temp_manager):
    """Verify ingestion of pure Markdown using standard headers."""
    md_content = """# Pure Markdown Topic
Category: anime_science

## Hook
Hook sentence from pure markdown.

## Body
Body sentence from pure markdown with scientific details.

## Takeaway
Takeaway sentence from pure markdown.
"""
    f = tmp_path / "pure_header.md"
    f.write_text(md_content, encoding="utf-8")

    script = temp_manager.ingest_file(f)
    assert script.category == ContentCategory.ANIME_SCIENCE
    assert "Hook sentence" in script.hook
    assert "Body sentence" in script.body
    assert "Takeaway sentence" in script.takeaway


def test_update_and_delete_script(tmp_path, temp_manager):
    """Verify safe updates and deletions of scripts."""
    f = tmp_path / "crud_test.json"
    f.write_text(
        json.dumps({
            "id": "crud_script_01",
            "title": "Initial Title",
            "category": "motivational_story",
            "hook": "Initial hook.",
            "body": "Initial body.",
            "takeaway": "Initial takeaway.",
        }),
        encoding="utf-8",
    )
    script = temp_manager.ingest_file(f)
    assert temp_manager.repository.exists("crud_script_01")

    # Update title
    script.title = "Updated Title"
    updated = temp_manager.update_script(script)
    assert updated.title == "Updated Title"
    assert temp_manager.get_script("crud_script_01").title == "Updated Title"

    # Delete
    deleted = temp_manager.delete_script("crud_script_01")
    assert deleted is True
    assert temp_manager.get_script("crud_script_01") is None
    assert not temp_manager.repository.exists("crud_script_01")


def test_batch_ingestion_15_days(tmp_path, temp_manager):
    """Verify batch ingestion of 15 days of content and summary metrics."""
    batch_dir = tmp_path / "batch_15"
    batch_dir.mkdir(parents=True, exist_ok=True)

    for i in range(1, 16):
        cat = "anime_science" if i % 2 == 1 else "motivational_story"
        f = batch_dir / f"batch_day_{i:02d}.json"
        f.write_text(
            json.dumps({
                "id": f"batch_script_{i:02d}",
                "title": f"Batch Title Day {i}",
                "category": cat,
                "hook": f"Unique Hook for day {i}.",
                "body": f"Unique Body content for day {i} explaining specific concepts.",
                "takeaway": f"Unique Takeaway for day {i}.",
            }),
            encoding="utf-8",
        )

    res = temp_manager.ingest_batch(batch_dir)
    assert res["total_files_scanned"] == 15
    assert len(res["ingested"]) == 15
    assert len(res["skipped_duplicates"]) == 0
    assert len(res["errors"]) == 0

    # Summary check before approvals
    summary = temp_manager.get_summary()
    assert summary["total_scripts"] == 15
    assert summary["approved_in_queue"] == 0
    assert summary["by_status"]["pending_review"] == 15

    # Approve 10 days
    for i in range(1, 11):
        temp_manager.approve_script(f"batch_script_{i:02d}")

    summary_after = temp_manager.get_summary()
    assert summary_after["approved_in_queue"] == 10
    assert summary_after["days_of_content_ready"] == 10
    assert summary_after["by_status"]["approved"] == 10
    assert summary_after["by_status"]["pending_review"] == 5
