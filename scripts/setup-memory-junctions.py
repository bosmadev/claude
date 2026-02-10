#!/usr/bin/env python3
"""
Setup Memory Junctions - One-time setup script for worktree memory sharing

Creates NTFS junctions to unify memory across git worktrees for known repos.
This is a convenience wrapper around memory-unify.py's setup functions.

Usage:
  python setup-memory-junctions.py           # Setup all known repos
  python setup-memory-junctions.py cwchat    # Setup single repo
"""

import importlib.util
import sys
from pathlib import Path

# Configure UTF-8 output for Windows console
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Add hooks directory to Python path for import
CLAUDE_HOME = Path.home() / ".claude"
HOOKS_DIR = CLAUDE_HOME / "hooks"
MEMORY_UNIFY_PATH = HOOKS_DIR / "memory-unify.py"

# Import memory-unify.py module using importlib (handles hyphen in filename)
spec = importlib.util.spec_from_file_location("memory_unify", MEMORY_UNIFY_PATH)
memory_unify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory_unify)

# Extract functions we need
setup_repo = memory_unify.setup_repo
setup_all_repos = memory_unify.setup_all_repos
KNOWN_REPOS = memory_unify.KNOWN_REPOS


def main() -> None:
    """Main entry point."""
    if len(sys.argv) >= 2:
        repo_name = sys.argv[1]

        if repo_name == "--help":
            print(__doc__)
            return

        if repo_name not in KNOWN_REPOS:
            print(f"⚠️  Warning: '{repo_name}' is not in known repos list: {KNOWN_REPOS}")
            print(f"   Attempting setup anyway...")
            print()

        setup_repo(repo_name)
    else:
        setup_all_repos()


if __name__ == "__main__":
    main()
