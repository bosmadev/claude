"""E2E tests for scripts/aggregate-pr.py"""

import re
from pathlib import Path

import pytest


def test_extract_build_id_from_branch():
    """Test build ID extraction from branch names."""
    from scripts.aggregate_pr import extract_build_id

    # Standard format
    assert extract_build_id("feature/b101-auth") == "101"
    assert extract_build_id("fix/b42-login-bug") == "42"
    assert extract_build_id("refactor/b103-api") == "103"

    # Variations
    assert extract_build_id("b101") == "101"
    assert extract_build_id("b101-feature-name") == "101"

    # No build ID
    assert extract_build_id("some-branch") == "some-branch"
    assert extract_build_id("main") == "main"


def test_parse_commit_type():
    """Test conventional commit parsing."""
    from scripts.aggregate_pr import parse_commit_type

    # Standard format
    commit_type, scope, description = parse_commit_type("feat(auth): add login")
    assert commit_type == "feat"
    assert scope == "auth"
    assert description == "add login"

    # No scope
    commit_type, scope, description = parse_commit_type("fix: resolve bug")
    assert commit_type == "fix"
    assert scope == ""
    assert description == "resolve bug"

    # Non-conventional
    commit_type, scope, description = parse_commit_type("update readme")
    assert commit_type == "other"
    assert scope == ""
    assert description == "update readme"


@pytest.mark.integration
def test_get_repo_root():
    """Test git repository root detection."""
    from scripts.aggregate_pr import get_repo_root

    root = get_repo_root()
    assert root is not None
    assert root.is_dir()
    assert (root / ".git").exists()


@pytest.mark.integration
def test_get_current_branch():
    """Test current branch detection."""
    from scripts.aggregate_pr import get_current_branch

    branch = get_current_branch()
    assert branch != ""
    assert branch != "unknown"


@pytest.mark.integration
def test_get_commits():
    """Test commit retrieval from git log."""
    from scripts.aggregate_pr import get_commits

    commits = get_commits(base_branch="main")
    # Should return list (may be empty if on main)
    assert isinstance(commits, list)

    # If there are commits, check structure
    if commits:
        commit = commits[0]
        assert hasattr(commit, "hash")
        assert hasattr(commit, "subject")
        assert hasattr(commit, "body")
        assert hasattr(commit, "commit_type")


def test_commit_type_descriptions():
    """Test that COMMIT_TYPE_DESCRIPTIONS covers common types."""
    from scripts.aggregate_pr import COMMIT_TYPE_DESCRIPTIONS

    required_types = ["feat", "fix", "refactor", "docs", "test", "chore"]
    for commit_type in required_types:
        assert commit_type in COMMIT_TYPE_DESCRIPTIONS
        assert isinstance(COMMIT_TYPE_DESCRIPTIONS[commit_type], str)
        assert len(COMMIT_TYPE_DESCRIPTIONS[commit_type]) > 0


@pytest.mark.integration
def test_run_git():
    """Test git command runner."""
    from scripts.aggregate_pr import run_git

    # Test successful command
    code, stdout, stderr = run_git(["--version"])
    assert code == 0
    assert "git version" in stdout.lower()

    # Test failing command
    code, stdout, stderr = run_git(["invalid-command"])
    assert code != 0
