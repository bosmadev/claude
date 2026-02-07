#!/usr/bin/env python3
"""
Git Consolidated Hook - Commit review, change tracking, and command history.

This module consolidates git-related hooks into a single file with
mode dispatch based on command-line argument.

Usage:
  python3 git.py commit-review      # PreToolUse: Review git commit commands
  python3 git.py change-tracker     # PostToolUse: Track file changes
  python3 git.py command-history    # PostToolUse: Track bash commands
  python3 git.py env-check          # PreToolUse: Check .env encryption
  python3 git.py pre-commit-checks  # PreToolUse: Combined commit-review + env-check
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# =============================================================================
# Stdin Timeout - Prevent hanging on missing stdin
# =============================================================================

# Cross-platform stdin timeout (SIGALRM not available on Windows)
_stdin_timer = None

def _setup_timeout():
    global _stdin_timer
    if sys.platform == "win32":
        import threading

        def timeout_exit():
            """Log timeout and exit gracefully."""
            try:
                debug_log = Path.home() / ".claude" / "debug" / "hook-timeout.log"
                debug_log.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_log, "a") as f:
                    f.write(f"[{datetime.now().isoformat()}] git.py timeout after 5s\n")
            except Exception:
                pass
            sys.exit(0)

        _stdin_timer = threading.Timer(5, timeout_exit)
        _stdin_timer.daemon = True
        _stdin_timer.start()
    else:
        import signal

        def timeout_handler(signum, frame):
            """Log timeout and exit to prevent hooks from hanging."""
            try:
                debug_log = Path.home() / ".claude" / "debug" / "hook-timeout.log"
                debug_log.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_log, "a") as f:
                    f.write(f"[{datetime.now().isoformat()}] git.py timeout after 5s\n")
            except Exception:
                pass
            sys.exit(0)

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(5)

def _cancel_timeout():
    global _stdin_timer
    if sys.platform == "win32":
        if _stdin_timer:
            _stdin_timer.cancel()
            _stdin_timer = None
    else:
        import signal
        signal.alarm(0)

_setup_timeout()


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
        - count: Number of unpushed commits (0 if none, -1 on error)
        - branch: Current branch name (empty string if not in repo, "ERROR" on git failure)

    Error cases:
        - Git not found: (False, -1, "ERROR")
        - Not in git repo: (False, 0, "")
        - No remote configured: (False, 0, branch_name)
        - No commits to push: (False, 0, branch_name)

    Examples:
        >>> has_unpushed, count, branch = check_unpushed_commits()
        >>> if count == -1:
        ...     print("Git not available or error occurred")
        >>> elif has_unpushed:
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
            return (False, -1, "ERROR")
        branch = result.stdout.strip()
    except FileNotFoundError:
        # Git command not found
        return (False, -1, "ERROR")
    except (subprocess.TimeoutExpired, OSError):
        # Other git execution errors
        return (False, -1, "ERROR")

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
    except FileNotFoundError:
        return (False, -1, "ERROR")
    except (subprocess.TimeoutExpired, OSError):
        return (False, -1, "ERROR")

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
    except FileNotFoundError:
        return (False, -1, "ERROR")
    except (subprocess.TimeoutExpired, OSError):
        return (False, -1, "ERROR")

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
            return (False, -1, "ERROR")
        count = int(result.stdout.strip())
        return (count > 0, count, branch)
    except FileNotFoundError:
        return (False, -1, "ERROR")
    except (subprocess.TimeoutExpired, OSError):
        return (False, -1, "ERROR")
    except ValueError:
        # Failed to parse count as integer
        return (False, -1, "ERROR")


# =============================================================================
# Commit Review (PreToolUse)
# =============================================================================

def commit_review() -> None:
    """
    Creates editable commit message file before git commit.
    User can edit .claude/pending-commit.md before confirming.
    """
    try:
        hook_input = json.loads(sys.stdin.buffer.read().decode('utf-8', errors='replace'))
        _cancel_timeout()
    except json.JSONDecodeError as e:
        # Log JSON error for debugging
        try:
            debug_log = Path.home() / ".claude" / "debug" / "hook-errors.log"
            debug_log.parent.mkdir(parents=True, exist_ok=True)
            with open(debug_log, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] commit_review JSON error: {e}\n")
        except Exception:
            pass
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Only intercept git commit commands
    if not re.match(r"^git\s+commit\b", command):
        sys.exit(0)

    # Extract message - improved HEREDOC and -m flag parsing
    # Handle HEREDOC with optional quotes and proper escaping
    heredoc_match = re.search(r'cat\s*<<\s*[\'"]?EOF[\'"]?\s*\n(.*?)\nEOF', command, re.DOTALL)
    if heredoc_match:
        msg = heredoc_match.group(1).strip()
    else:
        # Handle -m flag with single/double quotes, including escaped quotes
        # Use non-greedy match and handle escaped quotes
        msg_match = re.search(r'-m\s+(["\'])((?:(?!\1).|\\.)*)\1', command, re.DOTALL)
        if msg_match:
            msg = msg_match.group(2)
            # Unescape any escaped quotes
            msg = msg.replace(r'\"', '"').replace(r"\'", "'")
        else:
            msg = "(No commit message provided - please add one)"

    # Get project directory
    project_dir = hook_input.get("cwd", ".")
    commit_file = Path(project_dir) / ".claude" / "pending-commit.md"

    # Error handling for mkdir/write failures
    try:
        commit_file.parent.mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError) as e:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Failed to create .claude directory: {e}"
            }
        }
        print(json.dumps(output))
        sys.exit(0)

    commit_content = f"""# Edit your commit message below
