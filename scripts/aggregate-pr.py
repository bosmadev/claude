#!/usr/bin/env python3
"""
PR Commit Aggregation Script

Aggregates commits from a git branch into a structured PR summary.
Used by /openpr skill and @claude prepare GitHub Action.

Usage:
  python aggregate-pr.py [base-branch]   # Default: main
  python aggregate-pr.py --json          # Output as JSON for GitHub Actions
  python aggregate-pr.py --help          # Show usage

Output:
  Generates structured PR body with:
  - Summary paragraph
  - Commits grouped by type (feat, fix, refactor, etc.)
  - Build ID extracted from branch name
"""

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Commit:
    """Represents a parsed git commit."""
    hash: str
    subject: str
    body: str
    commit_type: str = ""
    scope: str = ""


@dataclass
class PRSummary:
    """Structured PR summary data."""
    build_id: str
    branch: str
    base_branch: str
    title: str
    summary: str
    commits: list[Commit] = field(default_factory=list)
    commits_by_type: dict[str, list[Commit]] = field(default_factory=dict)


# Conventional commit type descriptions for summary generation
COMMIT_TYPE_DESCRIPTIONS = {
    "feat": "new features",
    "fix": "bug fixes",
    "refactor": "code refactoring",
    "docs": "documentation updates",
    "test": "test improvements",
    "chore": "maintenance tasks",
    "perf": "performance improvements",
    "style": "code style changes",
    "config": "configuration changes",
    "cleanup": "code cleanup",
}


def run_git(args: list[str], cwd: str | None = None) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, "", str(e)


def get_repo_root() -> Path | None:
    """Get the git repository root."""
    code, stdout, _ = run_git(["rev-parse", "--show-toplevel"])
    if code == 0 and stdout:
        return Path(stdout)
    return None


def get_current_branch() -> str:
    """Get the current branch name."""
    code, stdout, _ = run_git(["branch", "--show-current"])
    if code == 0 and stdout:
        return stdout
    # Fallback for detached HEAD - use worktree name
    code, stdout, _ = run_git(["rev-parse", "--show-toplevel"])
    if code == 0:
        return Path(stdout).name
    return "unknown"


def extract_build_id(branch: str) -> str:
    """
    Extract build ID from branch name.

    Examples:
        b101 -> 101
        feature/b42-auth -> 42
        b101-feature-name -> 101
        some-branch -> some-branch (no build ID)
    """
    match = re.search(r'b(\d+)', branch)
    if match:
        return match.group(1)
    return branch


def parse_commit_type(subject: str) -> tuple[str, str, str]:
    """
    Parse conventional commit format.

    Returns (type, scope, description).
    Example: "feat(auth): add login" -> ("feat", "auth", "add login")
    """
    # Match: type(scope): description or type: description
    match = re.match(r'^(\w+)(?:\(([^)]+)\))?:\s*(.*)$', subject)
    if match:
        return match.group(1), match.group(2) or "", match.group(3)
    return "other", "", subject


def get_commits(base_branch: str = "main") -> list[Commit]:
    """Get all commits from current branch since base branch."""
    commits = []

    # Try to get commits since diverging from base
    code, stdout, _ = run_git([
        "log", f"{base_branch}..HEAD",
        "--pretty=format:%h|%s|%b---COMMIT_END---"
    ])

    if code != 0 or not stdout:
        # Fallback: get all commits on branch
        code, stdout, _ = run_git([
            "log", "--pretty=format:%h|%s|%b---COMMIT_END---"
        ])

    if code != 0 or not stdout:
        return commits

    # Parse commits
    raw_commits = stdout.split("---COMMIT_END---")
    for raw in raw_commits:
        raw = raw.strip()
        if not raw:
            continue

        parts = raw.split("|", 2)
        if len(parts) < 2:
            continue

        hash_val = parts[0]
        subject = parts[1]
        body = parts[2] if len(parts) > 2 else ""

        commit_type, scope, _ = parse_commit_type(subject)

        commits.append(Commit(
            hash=hash_val,
            subject=subject,
            body=body.strip(),
            commit_type=commit_type,
            scope=scope,
        ))

    return commits


