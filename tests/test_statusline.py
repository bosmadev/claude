"""E2E tests for scripts/statusline.py"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def test_parse_porcelain_status_empty():
    """Test parsing empty git status."""
    from scripts.statusline import parse_porcelain_status

    staged, modified, untracked = parse_porcelain_status("")
    assert staged == 0
    assert modified == 0
    assert untracked == 0


def test_parse_porcelain_status_staged():
    """Test parsing staged files."""
    from scripts.statusline import parse_porcelain_status

    status = "M  file1.py\nA  file2.py\nD  file3.py\n"
    staged, modified, untracked = parse_porcelain_status(status)
    assert staged == 3
    assert modified == 0
    assert untracked == 0


def test_parse_porcelain_status_modified():
    """Test parsing modified files."""
    from scripts.statusline import parse_porcelain_status

    status = " M file1.py\n M file2.py\n"
    staged, modified, untracked = parse_porcelain_status(status)
    assert staged == 0
    assert modified == 2
    assert untracked == 0


def test_parse_porcelain_status_untracked():
    """Test parsing untracked files."""
    from scripts.statusline import parse_porcelain_status

    status = "?? file1.py\n?? file2.py\n?? file3.py\n"
    staged, modified, untracked = parse_porcelain_status(status)
    assert staged == 0
    assert modified == 0
    assert untracked == 3


def test_parse_porcelain_status_mixed():
    """Test parsing mixed status."""
    from scripts.statusline import parse_porcelain_status

    status = "M  staged.py\n M modified.py\n?? untracked.py\nA  added.py\n"
    staged, modified, untracked = parse_porcelain_status(status)
    assert staged == 2  # M and A
    assert modified == 1
    assert untracked == 1


def test_minutes_until_reset_near():
    """Test minutes calculation when reset is near."""
    from scripts.statusline import minutes_until_reset

    # Reset in 30 minutes
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    resets_at = future.isoformat()

    result = minutes_until_reset(resets_at)
    assert "30m" in result or "29m" in result  # Allow for processing time


def test_minutes_until_reset_far():
    """Test minutes calculation when reset is far."""
    from scripts.statusline import minutes_until_reset

    # Reset in 3 hours
    future = datetime.now(timezone.utc) + timedelta(hours=3)
    resets_at = future.isoformat()

    result = minutes_until_reset(resets_at)
    assert "3h" in result or "2h59" in result  # Allow for processing time


def test_color_threshold_green():
    """Test color threshold green zone."""
    from scripts.statusline import color_threshold

    result = color_threshold("15", green_below=20, yellow_below=40)
    assert "\033[38;5;108m" in result  # AURORA_GREEN
    assert "15" in result


def test_color_threshold_yellow():
    """Test color threshold yellow zone."""
    from scripts.statusline import color_threshold

    result = color_threshold("30", green_below=20, yellow_below=40)
    assert "\033[38;5;222m" in result  # AURORA_YELLOW
    assert "30" in result


def test_color_threshold_red():
    """Test color threshold red zone."""
    from scripts.statusline import color_threshold

    result = color_threshold("50", green_below=20, yellow_below=40)
    assert "\033[38;5;131m" in result  # AURORA_RED
    assert "50" in result


def test_read_usage_cache_missing(tmp_path: Path):
    """Test reading missing usage cache."""
    from scripts.statusline import read_usage_cache

    cache_file = tmp_path / "nonexistent.json"
    result = read_usage_cache(cache_file)

    assert result["cost"] == "$0.00"
    assert result["usage_pct"] == "0"
    assert result["minutes"] == "0m"


def test_read_usage_cache_valid(tmp_path: Path):
    """Test reading valid usage cache."""
    from scripts.statusline import read_usage_cache

    cache_file = tmp_path / "usage-cache.json"
    cache_data = {
        "cost_usd": 1.50,
        "usage_pct": 25,
        "resets_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    }
    cache_file.write_text(json.dumps(cache_data))

    result = read_usage_cache(cache_file)

    assert result["cost"] == "$1.50"
    assert result["usage_pct"] == "25"
    assert "h" in result["minutes"] or "m" in result["minutes"]


@pytest.mark.integration
def test_git_run():
    """Test git command runner."""
    from scripts.statusline import git_run

    cwd = str(Path.cwd())
    result = git_run(cwd, "--version")
    assert "git version" in result.lower()


@pytest.mark.integration
def test_git_batch(tmp_path: Path):
    """Test parallel git batch operations."""
    from scripts.statusline import git_batch

    # Use current repo (test should run in git repo)
    cwd = str(Path.cwd())
    result = git_batch(cwd)

    # Should return dict with keys
    assert "branch" in result
    assert "hash" in result
    assert "ahead" in result
    assert "behind" in result
    assert "status" in result

    # Branch should not be empty
    assert result["branch"] != ""


def test_read_ralph_progress_missing(tmp_path: Path):
    """Test reading missing Ralph progress file."""
    from scripts.statusline import _read_ralph_progress

    result = _read_ralph_progress(str(tmp_path))
    assert result is None


def test_read_ralph_progress_valid(tmp_path: Path):
    """Test reading valid Ralph progress file."""
    from scripts.statusline import _read_ralph_progress

    # Create .claude/ralph directory
    ralph_dir = tmp_path / ".claude" / "ralph"
    ralph_dir.mkdir(parents=True)

    # Create fresh progress file
    progress_data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed": 5,
        "total": 10,
        "struggle_count": 0,
    }
    progress_file = ralph_dir / "progress.json"
    progress_file.write_text(json.dumps(progress_data))

    result = _read_ralph_progress(str(tmp_path))
    assert result is not None
    assert result["completed"] == 5
    assert result["total"] == 10


def test_read_ralph_progress_stale(tmp_path: Path):
    """Test reading stale Ralph progress file."""
    from scripts.statusline import _read_ralph_progress

    ralph_dir = tmp_path / ".claude" / "ralph"
    ralph_dir.mkdir(parents=True)

    # Create stale progress file (10 minutes old)
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    progress_data = {
        "updated_at": stale_time.isoformat(),
        "completed": 5,
        "total": 10,
    }
    progress_file = ralph_dir / "progress.json"
    progress_file.write_text(json.dumps(progress_data))

    result = _read_ralph_progress(str(tmp_path))
    assert result is None  # Should be considered stale


def test_style_display_mapping():
    """Test that STYLE_DISPLAY has expected entries."""
    from scripts.statusline import STYLE_DISPLAY

    assert "Engineer" in STYLE_DISPLAY
    assert "Default" in STYLE_DISPLAY
    assert STYLE_DISPLAY["Engineer"] == "⚙"
    assert STYLE_DISPLAY["Default"] == "·"