# Lines starting with # will be ignored
# Save this file, then confirm the commit in Claude CLI
# Delete all non-comment lines to abort the commit

{msg}
"""

    try:
        from hooks.transaction import atomic_write_text
        atomic_write_text(commit_file, commit_content, fsync=True)
    except (OSError, PermissionError) as e:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"Failed to write commit file: {e}"
            }
        }
        print(json.dumps(output))
        sys.exit(0)

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
    return find_git_root(cwd)


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


# =============================================================================
# Smart File Categorization - Path patterns to meaningful descriptions
# =============================================================================

# Category patterns: (regex, category_name, description_template)
# description_template uses {files} for file list, {count} for count
CATEGORY_PATTERNS: list[tuple[str, str, str]] = [
    # API routes - group by feature
    (r"^app/api/auth/", "api-auth", "authentication API ({files})"),
    (r"^app/api/admin/", "api-admin", "admin API ({files})"),
    (r"^app/api/gswarm/", "api-gswarm", "GSwarm API ({files})"),
    (r"^app/api/dashboard/", "api-dashboard", "dashboard API ({files})"),
    (r"^app/api/accounts/", "api-accounts", "accounts API ({files})"),
    (r"^app/api/api-keys/", "api-keys", "API key management ({files})"),
    (r"^app/api/projects/", "api-projects", "projects API ({files})"),
    (r"^app/api/", "api-other", "API routes ({files})"),

    # App pages and layouts
    (r"^app/dashboard/components/", "dashboard-components", "dashboard components ({files})"),
    (r"^app/dashboard/", "dashboard-pages", "dashboard pages ({files})"),
    (r"^app/.*layout\.tsx$", "app-layouts", "app layouts"),
    (r"^app/.*page\.tsx$", "app-pages", "app pages ({files})"),

    # Components
    (r"^components/ui/", "ui-components", "UI components ({files})"),
    (r"^components/", "components", "components ({files})"),

    # Library code
    (r"^lib/.*/storage/", "lib-storage", "storage layer ({files})"),
    (r"^lib/gswarm/", "lib-gswarm", "GSwarm core ({files})"),
    (r"^lib/", "lib", "library utilities ({files})"),

    # Config files
    (r"^\.github/workflows/", "ci", "CI workflows ({files})"),
    (r"^\.github/", "github", "GitHub templates ({files})"),
    (r"^(package\.json|pnpm-lock\.yaml|yarn\.lock|package-lock\.json)$", "deps", "dependencies"),
    (r"^(tsconfig.*\.json|biome\.json|\.eslintrc.*)$", "config-ts", "TypeScript/linting config"),
    (r"^(\.gitignore|\.env.*|\.dockerignore)$", "config-git", "git/env config"),
    (r"^python/", "python", "Python dependencies"),

    # Tests
    (r"^(tests?|__tests__|.*\.test\.|.*\.spec\.)", "tests", "tests ({files})"),

    # Scripts
    (r"^scripts/", "scripts", "build scripts ({files})"),

    # Docs
    (r"^(README|CHANGELOG|CONTRIBUTING|docs/)", "docs", "documentation"),

    # Middleware/instrumentation
    (r"^(middleware|instrumentation)\.ts$", "middleware", "middleware ({files})"),
]


def categorize_file(relative_path: str) -> tuple[str, str]:
    """
    Categorize a file based on its path.
    Returns (category_key, description_template).
    """
    # Validate input to prevent errors on empty or malformed paths
    if not relative_path or not relative_path.strip():
        return ("other", "{files}")

    # Normalize to forward slashes so regex patterns match on Windows
    normalized_path = relative_path.replace("\\", "/")
    for pattern, category, desc_template in CATEGORY_PATTERNS:
        if re.match(pattern, normalized_path):
            return (category, desc_template)
    # Fallback: use parent directory or filename
    parts = relative_path.split("/")
    if len(parts) > 1:
        return (f"other-{parts[0]}", f"{parts[0]} files ({{files}})")
    return ("other", "{files}")


def get_short_name(relative_path: str) -> str:
    """Extract a short meaningful name from a file path."""
    filename = relative_path.split("/")[-1]
    # Remove common suffixes for cleaner display
    name = re.sub(r"\.(tsx?|jsx?|mjs|cjs)$", "", filename)
    name = re.sub(r"\.route$", "", name)  # route.ts -> route -> (empty, use parent)
    if name in ("route", "page", "layout", "index"):
        # Use parent directory name instead
        parts = relative_path.split("/")
        if len(parts) >= 2:
            parent = parts[-2]
            if parent not in ("app", "api", "src"):
                return parent
    return name or filename


def format_file_list(files: list[str], max_display: int = 5) -> str:
    """Format a list of files for display, showing names not full paths."""
    short_names = [get_short_name(f) for f in files]
    # Dedupe while preserving order
    seen = set()
    unique = []
    for name in short_names:
        if name not in seen:
            seen.add(name)
            unique.append(name)

    if len(unique) <= max_display:
        return ", ".join(unique)
    else:
        shown = ", ".join(unique[:max_display])
        remaining = len(unique) - max_display
        return f"{shown} +{remaining} more"


def update_commit_md(repo_root: Path, relative_path: str, action_type: str, description: str = "") -> None:
    """
    Update commit.md with contextual, grouped entries.

    Preserves ## Ready section while updating ## Pending section.

    Format:
    # Pending Changes

    ## Pending
    - Added authentication API (login, logout, callback)
    - Updated UI components (button, badge)
    - Removed deprecated middleware

    <!-- tracked: path1, path2 -->

    ## Ready
    (User's final bullet points preserved here)
    """
    commit_file = repo_root / ".claude" / "commit.md"
    commit_file.parent.mkdir(parents=True, exist_ok=True)

    # Track which paths are already recorded
    tracked_paths: set[str] = set()
    ready_section: str = ""

    # Parse existing commit.md to recover tracked paths and Ready section
    if commit_file.exists():
        content = commit_file.read_text(encoding="utf-8", errors="replace")

        # Extract tracked paths from special comment markers
        for match in re.finditer(r"<!-- tracked: (.+?) -->", content):
            for path in match.group(1).split(","):
                tracked_paths.add(path.strip())

        # Extract ## Ready section (everything after ## Ready header)
        ready_match = re.search(r"^## Ready\s*\n(.*)", content, re.MULTILINE | re.DOTALL)
        if ready_match:
            ready_section = ready_match.group(1).strip()

    # Skip if already tracked
    if relative_path in tracked_paths:
        return

    # Add to tracked
    tracked_paths.add(relative_path)

    # Build verb_categories from all tracked paths (rebuild from scratch for consistency)
    verb_categories: dict[str, dict[str, list[str]]] = {}
    for path in tracked_paths:
        # Detect action type from git status
        p_action = detect_action_type(str(repo_root / path))
        p_verb = get_action_verb(p_action)
        p_category, _ = categorize_file(path)

        if p_verb not in verb_categories:
            verb_categories[p_verb] = {}
        if p_category not in verb_categories[p_verb]:
            verb_categories[p_verb][p_category] = []
        verb_categories[p_verb][p_category].append(path)

    # Build new content
    new_content = ["# Pending Changes", "", "## Pending"]

    # Order: Added > Fixed > Updated > Improved > Changed > Removed
    verb_order = ["Added", "Fixed", "Updated", "Improved", "Changed", "Removed"]

    for verb in verb_order:
        if verb not in verb_categories:
            continue

        categories = verb_categories[verb]
        # Sort categories for consistent output
        for category in sorted(categories.keys()):
            files = categories[category]
            _, desc_template = categorize_file(files[0])

            # Format the entry
            file_display = format_file_list(files)
            if "{files}" in desc_template:
                entry_text = desc_template.format(files=file_display, count=len(files))
            else:
                entry_text = desc_template

            new_content.append(f"- {verb} {entry_text}")

    # Add tracking comment (hidden, for parsing)
    new_content.append("")
    new_content.append(f"<!-- tracked: {', '.join(sorted(tracked_paths))} -->")
    new_content.append("")

    # Preserve ## Ready section
    new_content.append("## Ready")
    if ready_section:
        new_content.append(ready_section)
    else:
        new_content.append("(User writes their final bullet points here)")

    new_content.append("")

    try:
        from hooks.transaction import atomic_write_text
        atomic_write_text(commit_file, "\n".join(new_content), fsync=True)
    except Exception:
        # Silent fail - don't block PostToolUse hooks
        pass


# =============================================================================
# Receipt Audit Trail - SHA-256 hashing for tamper detection
# =============================================================================

def log_receipt(repo_root: Path, relative_path: str, action_type: str) -> None:
    """
    Log file change receipt with SHA-256 hash for audit trail.

    Creates immutable audit record in .claude/receipts.json:
    - SHA-256 hash of file content
    - Timestamp (ISO 8601 UTC)
    - Action type (added/modified/removed)
    - Relative path
    """
    import hashlib
    from hooks.transaction import transactional_update

    receipts_file = repo_root / ".claude" / "receipts.json"
    receipts_file.parent.mkdir(parents=True, exist_ok=True)

    # Validate path is within repo to prevent path traversal
    file_path = (repo_root / relative_path).resolve()
    if not str(file_path).startswith(str(repo_root.resolve())):
        # Path traversal attempt - skip this file silently
        return

    # Compute SHA-256 hash of file content
    if file_path.exists() and action_type != "removed":
        try:
            content = file_path.read_bytes()
            file_hash = hashlib.sha256(content).hexdigest()
        except OSError:
            file_hash = "ERROR_READING_FILE"
    else:
        file_hash = "DELETED" if action_type == "removed" else "FILE_NOT_FOUND"

    # Create receipt entry
    receipt = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "path": relative_path,
        "action": action_type,
        "sha256": file_hash,
    }

    def append_receipt(current):
        if not isinstance(current, list):
            current = []
        current.append(receipt)
        return current

    try:
        transactional_update(
            receipts_file,
            append_receipt,
            timeout=5.0,
            retries=3,
            fsync=True,
            default=[]
        )
    except Exception:
        pass  # Silent fail - don't block commits


def change_tracker() -> None:
    """Track file changes and log to commit.md with bullet style."""
    try:
        hook_input = json.loads(sys.stdin.buffer.read().decode('utf-8', errors='replace'))
        _cancel_timeout()
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
    # Normalize to forward slashes for consistent matching on Windows
    normalized_path = relative_path.replace("\\", "/")
    for pattern in skip_patterns:
        if pattern in normalized_path:
            sys.exit(0)

    action_type = detect_action_type(file_path)
    description = tool_input.get("description", "")

    try:
        update_commit_md(repo_root, relative_path, action_type, description)
        # Add receipt audit trail
        log_receipt(repo_root, relative_path, action_type)
    except OSError:
        pass

    sys.exit(0)


# =============================================================================
# Frontend Verification Reminder (PostToolUse) - Suggest /launch for visual checks
# =============================================================================

def frontend_verification_reminder() -> None:
    """Suggest visual verification via /launch when editing frontend files."""
    try:
        hook_input = json.loads(sys.stdin.buffer.read().decode('utf-8', errors='replace'))
        _cancel_timeout()
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name not in ("Edit", "Write"):
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    # Normalize path separators for pattern matching
    file_path_normalized = file_path.replace("\\", "/")

    # Frontend file patterns requiring visual verification
    frontend_patterns = [
        r"app/.*\.tsx$",           # Next.js pages/layouts
        r"components/.*\.tsx$",    # React components
        r"styles/.*\.css$",        # Stylesheets
        r"public/.*",              # Static assets
    ]

    # Skip patterns (docs, tests, types, config)
    skip_patterns = [
        r"README",
        r"\.test\.tsx$",
        r"\.spec\.tsx$",
        r"\.d\.ts$",
        r"\.config\.(ts|js)$",
    ]

    # Check if file should skip verification
    for pattern in skip_patterns:
        if re.search(pattern, file_path_normalized, re.IGNORECASE):
            sys.exit(0)

    # Check if file matches frontend patterns
    is_frontend = any(re.search(pattern, file_path_normalized) for pattern in frontend_patterns)

    if is_frontend:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "userFacingMessage": (
                    f"Frontend file edited: {file_path}\n"
                    "Consider running /launch to verify changes visually in the browser."
                )
            }
        }
        print(json.dumps(output))

    sys.exit(0)


# =============================================================================
# Command History (PostToolUse) - Per-project bash command tracking
# =============================================================================

def command_history() -> None:
    """Track bash commands in per-project command-history.log."""
    try:
        hook_input = json.loads(sys.stdin.buffer.read().decode('utf-8', errors='replace'))
        _cancel_timeout()
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

def check_env_encryption() -> None:
    """
    Check if .env files are encrypted with dotenvx before allowing git commit.

    Pre-commit guard that:
    1. Checks if package.json has env:encrypt script (dotenvx is configured)
    2. If yes, scans staged .env files for encryption header
    3. Blocks commit if unencrypted .env files are staged
    """
    try:
        hook_input = json.loads(sys.stdin.buffer.read().decode('utf-8', errors='replace'))
        _cancel_timeout()
    except json.JSONDecodeError:
        return

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    # Only intercept git commit commands
    if not re.match(r"^git\s+commit\b", command):
        return

    # Get project directory
    cwd = hook_input.get("cwd", ".")
    repo_root = find_git_root_from_cwd(cwd)
    if not repo_root:
        return

    # Check if package.json has env:encrypt script (dotenvx configured)
    package_json = repo_root / "package.json"
    if not package_json.exists():
        return

    try:
        pkg = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
        scripts = pkg.get("scripts", {})
        if "env:encrypt" not in scripts:
            # No dotenvx configured, skip check
            return
    except (json.JSONDecodeError, OSError):
        return

    # Get staged files
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return
        staged_files = result.stdout.strip().split("\n")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return

    # Check staged .env files for encryption
    # Improved pattern: matches .env, .env.*, .env.backup, env/.env, etc.
    unencrypted_envs = []
    for file in staged_files:
        if not file:
            continue
        # Match various .env patterns
        filename = Path(file).name
        if filename.startswith(".env") or filename == "env" or ".env." in filename:
            # Validate path is within repo to prevent path traversal
            env_path = (repo_root / file).resolve()
            if not str(env_path).startswith(str(repo_root.resolve())):
                continue  # Skip files outside repo
            if env_path.exists():
                try:
                    content = env_path.read_text(encoding="utf-8", errors="replace")
                    # dotenvx encrypted files start with #/--- and contain encryption metadata
                    # Improved validation: check for both header and encryption structure
                    is_encrypted = (
                        content.startswith("#/---") and
                        ("#/public-key:" in content or "#/ciphertext:" in content)
                    )
                    if not is_encrypted:
                        unencrypted_envs.append(file)
                except OSError:
                    pass

    if unencrypted_envs:
        files_list = ", ".join(unencrypted_envs)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"BLOCKED: Unencrypted .env files staged: {files_list}. Run `pnpm env:encrypt` first, then re-stage the encrypted files."
            }
        }
        print(json.dumps(output))
        sys.exit(0)

    # All .env files are encrypted (or none staged), allow commit
    return


def main() -> None:
    """Main entry point with mode dispatch."""
    if len(sys.argv) < 2:
        sys.exit(0)

    mode = sys.argv[1]
    if mode == "commit-review":
        commit_review()
    elif mode == "change-tracker":
        change_tracker()
    elif mode == "command-history":
        command_history()
    elif mode == "frontend-verification":
        frontend_verification_reminder()
    elif mode == "env-check":
        check_env_encryption()
    elif mode == "pre-commit-checks":
        # Combined mode: runs both commit-review and env-check in one process.
        # Early-exits for non-git-commit commands before any heavy logic.
        try:
            hook_input = json.loads(sys.stdin.buffer.read().decode('utf-8', errors='replace'))
            _cancel_timeout()
        except json.JSONDecodeError:
            sys.exit(0)
        command = hook_input.get("tool_input", {}).get("command", "")
        if not re.match(r"^git\s+commit\b", command):
            sys.exit(0)
        # It's a git commit — run both checks by re-injecting stdin
        import io
        raw = json.dumps(hook_input)
        sys.stdin = io.StringIO(raw)
        check_env_encryption()
        sys.stdin = io.StringIO(raw)
        commit_review()
    else:
        # Unknown mode - exit gracefully to avoid hook errors
        sys.exit(0)


if __name__ == "__main__":
    main()
