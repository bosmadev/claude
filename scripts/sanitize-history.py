#!/usr/bin/env python3
"""
Git history sanitization using git-filter-repo.
Removes .claude.json and replaces sensitive content across entire history.

Usage:
    python sanitize-history.py [--dry-run]

Requirements:
    - git-filter-repo installed (pip install git-filter-repo)
    - scripts/filter-expressions.txt exists
"""

import subprocess
import sys
from pathlib import Path
import shutil


# ANSI color codes
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


def print_color(msg: str, color: str) -> None:
    """Print colored message."""
    print(f"{color}{msg}{RESET}")


def check_git_filter_repo() -> bool:
    """Check if git-filter-repo is installed."""
    try:
        result = subprocess.run(
            ["git", "filter-repo", "--version"],
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def run_command(cmd: list[str], error_msg: str, dry_run: bool = False) -> bool:
    """Run shell command with error handling."""
    if dry_run:
        print_color(f"[DRY-RUN] Would execute: {' '.join(cmd)}", YELLOW)
        return True
    
    print_color(f"Running: {' '.join(cmd)}", BLUE)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    
    if result.returncode != 0:
        print_color(f"ERROR: {error_msg}", RED)
        print_color(f"STDOUT: {result.stdout}", RED)
        print_color(f"STDERR: {result.stderr}", RED)
        return False
    
    if result.stdout:
        print(result.stdout)
    
    return True


def create_backup(repo_path: Path, dry_run: bool = False) -> bool:
    """Create mirror backup of repository."""
    backup_path = repo_path.parent / "claude-backup.git"
    
    if backup_path.exists():
        print_color(f"Backup already exists: {backup_path}", YELLOW)
        return True
    
    if dry_run:
        print_color(f"[DRY-RUN] Would create backup at: {backup_path}", YELLOW)
        return True
    
    print_color(f"Creating mirror backup at: {backup_path}", BLUE)
    
    if not run_command(
        ["git", "clone", "--mirror", str(repo_path), str(backup_path)],
        "Failed to create backup",
        dry_run
    ):
        return False
    
    print_color(f"✓ Backup created at {backup_path}", GREEN)
    return True


def remove_claude_json(dry_run: bool = False) -> bool:
    """Remove .claude.json from entire history."""
    print_color("\n=== Step 1: Removing .claude.json from history ===", BLUE)
    
    return run_command(
        ["git", "filter-repo", "--path", ".claude.json", "--invert-paths", "--force"],
        "Failed to remove .claude.json",
        dry_run
    )


def replace_sensitive_content(expressions_file: Path, dry_run: bool = False) -> bool:
    """Replace sensitive content using expressions file."""
    print_color("\n=== Step 2: Replacing sensitive content ===", BLUE)
    
    if not expressions_file.exists():
        print_color(f"ERROR: Expressions file not found: {expressions_file}", RED)
        return False
    
    return run_command(
        ["git", "filter-repo", "--replace-text", str(expressions_file), "--force"],
        "Failed to replace sensitive content",
        dry_run
    )


def restore_remote(dry_run: bool = False) -> bool:
    """Re-add remote origin after filter-repo removes it."""
    print_color("\n=== Restoring remote origin ===", BLUE)
    
    return run_command(
        ["git", "remote", "add", "origin", "git@github.com:bosmadev/claude.git"],
        "Failed to restore remote",
        dry_run
    )


def verify_sanitization(dry_run: bool = False) -> bool:
    """Verify no sensitive patterns remain in history."""
    print_color("\n=== Verifying sanitization ===", BLUE)
    
    sensitive_patterns = [
        "REDACTED",
        "Dennis",
        "REDACTED-UUID",
        "REDACTED-UUID",
        "REDACTED",
        "REDACTED",
        "REDACTED",
        "accountUuid",
        r"C:\\Users\\Dennis",
        r"C:\Users\Dennis",
    ]
    
    if dry_run:
        print_color("[DRY-RUN] Would verify patterns are removed from history", YELLOW)
        return True
    
    all_clean = True
    
    for pattern in sensitive_patterns:
        # Search entire git history for pattern
        result = subprocess.run(
            ["git", "log", "--all", "-S", pattern, "--pretty=format:%H"],
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.stdout.strip():
            print_color(f"✗ Found pattern '{pattern}' in commits:", RED)
            print_color(f"  {result.stdout.strip()}", RED)
            all_clean = False
        else:
            print_color(f"✓ Pattern '{pattern}' not found", GREEN)
    
    return all_clean


def main():
    """Main execution flow."""
    dry_run = "--dry-run" in sys.argv
    
    if dry_run:
        print_color("=== DRY-RUN MODE - No changes will be made ===\n", YELLOW)
    
    # Check prerequisites
    if not check_git_filter_repo():
        print_color("ERROR: git-filter-repo not installed", RED)
        print_color("Install with: pip install git-filter-repo", YELLOW)
        sys.exit(1)
    
    repo_path = Path.cwd()
    expressions_file = repo_path / "scripts" / "filter-expressions.txt"
    
    if not expressions_file.exists() and not dry_run:
        print_color(f"ERROR: Expressions file not found: {expressions_file}", RED)
        sys.exit(1)
    
    # Create backup
    if not create_backup(repo_path, dry_run):
        sys.exit(1)
    
    # Step 1: Remove .claude.json
    if not remove_claude_json(dry_run):
        print_color("\nHistory rewrite FAILED at step 1", RED)
        sys.exit(1)
    
    # Step 2: Replace sensitive content
    if not replace_sensitive_content(expressions_file, dry_run):
        print_color("\nHistory rewrite FAILED at step 2", RED)
        sys.exit(1)
    
    # Restore remote
    if not restore_remote(dry_run):
        print_color("\nFailed to restore remote", RED)
        sys.exit(1)
    
    # Verify
    if not verify_sanitization(dry_run):
        print_color("\n⚠ Verification FAILED - sensitive content still present", RED)
        sys.exit(1)
    
    print_color("\n✓ History sanitization complete", GREEN)
    
    if not dry_run:
        print_color("\nNext steps:", YELLOW)
        print_color("1. Review changes with: git log --oneline -20", YELLOW)
        print_color("2. Force push to GitHub: git push --force --all origin", YELLOW)
        print_color("3. Notify collaborators to re-clone", YELLOW)
    else:
        print_color("\nRun without --dry-run to execute changes", YELLOW)


if __name__ == "__main__":
    main()
