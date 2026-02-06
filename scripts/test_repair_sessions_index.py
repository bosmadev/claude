"""Tests for repair-sessions-index.py script."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


def create_session_jsonl(
    session_path: Path,
    session_id: str,
    custom_title: str | None = None,
    message_count: int = 5,
    first_prompt: str = "Test prompt",
    git_branch: str = "main",
) -> None:
    """Helper to create a mock session JSONL file."""
    now = datetime.now(timezone.utc)
    lines = []

    # First message with session metadata
    lines.append(
        json.dumps(
            {
                "type": "user",
                "sessionId": session_id,
                "timestamp": now.isoformat().replace("+00:00", "Z"),
                "gitBranch": git_branch,
                "isSidechain": False,
                "message": {"content": first_prompt},
            }
        )
    )

    # Additional messages
    for i in range(message_count - 1):
        lines.append(
            json.dumps(
                {
                    "type": "assistant" if i % 2 else "user",
                    "timestamp": now.isoformat().replace("+00:00", "Z"),
                    "message": {"content": f"Message {i}"},
                }
            )
        )

    # Custom title event if provided
    if custom_title:
        lines.append(
            json.dumps(
                {
                    "type": "custom-title",
                    "customTitle": custom_title,
                    "timestamp": now.isoformat().replace("+00:00", "Z"),
                }
            )
        )

    session_path.write_text("\n".join(lines), encoding="utf-8")


def test_project_path_is_parent_not_grandparent(tmp_path: Path) -> None:
    """Test that projectPath is set to parent dir, not grandparent.

    This is the regression guard for the bug where projectPath was incorrectly
    set to ~/.claude/projects instead of the specific project directory.
    """
    # Simulate: ~/.claude/projects/C--Users-Dennis--claude/
    claude_projects = tmp_path / "projects"
    project_dir = claude_projects / "C--Users-Dennis--claude"
    project_dir.mkdir(parents=True)

    # Create a session file
    session_id = "12345678-1234-1234-1234-123456789abc"
    session_file = project_dir / f"{session_id}.jsonl"
    create_session_jsonl(session_file, session_id, custom_title="Test Session")

    # Import and call parse_session_file
    # Note: Python imports use underscores, not hyphens
    import sys

    scripts_dir = Path(__file__).parent
    sys.path.insert(0, str(scripts_dir))

    # Import using importlib due to hyphen in filename
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "repair_sessions_index", scripts_dir / "repair-sessions-index.py"
    )
    assert spec is not None
    assert spec.loader is not None
    repair_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repair_module)

    # Parse the session
    result = repair_module.parse_session_file(session_file)

    # CRITICAL: projectPath should be the PARENT dir (project_dir), not grandparent (claude_projects)
    assert result is not None
    assert result["projectPath"] == str(project_dir.absolute())
    assert result["projectPath"] != str(claude_projects.absolute())


def test_find_orphaned_sessions(tmp_path: Path) -> None:
    """Test detection of sessions not in index."""
    project_dir = tmp_path / "test-project"
    project_dir.mkdir()

    # Create 2 session files
    session1_id = "11111111-1111-1111-1111-111111111111"
    session2_id = "22222222-2222-2222-2222-222222222222"

    session1_file = project_dir / f"{session1_id}.jsonl"
    session2_file = project_dir / f"{session2_id}.jsonl"

    create_session_jsonl(session1_file, session1_id, custom_title="Indexed Session")
    create_session_jsonl(session2_file, session2_id, custom_title="Orphaned Session")

    # Create index with only session1
    index_data = {
        "entries": [
            {
                "sessionId": session1_id,
                "fullPath": str(session1_file.absolute()),
                "customTitle": "Indexed Session",
            }
        ]
    }

    # Import module
    import importlib.util
    import sys

    scripts_dir = Path(__file__).parent
    sys.path.insert(0, str(scripts_dir))

    spec = importlib.util.spec_from_file_location(
        "repair_sessions_index", scripts_dir / "repair-sessions-index.py"
    )
    assert spec is not None
    assert spec.loader is not None
    repair_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repair_module)

    # Find orphaned sessions
    orphaned = repair_module.find_orphaned_sessions(project_dir, index_data)

    # Should detect session2 as orphaned
    assert len(orphaned) == 1
    assert orphaned[0]["sessionId"] == session2_id
    assert orphaned[0]["customTitle"] == "Orphaned Session"


def test_parse_session_returns_correct_fields(tmp_path: Path) -> None:
    """Test that parse_session_file returns all expected fields."""
    session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    session_file = tmp_path / f"{session_id}.jsonl"

    custom_title = "Test Session Title"
    first_prompt = "What is the meaning of life?"
    git_branch = "feature/test"

    create_session_jsonl(
        session_file,
        session_id,
        custom_title=custom_title,
        message_count=10,
        first_prompt=first_prompt,
        git_branch=git_branch,
    )

    # Import module
    import importlib.util
    import sys

    scripts_dir = Path(__file__).parent
    sys.path.insert(0, str(scripts_dir))

    spec = importlib.util.spec_from_file_location(
        "repair_sessions_index", scripts_dir / "repair-sessions-index.py"
    )
    assert spec is not None
    assert spec.loader is not None
    repair_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repair_module)

    # Parse session
    result = repair_module.parse_session_file(session_file)

    # Verify all expected fields
    assert result is not None
    assert result["sessionId"] == session_id
    assert result["fullPath"] == str(session_file.absolute())
    assert result["customTitle"] == custom_title
    assert result["firstPrompt"].startswith(first_prompt)
    assert result["messageCount"] == 10
    assert result["gitBranch"] == git_branch
    assert result["projectPath"] == str(tmp_path.absolute())
    assert result["isSidechain"] is False

    # Verify metadata fields exist
    assert "created" in result
    assert "modified" in result
    assert "fileMtime" in result
    assert "summary" in result

    # Verify types
    assert isinstance(result["fileMtime"], int)
    assert isinstance(result["messageCount"], int)
