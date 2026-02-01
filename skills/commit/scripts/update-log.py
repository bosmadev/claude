#!/usr/bin/env python3
"""
Commit Tracker - Log file changes for pending commits.

Usage:
    update-log.py log <file-path> <action> <description>
    update-log.py show <file-path>
    update-log.py clear <file-path>
    update-log.py summary <file-path>

Actions: create, modify, delete

The file-path is used to detect the git repository root.
Changes are logged to {repo-root}/.claude/commit.md
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path


def is_env_file(file_path: str) -> bool:
    """Check if a file is an .env file."""
    name = Path(file_path).name
    return name == ".env" or name.startswith(".env.")


def has_dotenvx(repo_root: Path) -> bool:
    """Check if dotenvx is configured in the project."""
    # Check for .env.keys file (dotenvx encrypted keys)
    if (repo_root / ".env.keys").exists():
        return True

    # Check package.json for dotenvx scripts
    package_json = repo_root / "package.json"
    if package_json.exists():
        try:
            import json
            data = json.loads(package_json.read_text())
            scripts = data.get("scripts", {})
            for script in scripts.values():
                if "dotenvx" in str(script) or "env:encrypt" in str(script):
                    return True
            # Check devDependencies
            dev_deps = data.get("devDependencies", {})
            if "@dotenvx/dotenvx" in dev_deps:
                return True
        except (json.JSONDecodeError, KeyError):
            pass

    return False


def get_repo_root(file_path: str) -> Path | None:
    """Detect git repository root from a file path."""
    path = Path(file_path).resolve()

    # If it's a file, use its parent directory
    if path.is_file():
        path = path.parent
    elif not path.exists():
        # For non-existent paths, walk up to find existing parent
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


def get_relative_path(file_path: str, repo_root: Path) -> str:
    """Get file path relative to repo root."""
    try:
        return str(Path(file_path).resolve().relative_to(repo_root))
    except ValueError:
        return file_path


def ensure_claude_dir(repo_root: Path) -> Path:
    """Ensure .claude directory exists in repo root."""
    claude_dir = repo_root / ".claude"
    claude_dir.mkdir(exist_ok=True)
    return claude_dir


def get_commit_log_path(repo_root: Path) -> Path:
    """Get path to commit.md file."""
    return ensure_claude_dir(repo_root) / "commit.md"


def parse_existing_entries(content: str) -> list[str]:
    """Parse existing entries from commit.md content."""
    entries = []
    in_files_section = False

    for line in content.split("\n"):
        if line.strip() == "## Files Modified":
            in_files_section = True
            continue
        if line.startswith("## ") and in_files_section:
            break
        if in_files_section and line.strip().startswith("- ["):
            entries.append(line.strip())

    return entries


def format_entry(timestamp: str, action: str, rel_path: str, description: str) -> str:
    """Format a single log entry."""
    return f"- [{timestamp}] {action}: {rel_path} - {description}"


def generate_commit_log(entries: list[str], summary: str = "Auto-generated summary of changes") -> str:
    """Generate the full commit.md content."""
    lines = [
        "# Pending Changes",
        "",
        "## Files Modified",
    ]

    if entries:
        lines.extend(entries)
    else:
        lines.append("No changes logged yet.")

    lines.extend([
        "",
        "## Summary",
        summary,
        "",
    ])

    return "\n".join(lines)


def cmd_log(file_path: str, action: str, description: str) -> int:
    """Log a file change."""
    valid_actions = {"create", "modify", "delete"}
    if action not in valid_actions:
        print(f"Error: Invalid action '{action}'. Must be one of: {', '.join(valid_actions)}", file=sys.stderr)
        return 1

    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    commit_log_path = get_commit_log_path(repo_root)
    rel_path = get_relative_path(file_path, repo_root)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Read existing entries
    entries = []
    existing_summary = "Auto-generated summary of changes"
    if commit_log_path.exists():
        content = commit_log_path.read_text()
        entries = parse_existing_entries(content)

        # Preserve existing summary if present
        if "## Summary" in content:
            summary_start = content.find("## Summary") + len("## Summary")
            existing_summary = content[summary_start:].strip().split("\n")[0].strip()
            if not existing_summary or existing_summary == "Auto-generated summary of changes":
                existing_summary = "Auto-generated summary of changes"

    # Add new entry
    new_entry = format_entry(timestamp, action, rel_path, description)
    entries.append(new_entry)

    # Write updated log
    new_content = generate_commit_log(entries, existing_summary)
    commit_log_path.write_text(new_content)

    print(f"Logged: {action} {rel_path}")
    print(f"  -> {commit_log_path}")

    # Warn about .env files when dotenvx is configured
    if is_env_file(file_path) and has_dotenvx(repo_root):
        print(f"\nNote: Run `pnpm env:encrypt` before committing")

    return 0


def cmd_show(file_path: str) -> int:
    """Show current commit log."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    commit_log_path = get_commit_log_path(repo_root)
    if not commit_log_path.exists():
        print("No commit log found. Use 'log' command to start tracking changes.")
        return 0

    print(commit_log_path.read_text())
    return 0


def cmd_clear(file_path: str) -> int:
    """Clear the commit log."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    commit_log_path = get_commit_log_path(repo_root)
    new_content = generate_commit_log([])
    commit_log_path.write_text(new_content)

    print(f"Cleared commit log: {commit_log_path}")
    return 0


def cmd_summary(file_path: str) -> int:
    """Display summary information about pending changes."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    commit_log_path = get_commit_log_path(repo_root)
    if not commit_log_path.exists():
        print("No commit log found.")
        return 0

    content = commit_log_path.read_text()
    entries = parse_existing_entries(content)

    if not entries:
        print("No changes logged.")
        return 0

    # Count by action type
    counts = {"create": 0, "modify": 0, "delete": 0}
    for entry in entries:
        for action in counts:
            if f"] {action}:" in entry:
                counts[action] += 1
                break

    print(f"Pending Changes Summary ({len(entries)} total):")
    print(f"  Created: {counts['create']}")
    print(f"  Modified: {counts['modify']}")
    print(f"  Deleted: {counts['delete']}")
    print(f"\nLog file: {commit_log_path}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    command = sys.argv[1]

    if command == "log":
        if len(sys.argv) < 5:
            print("Usage: update-log.py log <file-path> <action> <description>", file=sys.stderr)
            return 1
        return cmd_log(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))

    elif command == "show":
        if len(sys.argv) < 3:
            print("Usage: update-log.py show <file-path>", file=sys.stderr)
            return 1
        return cmd_show(sys.argv[2])

    elif command == "clear":
        if len(sys.argv) < 3:
            print("Usage: update-log.py clear <file-path>", file=sys.stderr)
            return 1
        return cmd_clear(sys.argv[2])

    elif command == "summary":
        if len(sys.argv) < 3:
            print("Usage: update-log.py summary <file-path>", file=sys.stderr)
            return 1
        return cmd_summary(sys.argv[2])

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
