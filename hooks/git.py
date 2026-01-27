#!/usr/bin/env python3
"""
Git Consolidated Hook - Commit review, change tracking, and command history.

This module consolidates git-related hooks into a single file with
mode dispatch based on command-line argument.

Usage:
  python3 git.py commit-review    # PreToolUse: Review git commit commands
  python3 git.py change-tracker   # PostToolUse: Track file changes
  python3 git.py command-history  # PostToolUse: Track bash commands
"""

import json
import re
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# =============================================================================
# Stdin Timeout - Prevent hanging on missing stdin
# =============================================================================

def timeout_handler(signum, frame):
    """Silent exit on timeout - prevents hooks from hanging."""
    sys.exit(0)

# Set 5 second timeout for stdin read operations
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(5)


# =============================================================================
# Unpushed Commits Check - Utility for detecting local-only commits
# =============================================================================

def check_unpushed_commits(cwd: str | None = None) -> tuple[bool, int, str]:
    """
    Check if there are unpushed commits in the current git repository.

    Args:
        cwd: Working directory to check. If None, uses current directory.

    Returns:
        Tuple of (has_unpushed, count, branch):
        - has_unpushed: True if there are commits not pushed to remote
        - count: Number of unpushed commits (0 if none or error)
        - branch: Current branch name (empty string if not in repo)

    Examples:
        >>> has_unpushed, count, branch = check_unpushed_commits()
        >>> if has_unpushed:
        ...     print(f"{count} unpushed commits on {branch}")
    """
    cwd = cwd or "."

    # Check if we're in a git repository
    repo_root = find_git_root_from_cwd(cwd)
    if not repo_root:
        return (False, 0, "")

    # Get current branch name
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return (False, 0, "")
        branch = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return (False, 0, "")

    # Check if remote exists (any remote)
    try:
        result = subprocess.run(
            ["git", "remote"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            # No remotes configured
            return (False, 0, branch)
        remotes = result.stdout.strip().split("\n")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return (False, 0, branch)

    # Get tracking branch for current branch
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            upstream = result.stdout.strip()
        else:
            # No tracking branch - try origin/<branch> or origin/main
            preferred_remote = "origin" if "origin" in remotes else remotes[0]
            # Check if origin/<branch> exists
            check_result = subprocess.run(
                ["git", "rev-parse", "--verify", f"{preferred_remote}/{branch}"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if check_result.returncode == 0:
                upstream = f"{preferred_remote}/{branch}"
            else:
                # Try origin/main
                check_result = subprocess.run(
                    ["git", "rev-parse", "--verify", f"{preferred_remote}/main"],
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if check_result.returncode == 0:
                    upstream = f"{preferred_remote}/main"
                else:
                    # Try origin/master as fallback
                    check_result = subprocess.run(
                        ["git", "rev-parse", "--verify", f"{preferred_remote}/master"],
                        cwd=repo_root,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if check_result.returncode == 0:
                        upstream = f"{preferred_remote}/master"
                    else:
                        # No valid upstream found
                        return (False, 0, branch)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return (False, 0, branch)

    # Count commits ahead of upstream
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{upstream}..HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return (False, 0, branch)
        count = int(result.stdout.strip())
        return (count > 0, count, branch)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return (False, 0, branch)


# =============================================================================
# Commit Review (PreToolUse)
# =============================================================================

def commit_review() -> None:
    """
    Creates editable commit message file before git commit.
    User can edit .claude/pending-commit.md before confirming.
    """
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Only intercept git commit commands
    if not re.match(r"^git\s+commit", command):
        sys.exit(0)

    # Extract message from -m flag
    msg_match = re.search(r'-m\s+["\']([^"\']+)["\']', command)
    if msg_match:
        msg = msg_match.group(1)
    else:
        # Try to extract from HEREDOC pattern
        heredoc_match = re.search(r'cat\s*<<[\'"]?EOF[\'"]?\n(.*?)\nEOF', command, re.DOTALL)
        if heredoc_match:
            msg = heredoc_match.group(1).strip()
        else:
            msg = "(No commit message provided - please add one)"

    # Get project directory
    project_dir = hook_input.get("cwd", ".")
    commit_file = Path(project_dir) / ".claude" / "pending-commit.md"
    commit_file.parent.mkdir(parents=True, exist_ok=True)

    commit_content = f"""# Edit your commit message below
# Lines starting with # will be ignored
# Save this file, then confirm the commit in Claude CLI
# Delete all non-comment lines to abort the commit

{msg}
"""

    commit_file.write_text(commit_content)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "Commit message saved to .claude/pending-commit.md - Edit if needed, then confirm."
        }
    }
    print(json.dumps(output))
    sys.exit(0)


# =============================================================================
# Change Tracker (PostToolUse) - Bullet Style Format
# =============================================================================

def find_git_root(path: str) -> Path | None:
    """Find the git repository root for the given path."""
    try:
        search_dir = Path(path)
        if search_dir.is_file():
            search_dir = search_dir.parent
        search_dir = search_dir.resolve()
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=search_dir,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def find_git_root_from_cwd(cwd: str) -> Path | None:
    """Find the git repository root from current working directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def get_relative_path(file_path: str, repo_root: Path) -> str:
    """Get the file path relative to the repository root."""
    try:
        return str(Path(file_path).resolve().relative_to(repo_root))
    except ValueError:
        return file_path


def detect_action_type(file_path: str) -> str:
    """Detect whether this is a create, modify, or delete action."""
    try:
        repo_root = find_git_root(file_path)
        if not repo_root:
            return "modify"
        result = subprocess.run(
            ["git", "status", "--porcelain", file_path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            status = result.stdout.strip()
            if status.startswith("A ") or status.startswith("??"):
                return "create"
            elif status.startswith("D "):
                return "delete"
        return "modify"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return "modify"


def get_action_verb(action_type: str) -> str:
    """Map action type to human-readable verb."""
    return {
        "create": "Added",
        "modify": "Updated",
        "delete": "Removed",
    }.get(action_type, "Updated")


def truncate_line(line: str, max_length: int = 80) -> str:
    """Truncate line to max length with ellipsis if needed."""
    if len(line) <= max_length:
        return line
    return line[:max_length - 3] + "..."


def update_commit_md(repo_root: Path, relative_path: str, action_type: str, description: str = "") -> None:
    """Update commit.md with bullet-style entries using action verbs."""
    commit_file = repo_root / ".claude" / "commit.md"
    commit_file.parent.mkdir(parents=True, exist_ok=True)

    content = commit_file.read_text() if commit_file.exists() else ""

    # Parse existing entries: {verb: [(filename, full_entry)]}
    verb_entries: dict[str, list[tuple[str, str]]] = {}
    tracked_files: set[str] = set()

    for line in content.split("\n"):
        line_stripped = line.strip()
        if line_stripped.startswith("- "):
            entry = line_stripped[2:]
            # Parse: "Verb filename" or "Verb description with filename"
            match = re.match(r"(Added|Updated|Fixed|Removed|Improved|Changed)\s+(.+)", entry)
            if match:
                verb, rest = match.groups()
                if verb not in verb_entries:
                    verb_entries[verb] = []
                verb_entries[verb].append((rest, entry))
                # Track filenames (words with dots that look like filenames)
                for word in rest.replace(",", " ").split():
                    if "." in word and not word.startswith("."):
                        tracked_files.add(word)

    # Generate new entry
    filename = relative_path.split("/")[-1]
    verb = get_action_verb(action_type)

    # Skip if file already tracked
    if filename in tracked_files:
        return

    # Create entry
    if description:
        new_entry = f"{verb} {description}"
    else:
        new_entry = f"{verb} {filename}"

    # Add to appropriate verb group
    if verb not in verb_entries:
        verb_entries[verb] = []
    verb_entries[verb].append((filename, new_entry))

    # Rebuild content - group by verb, merge related files
    new_content = ["# Pending Changes", ""]

    # Order: Added > Fixed > Updated > Improved > Changed > Removed
    verb_order = ["Added", "Fixed", "Updated", "Improved", "Changed", "Removed"]

    for verb in verb_order:
        if verb not in verb_entries:
            continue

        entries = verb_entries[verb]
        if len(entries) == 1:
            # Single entry - keep as-is
            line = truncate_line(f"- {entries[0][1]}")
            new_content.append(line)
        elif len(entries) <= 4:
            # 2-4 entries - list filenames if they're simple
            filenames = [e[0] for e in entries if "." in e[0] and " " not in e[0]]
            if len(filenames) == len(entries):
                # All are simple filenames - merge
                line = truncate_line(f"- {verb} {', '.join(filenames)}")
                new_content.append(line)
            else:
                # Mixed - keep separate
                for _, entry in entries:
                    line = truncate_line(f"- {entry}")
                    new_content.append(line)
        else:
            # 5+ entries - summarize
            line = truncate_line(f"- {verb} {len(entries)} files")
            new_content.append(line)

    new_content.append("")
    commit_file.write_text("\n".join(new_content))


def change_tracker() -> None:
    """Track file changes and log to commit.md with bullet style."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path") or tool_input.get("filePath")

    if not file_path:
        sys.exit(0)

    repo_root = find_git_root(file_path)
    if not repo_root:
        sys.exit(0)

    relative_path = get_relative_path(file_path, repo_root)

    # Skip commit.md itself, temporary files, and internal docs
    skip_patterns = [
        "commit.md",
        "pending-commit.md",
        "pending-pr.md",
        ".claude/ralph/",
        ".claude/ralph-",
        ".claude/command-history",
        "plans/",
        ".FUTURE.md",
    ]
    for pattern in skip_patterns:
        if pattern in relative_path:
            sys.exit(0)

    action_type = detect_action_type(file_path)
    description = tool_input.get("description", "")

    try:
        update_commit_md(repo_root, relative_path, action_type, description)
    except OSError:
        pass

    sys.exit(0)


# =============================================================================
# Command History (PostToolUse) - Per-project bash command tracking
# =============================================================================

def command_history() -> None:
    """Track bash commands in per-project command-history.log."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    cwd = hook_input.get("cwd", ".")

    if not command:
        sys.exit(0)

    # Find repo root from cwd
    repo_root = find_git_root_from_cwd(cwd)
    if not repo_root:
        sys.exit(0)

    # Write to per-project command history
    history_file = repo_root / ".claude" / "command-history.log"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    # Format: [ISO timestamp] [cwd] command
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Get relative cwd if possible
    try:
        rel_cwd = str(Path(cwd).resolve().relative_to(repo_root))
        if rel_cwd == ".":
            rel_cwd = "/"
        else:
            rel_cwd = f"/{rel_cwd}"
    except ValueError:
        rel_cwd = cwd

    # Truncate very long commands
    cmd_display = command.replace("\n", " ")[:200]
    if len(command) > 200:
        cmd_display += "..."

    entry = f"[{timestamp}] [{rel_cwd}] {cmd_display}\n"

    try:
        with open(history_file, "a") as f:
            f.write(entry)
    except OSError:
        pass

    sys.exit(0)


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> None:
    """Main entry point with mode dispatch."""
    if len(sys.argv) < 2:
        print("Usage: git.py [commit-review|change-tracker|command-history]", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "commit-review":
        commit_review()
    elif mode == "change-tracker":
        change_tracker()
    elif mode == "command-history":
        command_history()
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
