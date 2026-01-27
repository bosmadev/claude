#!/usr/bin/env python3
"""
OpenPR Helper - Squash commits and create pull requests with Build N titles.

Usage:
    openpr-helper.py generate <file-path>     - Generate pending-pr.md
    openpr-helper.py get-title <file-path>    - Get PR title from branch
    openpr-helper.py get-commits <file-path>  - List commits to squash

The file-path is used to detect the git repository root.
"""

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


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

        # Fallback: use worktree directory name
        return repo_root.name

    except subprocess.CalledProcessError:
        return repo_root.name


def extract_build_number(branch: str) -> str | None:
    """Extract build number from branch name (b101 -> 101)."""
    # Pattern: 'b' followed by digits
    match = re.search(r"b(\d+)", branch)
    if match:
        return match.group(1)
    return None


def get_pr_title(branch: str) -> str:
    """Generate PR title from branch name."""
    build_num = extract_build_number(branch)
    if build_num:
        return f"Build {build_num}"
    # Fallback: use sanitized branch name
    return branch.replace("/", "-").replace("_", " ").title()


def get_base_branch(repo_root: Path) -> str:
    """Determine the base branch for the PR."""
    # Check if 'main' exists
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "main"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return "main"
    except subprocess.CalledProcessError:
        pass

    # Check if 'master' exists
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--verify", "master"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return "master"
    except subprocess.CalledProcessError:
        pass

    return "main"  # Default


def get_commits_since_base(repo_root: Path, base_branch: str) -> list[dict]:
    """Get list of commits since divergence from base branch."""
    try:
        result = subprocess.run(
            ["git", "log", f"{base_branch}..HEAD", "--oneline", "--reverse"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

        commits = []
        for line in result.stdout.strip().split("\n"):
            if line:
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    commits.append({"hash": parts[0], "message": parts[1]})
                elif len(parts) == 1:
                    commits.append({"hash": parts[0], "message": ""})

        return commits

    except subprocess.CalledProcessError:
        return []


def categorize_commits(commits: list[dict]) -> dict[str, list[str]]:
    """Categorize commits by conventional commit type."""
    categories = {
        "feat": [],
        "fix": [],
        "docs": [],
        "style": [],
        "refactor": [],
        "test": [],
        "chore": [],
        "build": [],
        "ci": [],
        "perf": [],
        "other": [],
    }

    for commit in commits:
        message = commit["message"]
        categorized = False

        for cat in categories:
            if cat == "other":
                continue
            # Check if message starts with type: or type(scope):
            if re.match(rf"^{cat}(\([^)]+\))?:", message):
                # Extract the description part
                desc = re.sub(rf"^{cat}(\([^)]+\))?: ?", "", message)
                categories[cat].append(desc)
                categorized = True
                break

        if not categorized:
            categories["other"].append(message)

    # Remove empty categories
    return {k: v for k, v in categories.items() if v}


def generate_summary(commits: list[dict]) -> str:
    """Generate summary from commits."""
    if not commits:
        return "No commits to summarize."

    categorized = categorize_commits(commits)
    lines = []

    type_labels = {
        "feat": "Features",
        "fix": "Bug Fixes",
        "docs": "Documentation",
        "style": "Style",
        "refactor": "Refactoring",
        "test": "Tests",
        "chore": "Chores",
        "build": "Build",
        "ci": "CI",
        "perf": "Performance",
        "other": "Other Changes",
    }

    for cat, items in categorized.items():
        if items:
            lines.append(f"### {type_labels.get(cat, cat.title())}")
            for item in items:
                lines.append(f"- {item}")
            lines.append("")

    return "\n".join(lines).strip() if lines else "- Various updates and improvements"


def generate_pending_pr(repo_root: Path) -> str:
    """Generate pending-pr.md content."""
    branch = get_branch_name(repo_root)
    pr_title = get_pr_title(branch)
    base_branch = get_base_branch(repo_root)
    commits = get_commits_since_base(repo_root, base_branch)
    summary = generate_summary(commits)

    # Format commits list
    commits_list = ""
    if commits:
        for commit in commits:
            commits_list += f"- `{commit['hash']}` {commit['message']}\n"
    else:
        commits_list = "No commits found."

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = f"""# Pending Pull Request

Generated: {timestamp}

## PR Title

{pr_title}

## Branch

{branch} -> {base_branch}

## Summary

{summary}

## Commits to Squash ({len(commits)} total)

{commits_list}
## Test Plan

- [ ] Functionality tested locally
- [ ] Unit tests pass (`pnpm test`)
- [ ] Build succeeds (`pnpm build`)
- [ ] Lint passes (`pnpm lint`)

## PR Body Preview

```markdown
## Summary

{summary}

## Test plan

- [ ] Functionality tested locally
- [ ] All tests pass
- [ ] Build succeeds
```

---

**Actions:**
- Run `/openpr confirm` to squash commits and create this PR
- Run `/openpr abort` to cancel
- Edit this file to modify the PR before creating

**Note:** This will squash all {len(commits)} commits into a single commit titled "{pr_title}"
"""

    return content


def cmd_generate(file_path: str) -> int:
    """Generate pending-pr.md."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    branch = get_branch_name(repo_root)
    if branch in ("main", "master"):
        print("Error: Cannot create PR from main/master branch", file=sys.stderr)
        return 1

    pending_path = repo_root / "pending-pr.md"

    if pending_path.exists():
        print(f"Warning: pending-pr.md already exists at {pending_path}")
        print("Run '/openpr abort' first or delete the file manually.")
        return 1

    content = generate_pending_pr(repo_root)
    pending_path.write_text(content)

    print(f"Generated: {pending_path}")
    print(content)
    return 0


def cmd_get_title(file_path: str) -> int:
    """Print PR title from branch name."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    branch = get_branch_name(repo_root)
    title = get_pr_title(branch)
    print(title)
    return 0


def cmd_get_commits(file_path: str) -> int:
    """Print commits to squash."""
    repo_root = get_repo_root(file_path)
    if not repo_root:
        print(f"Error: '{file_path}' is not in a git repository", file=sys.stderr)
        return 1

    base_branch = get_base_branch(repo_root)
    commits = get_commits_since_base(repo_root, base_branch)

    for commit in commits:
        print(f"{commit['hash']} {commit['message']}")

    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    command = sys.argv[1]

    if command == "generate":
        if len(sys.argv) < 3:
            print("Usage: openpr-helper.py generate <file-path>", file=sys.stderr)
            return 1
        return cmd_generate(sys.argv[2])

    elif command == "get-title":
        if len(sys.argv) < 3:
            print("Usage: openpr-helper.py get-title <file-path>", file=sys.stderr)
            return 1
        return cmd_get_title(sys.argv[2])

    elif command == "get-commits":
        if len(sys.argv) < 3:
            print("Usage: openpr-helper.py get-commits <file-path>", file=sys.stderr)
            return 1
        return cmd_get_commits(sys.argv[2])

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
