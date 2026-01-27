#!/usr/bin/env python3
"""
Commit Helper - Branch-aware commit naming and pending commit generation.

Usage:
    commit-helper.py generate <file-path>     - Generate pending-commit.md
    commit-helper.py get-branch <file-path>   - Get current branch name
    commit-helper.py get-increment <file-path> - Get next commit increment
    commit-helper.py detect-type <file-path>  - Detect conventional commit type

The file-path is used to detect the git repository root.
"""

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Conventional commit types
COMMIT_TYPES = {
    "feat": "A new feature",
    "fix": "A bug fix",
    "docs": "Documentation changes",
    "style": "Code style changes (formatting, semicolons)",
    "refactor": "Code refactoring (no feature or fix)",
    "test": "Adding or updating tests",
    "chore": "Routine tasks (dependencies, configs)",
    "build": "Build system or external dependencies",
    "ci": "CI configuration changes",
    "perf": "Performance improvements",
    "revert": "Reverting a previous commit",
}


def get_repo_root(file_path: str) -> Path | None:
    """Detect git repository root from a file path."""
    path = Path(file_path).resolve()

    if path.is_file():
        path = path.parent
    elif not path.exists():
        while not path.exists() and path.parent != path:
            path = path.parent

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        return None


def get_branch_name(repo_root: Path) -> str:
    """Get current branch name, with worktree fallback."""
    try:
        # Try git branch first
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        branch = result.stdout.strip()

        if branch:
            return branch

        # Fallback: check if in detached HEAD state, use worktree name
        return repo_root.name

    except subprocess.CalledProcessError:
        # Final fallback: use directory name
        return repo_root.name


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for use in commit ID (replace / with -)."""
    return branch.replace("/", "-")


def get_last_commit_number(repo_root: Path, branch: str) -> int:
    """Find the last commit number for this branch."""
    safe_branch = sanitize_branch_name(branch)

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-200", "--all"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

        # Pattern: commit message starting with {branch}-{number}
        pattern = rf"\b{re.escape(safe_branch)}-(\d+)\b"

        for line in result.stdout.split("\n"):
            match = re.search(pattern, line)
            if match:
                return int(match.group(1))

        return 0

    except subprocess.CalledProcessError:
        return 0


def get_next_increment(repo_root: Path, branch: str) -> int:
    """Calculate the next commit increment for this branch."""
    last_num = get_last_commit_number(repo_root, branch)
    return last_num + 1


def read_commit_log(repo_root: Path) -> dict:
    """Read and parse .claude/commit.md."""
    commit_log_path = repo_root / ".claude" / "commit.md"

    result = {
        "exists": False,
        "entries": [],
        "summary": "",
        "raw_content": "",
    }

    if not commit_log_path.exists():
        return result

    result["exists"] = True
    content = commit_log_path.read_text()
    result["raw_content"] = content

    # Parse entries
    in_files_section = False
    for line in content.split("\n"):
        if line.strip() == "## Files Modified":
            in_files_section = True
            continue
        if line.startswith("## ") and in_files_section:
            in_files_section = False
        if in_files_section and line.strip().startswith("- ["):
            result["entries"].append(line.strip())

    # Parse summary
    if "## Summary" in content:
        summary_start = content.find("## Summary") + len("## Summary")
        summary_text = content[summary_start:].strip()
        # Get first non-empty line
        for line in summary_text.split("\n"):
            if line.strip() and line.strip() != "Auto-generated summary of changes":
                result["summary"] = line.strip()
                break

    return result


def detect_commit_type(commit_log: dict) -> str:
    """Detect conventional commit type from changes."""
    entries = commit_log.get("entries", [])
    summary = commit_log.get("summary", "").lower()

    # Check summary for keywords
    if any(word in summary for word in ["fix", "bug", "issue", "error", "crash"]):
        return "fix"
    if any(word in summary for word in ["add", "new", "feature", "implement"]):
        return "feat"
    if any(word in summary for word in ["refactor", "restructure", "reorganize"]):
        return "refactor"
    if any(word in summary for word in ["perf", "performance", "optimize", "speed"]):
        return "perf"

    # Analyze file patterns
    created_files = []
    modified_files = []
    deleted_files = []

    for entry in entries:
        if "] create:" in entry:
            # Extract file path
            match = re.search(r"create: ([^\s-]+)", entry)
            if match:
                created_files.append(match.group(1))
        elif "] modify:" in entry:
            match = re.search(r"modify: ([^\s-]+)", entry)
            if match:
                modified_files.append(match.group(1))
        elif "] delete:" in entry:
            match = re.search(r"delete: ([^\s-]+)", entry)
            if match:
                deleted_files.append(match.group(1))

    all_files = created_files + modified_files

    # Check file patterns
    if all_files:
        # All docs
        if all(f.endswith((".md", ".rst", ".txt")) for f in all_files):
            return "docs"

        # All tests
        if all("test" in f.lower() or "spec" in f.lower() for f in all_files):
            return "test"

        # CI files
        ci_patterns = [".github/workflows", ".gitlab-ci", "Jenkinsfile", ".circleci"]
        if any(any(p in f for p in ci_patterns) for f in all_files):
            return "ci"

        # Build/config files
        config_patterns = ["package.json", "tsconfig", "vite.config", "webpack", "Dockerfile"]
        if all(any(p in f for p in config_patterns) for f in all_files):
            return "build"

        # New files created = likely a feature
        if created_files and not modified_files:
            return "feat"

    # Default
    return "chore"


def get_git_diff_stat(repo_root: Path) -> str:
    """Get git diff stat as fallback for file changes."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return "No changes detected"


