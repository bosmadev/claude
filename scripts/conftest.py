"""Shared pytest fixtures for E2E tests."""

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test files."""
    return tmp_path


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with initial commit."""
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    readme = repo_dir / "README.md"
    readme.write_text("# Test Repository\n")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
    )

    return repo_dir


@pytest.fixture
def stdin_json() -> dict[str, Any]:
    """Mock stdin JSON for statusline protocol input."""
    return {
        "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
        "context_window": {"context_window_size": 200000},
        "exceeds_200k_tokens": False,
    }


@pytest.fixture
def sample_pr_body() -> str:
    """Sample PR body for aggregate-pr tests."""
    return """## Summary
Build 101 implementation

## Changes
### scripts/aggregate-pr.py
- Add build ID extraction
- Add changelog generation

### scripts/statusline.py
- Add team agent display
- Add model parsing
"""


@pytest.fixture
def sample_commits() -> list[dict[str, Any]]:
    """Sample commit data for aggregate-pr tests with relative timestamps."""
    now = datetime.now(timezone.utc)
    one_hour_ago = now.replace(hour=now.hour - 1)

    return [
        {
            "sha": "abc123",
            "message": "feat: add build ID extraction",
            "author": "test-user",
            "timestamp": one_hour_ago.isoformat().replace("+00:00", "Z"),
        },
        {
            "sha": "def456",
            "message": "fix: parse model correctly",
            "author": "test-user",
            "timestamp": now.isoformat().replace("+00:00", "Z"),
        },
    ]


@pytest.fixture
def sample_statusline_input() -> dict[str, Any]:
    """Sample statusline input data."""
    return {
        "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
        "context_window": {"context_window_size": 200000},
        "exceeds_200k_tokens": False,
    }


@pytest.fixture
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock environment variables."""
    monkeypatch.setenv("CLAUDE_CODE_EFFORT_LEVEL", "extended")
    monkeypatch.setenv("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "1")
