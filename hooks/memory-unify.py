#!/usr/bin/env python3
r"""
Memory Unification Hook - SessionStart Hook for Worktree Memory Sharing

Automatically creates symlinks to share memory across git worktrees.
For repos following the {source_dir}/{repo}/{branch} convention, dev worktrees
redirect their memory to the main worktree via os.symlink() (all platforms).

Set CLAUDE_SOURCE_DIR to override the default source directory.
Default: D:/source on Windows, ~/source on Linux.

Usage:
  python memory-unify.py                  # SessionStart hook mode (reads stdin)
  python memory-unify.py --setup          # Setup all known repos
  python memory-unify.py --setup cwchat   # Setup single repo
  python memory-unify.py --test           # Test path-hash computation
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

# Add parent directory to path for compat imports
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from hooks.compat import (
    IS_WINDOWS,
    cancel_stdin_timeout,
    create_symlink,
    get_symlink_target as _get_symlink_target,
    is_symlink as _is_symlink,
    setup_stdin_timeout,
)


# Wrapper functions for backward compat within this file
def _setup_timeout():
    """Setup timeout protection for stdin read operations."""
    setup_stdin_timeout(5, debug_label="memory-unify.py stdin read")


def _cancel_timeout():
    """Cancel timeout after successful stdin read."""
    cancel_stdin_timeout()


# =============================================================================
# Constants
# =============================================================================

CLAUDE_HOME = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_HOME / "projects"

# Known repos for --setup mode
KNOWN_REPOS = ["cwchat", "pulsona", "gswarm-api"]


def _get_source_dir() -> Path:
    """Return the source directory, platform-aware with env override."""
    env = os.environ.get("CLAUDE_SOURCE_DIR")
    if env:
        return Path(env)
    if IS_WINDOWS:
        return Path("D:/source")
    # Linux/Mac: use ~/source as default
    return Path.home() / "source"


# Worktree detection: matches both Windows (D:/source) and Unix (/home/user/source) layouts
WORKTREE_PATTERN_WIN = re.compile(r"^([A-Za-z]):/source/([^/]+)/([^/]+)/?$")
WORKTREE_PATTERN_UNIX = re.compile(r"^(/(?:home/[^/]+|root|Users/[^/]+)/source)/([^/]+)/([^/]+)/?$")

_SYMLINK_WARNING_SHOWN = False


def _warn_symlink_unavailable(reason: str) -> None:
    """Log a once-per-process warning when symlink creation is unavailable."""
    global _SYMLINK_WARNING_SHOWN
    if _SYMLINK_WARNING_SHOWN:
        return
    _SYMLINK_WARNING_SHOWN = True
    log_dir = CLAUDE_HOME / "debug"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "memory-unify.log"
    from datetime import datetime
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} - WARNING: {reason}\n")


# =============================================================================
# Path Hash Computation
# =============================================================================


def compute_path_hash(path: str) -> str:
    r"""
    Compute path hash for Claude Code project directory naming.

    Algorithm:
    1. Normalize backslashes to forward slashes
    2. Windows (has colon): D:/source/cwchat/main -> D--source-cwchat-main
    3. Unix (no colon): /home/dennis/source/cwchat/main -> home-dennis-source-cwchat-main

    Args:
        path: Absolute path to hash

    Returns:
        Path hash string suitable for directory naming
    """
    # Normalize separators first
    normalized = path.replace("\\", "/")

    # Only resolve via Path if this looks like a native path on the current OS
    # (avoid Path.resolve() turning /home/... into C:\home\... on Windows)
    if IS_WINDOWS and not re.match(r"^[A-Za-z]:", normalized):
        # Unix-style path on Windows host — skip resolve, hash as-is
        pass
    else:
        try:
            resolved = Path(path).resolve()
            normalized = str(resolved).replace("\\", "/")
        except (OSError, ValueError):
            pass

    if ":" in normalized:
        # Windows path: D:/source/... -> D--source-...
        drive, rest = normalized.split(":", 1)
        rest = rest.lstrip("/").replace("/", "-")
        return f"{drive}--{rest}"
    else:
        # Unix path: /home/dennis/source/... -> home-dennis-source-...
        return normalized.lstrip("/").replace("/", "-")


# =============================================================================
# Worktree Detection
# =============================================================================


def detect_source_repo(cwd: str) -> Optional[Tuple[str, str, str]]:
    r"""
    Detect if CWD is a worktree in {source_dir}/{repo}/{branch} layout.

    Supports:
    - Windows: D:/source/{repo}/{branch}
    - Linux: /home/user/source/{repo}/{branch}, /root/source/{repo}/{branch}
    - Custom: CLAUDE_SOURCE_DIR/{repo}/{branch}

    Returns:
        (repo_name, branch_name, base_path) tuple or None
    """
    normalized = cwd.replace("\\", "/")

    # Windows drive letter pattern
    match = WORKTREE_PATTERN_WIN.match(normalized)
    if match:
        drive, repo, branch = match.groups()
        return (repo, branch, f"{drive}:/source")

    # Unix home/root pattern
    match = WORKTREE_PATTERN_UNIX.match(normalized)
    if match:
        base, repo, branch = match.groups()
        return (repo, branch, base)

    # Custom CLAUDE_SOURCE_DIR pattern
    source_str = str(_get_source_dir()).replace("\\", "/")
    if normalized.startswith(source_str + "/"):
        rest = normalized[len(source_str) + 1:].strip("/")
        parts = rest.split("/")
        if len(parts) == 2:
            repo, branch = parts
            return (repo, branch, source_str)

    return None


# =============================================================================
# Symlink Management
# =============================================================================


def is_junction(path: Path) -> bool:
    """Check if path is a symlink/junction (cross-platform)."""
    if not path.exists() and not path.is_symlink():
        return False
    return _is_symlink(path)


def get_junction_target(path: Path) -> Optional[Path]:
    """Get the target of a symlink/junction."""
    if not is_junction(path):
        return None
    target = _get_symlink_target(path)
    if target:
        try:
            return target.resolve()
        except OSError:
            return target
    return None


def create_memory_junction(dev_hash: str, main_hash: str) -> dict:
    """
    Create symlink from dev memory to main memory (all platforms).

    Returns:
        dict with keys: success (bool), action (str), message (str)
    """
    dev_memory = PROJECTS_DIR / dev_hash / "memory"
    main_memory = PROJECTS_DIR / main_hash / "memory"

    # Ensure main memory directory exists
    if not main_memory.exists():
        try:
            main_memory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"success": False, "action": "error", "message": f"Failed to create main memory dir: {e}"}

    # Check if dev memory already exists
    if dev_memory.exists() or dev_memory.is_symlink():
        if is_junction(dev_memory):
            target = get_junction_target(dev_memory)
            if target:
                try:
                    if target.resolve() == main_memory.resolve():
                        return {"success": True, "action": "skipped", "message": "Symlink already exists and is correct"}
                except OSError:
                    pass
            return {"success": False, "action": "warned", "message": f"Symlink exists but points to wrong target: {target}"}

        # Real directory with content?
        try:
            files = list(dev_memory.iterdir())
            if files:
                return {
                    "success": False,
                    "action": "warned",
                    "message": f"Dev memory has existing content ({len(files)} files) - not destroying",
                }
        except OSError:
            pass

        # Empty directory - remove before creating symlink
        try:
            dev_memory.rmdir()
        except OSError as e:
            return {"success": False, "action": "error", "message": f"Failed to remove empty dev memory dir: {e}"}

    # Ensure parent directory exists
    dev_memory.parent.mkdir(parents=True, exist_ok=True)

    # Create symlink using compat.create_symlink (os.symlink + mklink /J fallback on Windows)
    if create_symlink(main_memory, dev_memory):
        return {
            "success": True,
            "action": "created",
            "message": f"Created symlink: {dev_hash}/memory -> {main_hash}/memory",
        }
    else:
        _warn_symlink_unavailable(
            "create_symlink() failed — on Windows enable unprivileged symlinks or run as admin"
        )
        return {
            "success": False,
            "action": "error",
            "message": "create_symlink() failed — check permissions (see ~/.claude/debug/memory-unify.log)",
        }


# =============================================================================
# Hook Handler
# =============================================================================


def hook_session_start() -> None:
    """SessionStart hook entry point. Reads stdin JSON, creates symlink if needed."""
    try:
        raw_input = sys.stdin.read()
        hook_input = json.loads(raw_input)
        _cancel_timeout()
    except json.JSONDecodeError:
        sys.exit(0)

    cwd = hook_input.get("workingDirectory", "")
    if not cwd:
        sys.exit(0)

    repo_info = detect_source_repo(cwd)
    if not repo_info:
        sys.exit(0)

    repo_name, branch_name, base_path = repo_info

    # Skip main worktree
    if branch_name == "main":
        sys.exit(0)

    # Compute path hashes
    dev_hash = compute_path_hash(cwd)
    normalized_cwd = cwd.replace("\\", "/")
    main_path = normalized_cwd.replace(f"/{branch_name}", "/main")
    main_hash = compute_path_hash(main_path)

    result = create_memory_junction(dev_hash, main_hash)

    if result["action"] in ("created", "warned", "error"):
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": result["message"],
            }
        }
        print(json.dumps(output))

    sys.exit(0)


# =============================================================================
# CLI: Setup Mode
# =============================================================================


def setup_repo(repo_name: str) -> None:
    """Setup memory symlink for a single repo's dev worktree."""
    source = _get_source_dir()
    main_path = str(source / repo_name / "main")
    dev_path = str(source / repo_name / f"{repo_name}-dev")

    if not Path(main_path).exists():
        print(f"[WARN] Main worktree not found: {main_path}")
        return

    main_hash = compute_path_hash(main_path)
    dev_hash = compute_path_hash(dev_path)
    result = create_memory_junction(dev_hash, main_hash)

    markers = {"created": "[OK]", "skipped": "[SKIP]", "warned": "[WARN]", "error": "[FAIL]"}
    print(f"{markers.get(result['action'], '[INFO]')} {repo_name}: {result['message']}")