def generate_pending_commit(repo_root: Path) -> str:
    """Generate pending-commit.md content."""
    branch = get_branch_name(repo_root)
    safe_branch = sanitize_branch_name(branch)
    increment = get_next_increment(repo_root, branch)
    commit_id = f"{safe_branch}-{increment}"

    commit_log = read_commit_log(repo_root)
    commit_type = detect_commit_type(commit_log)

    # Build file changes section
    if commit_log["entries"]:
        files_section = "\n".join(commit_log["entries"])
    else:
        files_section = get_git_diff_stat(repo_root)

    # Build summary
    if commit_log["summary"]:
        summary = commit_log["summary"]
    else:
        summary = "Update codebase"

    # Generate scope from common path prefix
    scope = ""
    if commit_log["entries"]:
        paths = []
        for entry in commit_log["entries"]:
            match = re.search(r"(?:create|modify|delete): ([^\s]+)", entry)
            if match:
                paths.append(match.group(1))
        if paths:
            # Find common directory
            parts = [p.split("/") for p in paths]
            if parts and len(parts[0]) > 1:
                scope = parts[0][0]  # First directory

    # Build commit message
    if scope:
        commit_message = f"{commit_type}({scope}): {summary}"
    else:
        commit_message = f"{commit_type}: {summary}"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = f"""# Pending Commit

Generated: {timestamp}

## Commit ID

{commit_id}

## Branch

{branch}

## Type

{commit_type} - {COMMIT_TYPES.get(commit_type, "Unknown")}

## Message

{commit_message}

## Files Changed

{files_section}

## Full Commit Message

```
{commit_message}

Commit-ID: {commit_id}
```

---

**Actions:**
- Run `/commit confirm` to create this commit
- Run `/commit abort` to cancel
- Edit this file to modify the commit message before confirming

**Available Types:** {", ".join(COMMIT_TYPES.keys())}
"""

    return content


def cmd_generate(file_path: str) -> int:
    """Generate pending-commit.md."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    pending_path = repo_root / "pending-commit.md"

    if pending_path.exists():
        print(f"Warning: pending-commit.md already exists at {pending_path}")
        print("Run '/commit abort' first or delete the file manually.")
        return 1

    content = generate_pending_commit(repo_root)
    pending_path.write_text(content)

    print(f"Generated: {pending_path}")
    print(content)
    return 0


def cmd_get_branch(file_path: str) -> int:
    """Print current branch name."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    branch = get_branch_name(repo_root)
    print(branch)
    return 0


def cmd_get_increment(file_path: str) -> int:
    """Print next commit increment."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    branch = get_branch_name(repo_root)
    increment = get_next_increment(repo_root, branch)
    print(increment)
    return 0


def cmd_detect_type(file_path: str) -> int:
    """Print detected commit type."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    commit_log = read_commit_log(repo_root)
    commit_type = detect_commit_type(commit_log)
    print(commit_type)
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    command = sys.argv[1]

    if command == "generate":
        if len(sys.argv) < 3:
            print("Usage: commit-helper.py generate <file-path>", file=sys.stderr)
            return 1
        return cmd_generate(sys.argv[2])

    elif command == "get-branch":
        if len(sys.argv) < 3:
            print("Usage: commit-helper.py get-branch <file-path>", file=sys.stderr)
            return 1
        return cmd_get_branch(sys.argv[2])

    elif command == "get-increment":
        if len(sys.argv) < 3:
            print("Usage: commit-helper.py get-increment <file-path>", file=sys.stderr)
            return 1
        return cmd_get_increment(sys.argv[2])

    elif command == "detect-type":
        if len(sys.argv) < 3:
            print("Usage: commit-helper.py detect-type <file-path>", file=sys.stderr)
            return 1
        return cmd_detect_type(sys.argv[2])

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
