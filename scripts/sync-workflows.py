#!/usr/bin/env python3
"""
Workflow File Drift Detection & Sync

Compares source-of-truth workflow files in ~/.claude against repo copies.
Reports drift and optionally syncs (--fix flag).

Usage:
  python sync-workflows.py              # Check for drift (report only)
  python sync-workflows.py --fix        # Copy source-of-truth to repos
  python sync-workflows.py --verbose    # Show full diff output

Monitored files:
  ~/.claude/.github/workflows/claude.yml  → {repo}/.github/workflows/claude.yml
  ~/.claude/.github/changelog.ts          → {repo}/.github/changelog.ts

Repos:
  D:/source/gswarm/gswarm-dev/
  D:/source/cwchat/cwchat-dev/
  D:/source/pulsona/pulsona-dev/
"""

import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

# Source of truth
CLAUDE_HOME = Path.home() / ".claude"

# Files to sync: (source_relative, dest_relative)
SYNC_FILES = [
    (".github/workflows/claude.yml", ".github/workflows/claude.yml"),
    (".github/changelog.ts", ".github/changelog.ts"),
]

# Repos to sync to (dev branches for editing, but these files need main)
REPOS = [
    Path("D:/source/gswarm/gswarm-dev"),
    Path("D:/source/cwchat/cwchat-dev"),
    Path("D:/source/pulsona/pulsona-dev"),
]


def get_repo_name(repo_path: Path) -> str:
    """Get short name for display."""
    return repo_path.name


def check_drift(verbose: bool = False) -> list[tuple[Path, str, str]]:
    """
    Check for drift between source-of-truth and repo copies.

    Returns list of (repo_path, relative_file, diff_summary) tuples for drifted files.
    """
    drifted = []

    for source_rel, dest_rel in SYNC_FILES:
        source = CLAUDE_HOME / source_rel
        if not source.exists():
            print(f"  WARNING: Source not found: {source}")
            continue

        for repo in REPOS:
            dest = repo / dest_rel
            repo_name = get_repo_name(repo)

            if not dest.exists():
                drifted.append((repo, dest_rel, "MISSING"))
                print(f"  {repo_name}/{dest_rel}: MISSING")
                continue

            if filecmp.cmp(str(source), str(dest), shallow=False):
                if verbose:
                    print(f"  {repo_name}/{dest_rel}: OK (identical)")
                continue

            # Files differ — compute brief diff
            try:
                result = subprocess.run(
                    ["git", "diff", "--no-index", "--stat", str(source), str(dest)],
                    capture_output=True, text=True, timeout=5,
                )
                stat = result.stdout.strip().split("\n")[-1] if result.stdout else "differs"
            except (subprocess.TimeoutExpired, FileNotFoundError):
                stat = "differs"

            drifted.append((repo, dest_rel, stat))
            print(f"  {repo_name}/{dest_rel}: DRIFTED — {stat}")

            if verbose:
                try:
                    result = subprocess.run(
                        ["git", "diff", "--no-index", str(source), str(dest)],
                        capture_output=True, text=True, timeout=10,
                    )
                    # Show first 30 lines of diff
                    diff_lines = result.stdout.strip().split("\n")[:30]
                    for line in diff_lines:
                        print(f"    {line}")
                    if len(result.stdout.strip().split("\n")) > 30:
                        print(f"    ... ({len(result.stdout.strip().split(chr(10)))} total lines)")
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass

    return drifted


def sync_files(drifted: list[tuple[Path, str, str]]) -> int:
    """
    Copy source-of-truth files to drifted repos.

    Returns count of files synced.
    """
    synced = 0
    for repo, dest_rel, _ in drifted:
        source_rel = dest_rel  # Same relative path in source
        source = CLAUDE_HOME / source_rel
        dest = repo / dest_rel

        if not source.exists():
            print(f"  SKIP: Source not found: {source}")
            continue

        # Ensure destination directory exists
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(str(source), str(dest))
            repo_name = get_repo_name(repo)
            print(f"  SYNCED: {repo_name}/{dest_rel}")
            synced += 1
        except (OSError, PermissionError) as e:
            print(f"  ERROR: {repo} — {e}")

    return synced


def main():
    args = sys.argv[1:]
    fix_mode = "--fix" in args
    verbose = "--verbose" in args or "-v" in args

    print("Workflow Drift Detection")
    print("=" * 50)
    print(f"Source: {CLAUDE_HOME}")
    print(f"Files:  {', '.join(s for s, _ in SYNC_FILES)}")
    print(f"Repos:  {len(REPOS)}")
    print()

    # Check drift
    print("Checking for drift...")
    drifted = check_drift(verbose)
    print()

    if not drifted:
        print("All files in sync. No drift detected.")
        return

    print(f"Found {len(drifted)} drifted file(s).")

    if fix_mode:
        print()
        print("Syncing files...")
        synced = sync_files(drifted)
        print(f"\nSynced {synced}/{len(drifted)} files.")
        if synced > 0:
            print("\nIMPORTANT: These changes are on dev branches.")
            print("For claude.yml to work, it must be on MAIN branch.")
            print("Options:")
            print("  1. Commit + push on dev, then merge to main")
            print("  2. Copy directly to main worktree and commit there")
    else:
        print("\nRun with --fix to sync source-of-truth to repos.")


if __name__ == "__main__":
    main()