def setup_all_repos() -> None:
    """Setup memory symlinks for all known repos."""
    source = _get_source_dir()
    print(f"Setting up memory symlinks for known repos (source: {source})...")
    print()
    for repo in KNOWN_REPOS:
        setup_repo(repo)


# =============================================================================
# CLI: Test Mode
# =============================================================================


def test_path_hash() -> None:
    """Test path hash computation with sample paths."""
    home_claude = str(Path.home() / ".claude")
    home_claude_hash = compute_path_hash(home_claude)

    test_cases = [
        ("D:\\source\\cwchat\\main", "D--source-cwchat-main"),
        ("D:/source/cwchat/main", "D--source-cwchat-main"),
        ("D:\\source\\cwchat\\cwchat-dev", "D--source-cwchat-cwchat-dev"),
        ("D:/source/pulsona/main", "D--source-pulsona-main"),
        ("/home/dennis/source/cwchat/main", "home-dennis-source-cwchat-main"),
        ("/home/dennis/source/cwchat/cwchat-dev", "home-dennis-source-cwchat-cwchat-dev"),
        ("/root/source/pulsona/main", "root-source-pulsona-main"),
        (home_claude, home_claude_hash),
    ]

    print("Path Hash Test:")
    print("-" * 60)
    for path, expected in test_cases:
        result = compute_path_hash(path)
        status = "[PASS]" if result == expected else "[FAIL]"
        print(f"{status} {path}")
        if result != expected:
            print(f"   Expected: {expected}")
            print(f"   Got:      {result}")
        print()


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> None:
    """Main CLI entry point with mode dispatch."""
    if len(sys.argv) < 2:
        _setup_timeout()
        hook_session_start()
        return

    mode = sys.argv[1]

    if mode == "--setup":
        if len(sys.argv) >= 3:
            setup_repo(sys.argv[2])
        else:
            setup_all_repos()
    elif mode == "--test":
        test_path_hash()
    elif mode == "--help":
        print(__doc__)
    else:
        print(f"Unknown mode: {mode}")
        print("Use --help for usage information")
        sys.exit(1)


if __name__ == "__main__":
    main()
