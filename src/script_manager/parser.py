"""Script parsing and format ingestion."""

from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple, Union

import yaml

from src.script_manager.exceptions import ScriptValidationError
from src.script_manager.models import ContentCategory, SceneBreakdown, Script


def _slugify(text: str) -> str:
    """Generate a clean slug identifier from text."""
    clean = re.sub(r"[^\w\s-]", "", text.lower())
    clean = re.sub(r"[\s_]+", "_", clean).strip("_")
    return clean[:50] if clean else "script"


def _extract_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Extract YAML frontmatter from markdown text if present."""
    frontmatter: Dict[str, Any] = {}
    body = content

    pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
    match = re.match(pattern, content, re.DOTALL)
    if match:
        raw_yaml, body = match.groups()
        try:
            parsed = yaml.safe_load(raw_yaml)
            if isinstance(parsed, dict):
                frontmatter = parsed
        except Exception as e:
            raise ScriptValidationError(f"Invalid YAML frontmatter: {e}") from e

    return frontmatter, body.strip()


def _parse_markdown_sections(content: str) -> Dict[str, Any]:
    """Parse markdown body for Hook, Body, Takeaway, and optional Scene sections."""
    sections: Dict[str, Any] = {
        "hook": "",
        "body": "",
        "takeaway": "",
        "scenes": [],
    }

    # Split by level-2 headers
    header_pattern = r"(?m)^##\s+(.+)$"
    parts = re.split(header_pattern, content)

    # First part is text before first ## (could contain title or intro or metadata)
    preamble = parts[0].strip()
    if preamble:
        title_match = re.search(r"^#\s+(.+)$", preamble, re.MULTILINE)
        if title_match:
            sections["title"] = title_match.group(1).strip()

        for line in preamble.splitlines():
            line_match = re.match(r"^([A-Za-z_]+)\s*:\s*(.*)$", line.strip())
            if line_match:
                k = line_match.group(1).lower()
                if k in ["category", "id", "tags", "target_duration_seconds"]:
                    sections[k] = line_match.group(2).strip()

    i = 1
    while i < len(parts):
        header_title = parts[i].strip().lower()
        section_content = parts[i + 1].strip() if (i + 1) < len(parts) else ""

        if "hook" in header_title:
            sections["hook"] = section_content
        elif any(k in header_title for k in ["body", "story", "explanation", "main"]):
            sections["body"] = section_content
        elif any(k in header_title for k in ["takeaway", "conclusion", "moral", "cta", "closing"]):
            sections["takeaway"] = section_content
        elif "scene" in header_title:
            # Parse individual scene sections if formatted as ## Scene 1: Visual Prompt
            scene_match = re.search(r"scene\s+(\d+)", header_title)
            scene_num = int(scene_match.group(1)) if scene_match else (len(sections["scenes"]) + 1)
            sections["scenes"].append(
                SceneBreakdown(
                    scene_number=scene_num,
                    visual_prompt=header_title,
                    narration=section_content,
                )
            )

        i += 2

    # If title wasn't in frontmatter, try to find a level-1 header in preamble
    if not sections.get("title") and preamble:
        title_match = re.search(r"^#\s+(.+)$", preamble, re.MULTILINE)
        if title_match:
            sections["title"] = title_match.group(1).strip()

    return sections


def _parse_plain_text(content: str) -> Dict[str, Any]:
    """Parse plain text files with explicit Key: Value or Section: Value headers."""
    data: Dict[str, Any] = {
        "title": "",
        "category": "",
        "id": "",
        "hook": "",
        "body": "",
        "takeaway": "",
    }
    lines = content.splitlines()
    current_section = None
    accumulated_lines: Dict[str, List[str]] = {
        "hook": [],
        "body": [],
        "takeaway": [],
    }

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        match = re.match(r"^([A-Za-z_\s]+)\s*:\s*(.*)$", stripped)
        header_name = match.group(1).strip().lower() if match else ""

        if match and header_name in ["title", "category", "id", "tags"]:
            data[header_name] = match.group(2).strip()
            current_section = None
        elif match and header_name in ["hook", "intro"]:
            current_section = "hook"
            first_line = match.group(2).strip()
            if first_line:
                accumulated_lines["hook"].append(first_line)
        elif match and any(k in header_name for k in ["body", "story", "explanation", "main"]):
            current_section = "body"
            first_line = match.group(2).strip()
            if first_line:
                accumulated_lines["body"].append(first_line)
        elif match and any(k in header_name for k in ["takeaway", "conclusion", "moral", "cta"]):
            current_section = "takeaway"
            first_line = match.group(2).strip()
            if first_line:
                accumulated_lines["takeaway"].append(first_line)
        else:
            if current_section:
                accumulated_lines[current_section].append(stripped)
            else:
                accumulated_lines["body"].append(stripped)

    for section in ["hook", "body", "takeaway"]:
        if accumulated_lines[section]:
            data[section] = " ".join(accumulated_lines[section]).strip()

    return {k: v for k, v in data.items() if v}


def parse_script_file(file_path: Union[str, Path]) -> Script:
    """Parse a script file (.md, .json, .yaml, .txt) into a validated Script model."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Script file not found: {path}")

    raw_text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()

    data: Dict[str, Any] = {}

    if suffix == ".json":
        try:
            import json

            data = json.loads(raw_text)
            if not isinstance(data, dict):
                raise ScriptValidationError(f"JSON root must be an object: {path}")
        except Exception as e:
            raise ScriptValidationError(f"Invalid JSON in {path}: {e}") from e

    elif suffix in [".yaml", ".yml"]:
        try:
            data = yaml.safe_load(raw_text)
            if not isinstance(data, dict):
                raise ScriptValidationError(f"YAML root must be an object/dict: {path}")
        except Exception as e:
            raise ScriptValidationError(f"Invalid YAML in {path}: {e}") from e

    elif suffix == ".md":
        frontmatter, markdown_body = _extract_frontmatter(raw_text)
        sections = _parse_markdown_sections(markdown_body)
        data = {**frontmatter, **{k: v for k, v in sections.items() if v}}

    elif suffix == ".txt":
        data = _parse_plain_text(raw_text)

    else:
        raise ScriptValidationError(f"Unsupported file format '{suffix}'. Supported: .md, .json, .yaml, .txt")

    # Fallback to file stem for title or id if missing
    if not data.get("title"):
        data["title"] = path.stem.replace("_", " ").title()

    if not data.get("id"):
        data["id"] = _slugify(f"{data.get('category', 'script')}_{path.stem}")

    # Validate category presence & value
    raw_category = data.get("category")
    if not raw_category:
        raise ScriptValidationError(
            f"Script is missing required 'category' in {path}. Must be 'anime_science' or 'motivational_story'."
        )

    try:
        data["category"] = ContentCategory(str(raw_category).strip().lower())
    except ValueError:
        valid_cats = [c.value for c in ContentCategory]
        raise ScriptValidationError(
            f"Invalid category '{raw_category}' in {path}. Allowed categories: {valid_cats}"
        )

    # Validate required text blocks
    for field_name in ["hook", "body", "takeaway"]:
        val = data.get(field_name, "").strip()
        if not val:
            raise ScriptValidationError(
                f"Script is missing required section '{field_name}' in {path}."
            )
        data[field_name] = val

    if isinstance(data.get("tags"), str):
        raw_tags = data["tags"].strip()
        if raw_tags.startswith("[") and raw_tags.endswith("]"):
            import json
            try:
                data["tags"] = json.loads(raw_tags)
            except Exception:
                data["tags"] = [t.strip() for t in raw_tags.strip("[]").split(",") if t.strip()]
        else:
            data["tags"] = [t.strip() for t in raw_tags.split(",") if t.strip()]

    data["source_file"] = str(path.resolve())

    try:
        return Script(**data)
    except Exception as e:
        raise ScriptValidationError(f"Schema validation error in {path}: {e}") from e
