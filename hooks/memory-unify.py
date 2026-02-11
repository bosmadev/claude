#!/usr/bin/env python3
r"""
Memory Unification Hook - SessionStart Hook for Worktree Memory Sharing

Automatically creates NTFS junctions to share memory across git worktrees.
For repos following the D:\source\{repo}\{branch} convention, dev worktrees
redirect their memory to the main worktree via NTFS junctions.

Usage:
  python memory-unify.py                  # SessionStart hook mode (reads stdin)
  python memory-unify.py --setup          # Setup all known repos
  python memory-unify.py --setup cwchat   # Setup single repo
  python memory-unify.py --test           # Test path-hash computation
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

# =============================================================================
# Stdin Timeout - Prevent hanging on missing stdin
# =============================================================================

_stdin_timer = None


def _setup_timeout():
    """Setup timeout protection for stdin read operations."""
    global _stdin_timer
    if sys.platform == "win32":
        import threading

        def timeout_exit():
            sys.exit(0)

        _stdin_timer = threading.Timer(5, timeout_exit)
        _stdin_timer.daemon = True
        _stdin_timer.start()
    else:
        import signal

        def timeout_handler(signum, frame):
            sys.exit(0)

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(5)


def _cancel_timeout():
    """Cancel timeout after successful stdin read."""
    global _stdin_timer
    if sys.platform == "win32":
        if _stdin_timer:
            _stdin_timer.cancel()
            _stdin_timer = None
    else:
        import signal

        signal.alarm(0)


# =============================================================================
# Constants
# =============================================================================

CLAUDE_HOME = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_HOME / "projects"

# Known repos for --setup mode
KNOWN_REPOS = ["cwchat", "pulsona", "gswarm-api"]

# Worktree detection regex: D:/source/{repo}/{branch}
WORKTREE_PATTERN = re.compile(r"^([A-Za-z]):/source/([^/]+)/([^/]+)/?$")


# =============================================================================
# Path Hash Computation
# =============================================================================


def compute_path_hash(path: str) -> str:
    r"""
    Compute path hash for Claude Code project directory naming.

    Algorithm (from plan):
    1. Normalize backslashes to forward slashes: D:\source\cwchat\main -> D:/source/cwchat/main
    2. Replace forward slashes with single dash: D:/source/cwchat/main -> D:-source-cwchat-main
    3. Replace first colon with double dash: D:-source-cwchat-main -> D--source-cwchat-main

    Args:
        path: Absolute path to hash

    Returns:
        Path hash string suitable for directory naming
    """
    # Resolve to absolute path and normalize
    try:
        resolved = Path(path).resolve()
        normalized = str(resolved).replace("\\", "/")
    except (OSError, ValueError):
        # Fallback to original path if resolution fails
        normalized = path.replace("\\", "/")

    # Split on first colon to separate drive letter
    if ":" in normalized:
        drive, rest = normalized.split(":", 1)
        # Strip leading slash before replacing
        rest = rest.lstrip("/")
        # Replace remaining slashes with dashes
        rest = rest.replace("/", "-")
        # Rejoin with double dash
        normalized = f"{drive}--{rest}"
    else:
        # No colon (Unix path) - just replace slashes
        normalized = normalized.replace("/", "-")

    return normalized


# =============================================================================
# Worktree Detection
# =============================================================================


def detect_source_repo(cwd: str) -> Optional[Tuple[str, str]]:
    r"""
    Detect if CWD is a worktree in D:\source\{repo}\{branch} layout.

    Args:
        cwd: Current working directory

    Returns:
        (repo_name, branch_name) if match, None otherwise
    """
    # Normalize path for matching
    normalized = cwd.replace("\\", "/")

    match = WORKTREE_PATTERN.match(normalized)
    if match:
        drive, repo, branch = match.groups()
        return (repo, branch)

    return None


# =============================================================================
# Junction Management
# =============================================================================


def is_junction(path: Path) -> bool:
    """
    Check if a path is an NTFS junction.

    Uses Python 3.12+ Path.is_junction() if available,
    falls back to os.path.islink() for older versions.

    Args:
        path: Path to check

    Returns:
        True if path is a junction, False otherwise
    """
    if not path.exists():
        return False

    # Python 3.12+ has native is_junction()
    if hasattr(path, "is_junction"):
        return path.is_junction()

    # Fallback: os.path.islink() works for junctions on Windows
    return os.path.islink(str(path))


def get_junction_target(path: Path) -> Optional[Path]:
    """
    Get the target of an NTFS junction.

    Args:
        path: Junction path

    Returns:
        Target path if junction exists, None otherwise
    """
    if not is_junction(path):
        return None

    try:
        # readlink works for junctions on Windows
        target = os.readlink(str(path))
        return Path(target).resolve()
    except (OSError, ValueError):
        return None


def create_memory_junction(
    dev_hash: str, main_hash: str
) -> dict:
    """
    Create NTFS junction from dev memory to main memory.

    Args:
        dev_hash: Path hash for dev worktree
        main_hash: Path hash for main worktree

    Returns:
        dict with keys:
        - success: bool
        - action: str (created|skipped|warned)
        - message: str
    """
    dev_memory = PROJECTS_DIR / dev_hash / "memory"
    main_memory = PROJECTS_DIR / main_hash / "memory"

    # Ensure main memory directory exists
    if not main_memory.exists():
        try:
            main_memory.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {
                "success": False,
                "action": "error",
                "message": f"Failed to create main memory dir: {e}",
            }

    # Check if dev memory already exists
    if dev_memory.exists():
        # Case 1: Already a junction pointing to the right place
        if is_junction(dev_memory):
            target = get_junction_target(dev_memory)
            if target and target.resolve() == main_memory.resolve():
                return {
                    "success": True,
                    "action": "skipped",
                    "message": "Junction already exists and is correct",
                }
            else:
                return {
                    "success": False,
                    "action": "warned",
                    "message": f"Junction exists but points to wrong target: {target}",
                }

        # Case 2: Real directory with content
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

        # Case 3: Empty directory - remove and create junction
        try:
            dev_memory.rmdir()
        except OSError as e:
            return {
                "success": False,
                "action": "error",
                "message": f"Failed to remove empty dev memory dir: {e}",
            }

    # Ensure parent directory exists
    dev_memory.parent.mkdir(parents=True, exist_ok=True)

    # Create junction using cmd.exe mklink
    try:
        # Use absolute paths
        dev_path = str(dev_memory.resolve())
        main_path = str(main_memory.resolve())

        # Run mklink /J via cmd.exe
        result = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", dev_path, main_path],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0:
            return {
                "success": True,
                "action": "created",
                "message": f"Created junction: {dev_hash}/memory -> {main_hash}/memory",
            }
        else:
            return {
                "success": False,
                "action": "error",
                "message": f"mklink failed: {result.stderr}",
            }

    except Exception as e:
        return {
            "success": False,
            "action": "error",
            "message": f"Exception creating junction: {e}",
        }


# =============================================================================
# Hook Handler
# =============================================================================


def hook_session_start() -> None:
    """
    SessionStart hook entry point.

    Reads stdin JSON, detects worktree, creates junction if needed.
    """
    try:
        raw_input = sys.stdin.read()
        hook_input = json.loads(raw_input)
        _cancel_timeout()
    except json.JSONDecodeError:
        # Invalid JSON - exit silently
        sys.exit(0)

    # Extract working directory
    cwd = hook_input.get("workingDirectory", "")
    if not cwd:
        sys.exit(0)

    # Detect if this is a dev worktree
    repo_info = detect_source_repo(cwd)
    if not repo_info:
        # Not a D:\source\{repo}\{branch} worktree - exit silently
        sys.exit(0)

    repo_name, branch_name = repo_info

    # Skip if this is the main worktree
    if branch_name == "main":
        sys.exit(0)

    # Compute path hashes
    dev_hash = compute_path_hash(cwd)
    main_path = cwd.replace(f"\\{branch_name}", "\\main").replace(f"/{branch_name}", "/main")
    main_hash = compute_path_hash(main_path)

    # Create junction
    result = create_memory_junction(dev_hash, main_hash)

    # Output hook result if noteworthy
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
    """
    Setup memory junction for a single repo's dev worktree.

    Args:
        repo_name: Name of repo (e.g., "cwchat")
    """
    # Construct paths
    main_path = f"D:/source/{repo_name}/main"
    dev_path = f"D:/source/{repo_name}/{repo_name}-dev"

    # Check if main worktree exists
    if not Path(main_path).exists():
        print(f"⚠️  Main worktree not found: {main_path}")
        return

    # Compute hashes
    main_hash = compute_path_hash(main_path)
    dev_hash = compute_path_hash(dev_path)

    # Create junction
    result = create_memory_junction(dev_hash, main_hash)

    # Output result
    status_emoji = {
        "created": "✅",
        "skipped": "⏭️",
        "warned": "⚠️",
        "error": "❌",
    }
    emoji = status_emoji.get(result["action"], "ℹ️")
    print(f"{emoji} {repo_name}: {result['message']}")


def setup_all_repos() -> None:
    """Setup memory junctions for all known repos."""
    print("Setting up memory junctions for known repos...")
    print()

    for repo in KNOWN_REPOS:
        setup_repo(repo)


# =============================================================================
# CLI: Test Mode
# =============================================================================


def test_path_hash() -> None:
    """Test path hash computation with sample paths."""
    # Generate expected hash for user's home .claude directory
    home_claude = str(Path.home() / ".claude")
    home_claude_hash = compute_path_hash(home_claude)
    
    test_cases = [
        ("D:\\source\\cwchat\\main", "D--source-cwchat-main"),
        ("D:/source/cwchat/main", "D--source-cwchat-main"),
        ("D:\\source\\cwchat\\cwchat-dev", "D--source-cwchat-cwchat-dev"),
        ("D:/source/pulsona/main", "D--source-pulsona-main"),
        (home_claude, home_claude_hash),
    ]

    print("Path Hash Test:")
    print("-" * 60)

    for path, expected in test_cases:
        result = compute_path_hash(path)
        # Use ASCII status indicators for Windows console compatibility
        status = "[PASS]" if result == expected else "[FAIL]"
        print(f"{status} {path}")
        print(f"   Expected: {expected}")
        print(f"   Got:      {result}")
        print()


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> None:
    """Main CLI entry point with mode dispatch."""
    if len(sys.argv) < 2:
        # No args - run as hook
        _setup_timeout()
        hook_session_start()
        return

    mode = sys.argv[1]

    if mode == "--setup":
        if len(sys.argv) >= 3:
            # Setup specific repo
            repo_name = sys.argv[2]
            setup_repo(repo_name)
        else:
            # Setup all known repos
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