def group_commits_by_type(commits: list[Commit]) -> dict[str, list[Commit]]:
    """Group commits by their conventional commit type."""
    grouped: dict[str, list[Commit]] = {}
    for commit in commits:
        ctype = commit.commit_type or "other"
        if ctype not in grouped:
            grouped[ctype] = []
        grouped[ctype].append(commit)
    return grouped


def generate_summary(commits_by_type: dict[str, list[Commit]]) -> str:
    """Generate a summary paragraph from commit types."""
    if not commits_by_type:
        return "No commits found."

    parts = []

    # Order: feat, fix, refactor, then others
    priority_order = ["feat", "fix", "refactor", "perf", "docs", "test", "config", "cleanup", "chore"]

    for ctype in priority_order:
        if ctype in commits_by_type:
            count = len(commits_by_type[ctype])
            desc = COMMIT_TYPE_DESCRIPTIONS.get(ctype, f"{ctype} changes")
            if count == 1:
                parts.append(f"1 {desc.rstrip('s')}")  # Singular
            else:
                parts.append(f"{count} {desc}")

    # Add any remaining types
    for ctype in commits_by_type:
        if ctype not in priority_order:
            count = len(commits_by_type[ctype])
            parts.append(f"{count} {ctype} changes")

    if not parts:
        return "Various code changes."

    if len(parts) == 1:
        return f"This PR includes {parts[0]}."
    elif len(parts) == 2:
        return f"This PR includes {parts[0]} and {parts[1]}."
    else:
        return f"This PR includes {', '.join(parts[:-1])}, and {parts[-1]}."


def format_commits_list(commits: list[Commit], build_id: str) -> str:
    """Format commits as numbered list with build ID prefix."""
    lines = []
    for i, commit in enumerate(commits, 1):
        # Format: b{buildId}-{n}: {subject}
        lines.append(f"- b{build_id}-{i}: {commit.subject}")
    return "\n".join(lines)


def format_commits_by_type(commits_by_type: dict[str, list[Commit]], build_id: str) -> str:
    """Format commits grouped by type."""
    sections = []

    # Track commit numbering across all types
    commit_num = 1

    # Order: feat, fix, refactor, then others alphabetically
    priority_order = ["feat", "fix", "refactor", "perf", "docs", "test", "config", "cleanup", "chore"]
    all_types = list(commits_by_type.keys())
    ordered_types = [t for t in priority_order if t in all_types]
    ordered_types += sorted([t for t in all_types if t not in priority_order])

    for ctype in ordered_types:
        commits = commits_by_type[ctype]
        type_lines = []
        for commit in commits:
            type_lines.append(f"- b{build_id}-{commit_num}: {commit.subject}")
            commit_num += 1
        sections.append(f"### {ctype}\n{chr(10).join(type_lines)}")

    return "\n\n".join(sections)


def aggregate_pr(base_branch: str = "main") -> PRSummary:
    """Main aggregation function - returns structured PR data."""
    branch = get_current_branch()
    build_id = extract_build_id(branch)
    commits = get_commits(base_branch)
    commits_by_type = group_commits_by_type(commits)
    summary = generate_summary(commits_by_type)

    # Generate title
    if build_id.isdigit():
        title = f"Build {build_id}"
    else:
        title = f"Build: {build_id}"

    return PRSummary(
        build_id=build_id,
        branch=branch,
        base_branch=base_branch,
        title=title,
        summary=summary,
        commits=commits,
        commits_by_type=commits_by_type,
    )


def format_pr_body(pr: PRSummary) -> str:
    """Format PR body as markdown."""
    commits_section = format_commits_by_type(pr.commits_by_type, pr.build_id)

    # Collect detailed changes from commit bodies
    details = []
    for commit in pr.commits:
        if commit.body:
            details.append(f"**{commit.hash}**: {commit.body}")

    details_section = "\n\n".join(details) if details else "_No detailed descriptions provided._"

    return f"""## Summary

{pr.summary}

## Commits

{commits_section}

## Details

{details_section}
"""


