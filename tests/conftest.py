"""Shared pytest fixtures for E2E tests."""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def temp_dir(tmp_path: Path) -> Path:
    """Provide a temporary directory for test files."""
    return tmp_path


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
    """Sample commit data for aggregate-pr tests."""
    return [
        {
            "sha": "abc123",
            "message": "feat: add build ID extraction",
            "author": "test-user",
            "timestamp": "2026-02-06T12:00:00Z",
        },
        {
            "sha": "def456",
            "message": "fix: parse model correctly",
            "author": "test-user",
            "timestamp": "2026-02-06T13:00:00Z",
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