def format_squash_message(pr: PRSummary, pr_url: str = "", version: str = "") -> str:
    """
    Format the squash commit message.

    Format:
    Build {id}: {summary title} ({version})

    ## Summary
    {summary paragraph}

    ## Changes
    {commits list}

    ## Details
    {commit bodies}

    PR: {url}
    """
    commits_list = format_commits_list(pr.commits, pr.build_id)

    # Collect details from commit bodies
    details = []
    for commit in pr.commits:
        if commit.body:
            details.append(commit.body)
    details_section = "\n".join(details) if details else ""

    # Add version to title if provided
    title = pr.title
    if version:
        title += f" ({version})"

    msg = f"""{title}

## Summary
{pr.summary}

## Changes
{commits_list}
"""

    if details_section:
        msg += f"\n## Details\n{details_section}\n"

    if pr_url:
        msg += f"\nPR: {pr_url}"

    return msg


def to_json(pr: PRSummary, version: str = "") -> str:
    """Convert PR summary to JSON for GitHub Actions."""
    data = {
        "build_id": pr.build_id,
        "branch": pr.branch,
        "base_branch": pr.base_branch,
        "title": pr.title,
        "summary": pr.summary,
        "commit_count": len(pr.commits),
        "commits": [
            {
                "hash": c.hash,
                "subject": c.subject,
                "type": c.commit_type,
                "scope": c.scope,
            }
            for c in pr.commits
        ],
        "body": format_pr_body(pr),
    }

    if version:
        data["version"] = version

    return json.dumps(data, indent=2)


def print_help():
    """Print usage information."""
    print("""aggregate-pr.py - Aggregate commits for PR creation

Usage:
  python aggregate-pr.py [options] [base-branch]

Options:
  --json          Output as JSON (for GitHub Actions)
  --squash        Output squash commit message format
  --version VER   Include version in output (e.g., 1.0.6)
  --help          Show this help

Arguments:
  base-branch     Target branch for PR (default: main)

Examples:
  python aggregate-pr.py                        # PR to main, markdown output
  python aggregate-pr.py develop                # PR to develop
  python aggregate-pr.py --json                 # JSON output for Actions
  python aggregate-pr.py --squash --version 1.0.6  # With version number
""")


def main():
    """CLI entry point."""
    args = sys.argv[1:]

    # Parse flags
    output_json = "--json" in args
    output_squash = "--squash" in args
    show_help = "--help" in args or "-h" in args

    # Parse --version flag
    version = ""
    if "--version" in args:
        try:
            version_index = args.index("--version")
            if version_index + 1 < len(args):
                version = args[version_index + 1]
                # Remove both --version and its value
                args = args[:version_index] + args[version_index + 2:]
            else:
                print("Error: --version requires a value", file=sys.stderr)
                sys.exit(1)
        except ValueError:
            pass

    if show_help:
        print_help()
        sys.exit(0)

    # Remove flags to get base branch
    args = [a for a in args if not a.startswith("--") and not a.startswith("-")]
    base_branch = args[0] if args else "main"

    # Check we're in a git repo
    if not get_repo_root():
        print("Error: Not in a git repository", file=sys.stderr)
        sys.exit(1)

    # Check we're not on main/master
    branch = get_current_branch()
    if branch in ("main", "master"):
        print("Error: Cannot create PR from main/master branch", file=sys.stderr)
        sys.exit(1)

    # Aggregate
    pr = aggregate_pr(base_branch)

    if not pr.commits:
        print("Error: No commits found to include in PR", file=sys.stderr)
        sys.exit(1)

    # Output
    if output_json:
        print(to_json(pr, version))
    elif output_squash:
        print(format_squash_message(pr, "", version))
    else:
        # For markdown output, add version to title if provided
        title = pr.title
        if version:
            title += f" ({version})"
        print(f"# {title}\n")
        print(format_pr_body(pr))


if __name__ == "__main__":
    main()
