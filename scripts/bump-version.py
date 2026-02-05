#!/usr/bin/env python3
"""
Version Bumping Utility

Analyzes commit messages to determine semantic version bump type
and calculates the next version number.

Used by GitHub Actions workflow to auto-bump package.json versions
after PR merges.

Usage:
  python bump-version.py --commits <commits_json> --current <version>
  python bump-version.py --file package.json --commits <commits_json>
  python bump-version.py --help

Examples:
  python bump-version.py --commits '["feat: add auth", "fix: login"]' --current 1.0.5
  python bump-version.py --file package.json --commits '["feat!: breaking change"]'
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Literal


def parse_version(version_str: str) -> tuple[int, int, int]:
    """
    Parse a semver version string into (major, minor, patch).

    Examples:
        "1.0.5" -> (1, 0, 5)
        "v2.3.1" -> (2, 3, 1)
    """
    # Strip 'v' prefix if present
    version_str = version_str.lstrip('v')

    # Match major.minor.patch
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version_str)
    if not match:
        raise ValueError(f"Invalid version format: {version_str}")

    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def format_version(major: int, minor: int, patch: int) -> str:
    """Format version tuple as semver string."""
    return f"{major}.{minor}.{patch}"


def determine_bump_type(commits: list[str]) -> Literal["major", "minor", "patch"]:
    """
    Analyze commit messages to determine semver bump type.

    Rules:
    - BREAKING CHANGE or ! suffix -> major
    - feat: prefix -> minor
    - fix:, refactor:, docs:, etc. -> patch

    Examples:
        ["feat!: breaking change"] -> "major"
        ["feat: add login"] -> "minor"
        ["fix: button bug"] -> "patch"
    """
    for commit in commits:
        # Check for breaking change indicators
        if "BREAKING" in commit.upper() or "!" in commit.split(":")[0]:
            return "major"

        # Check for feature commits
        if commit.startswith("feat"):
            return "minor"

    # Default to patch (fix, refactor, docs, chore, etc.)
    return "patch"


def bump_version(
    current_version: str,
    bump_type: Literal["major", "minor", "patch"]
) -> str:
    """
    Calculate next version based on current version and bump type.

    Examples:
        bump_version("1.0.5", "patch") -> "1.0.6"
        bump_version("1.0.5", "minor") -> "1.1.0"
        bump_version("1.0.5", "major") -> "2.0.0"
    """
    major, minor, patch = parse_version(current_version)

    if bump_type == "major":
        return format_version(major + 1, 0, 0)
    elif bump_type == "minor":
        return format_version(major, minor + 1, 0)
    else:  # patch
        return format_version(major, minor, patch + 1)


def read_version_from_file(file_path: Path) -> str:
    """
    Read current version from a package file.

    Supports:
    - package.json (Node.js)
    - pyproject.toml (Python)
    - Cargo.toml (Rust)
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if file_path.name == "package.json":
        data = json.loads(file_path.read_text())
        return data.get("version", "0.0.0")

    elif file_path.name == "pyproject.toml":
        # Simple TOML parsing for version field
        content = file_path.read_text()
        match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        if match:
            return match.group(1)
        raise ValueError("No version field found in pyproject.toml")

    elif file_path.name == "Cargo.toml":
        # Simple TOML parsing for version field
        content = file_path.read_text()
        match = re.search(r'^version\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        if match:
            return match.group(1)
        raise ValueError("No version field found in Cargo.toml")

    else:
        raise ValueError(f"Unsupported file type: {file_path.name}")


def parse_commits(commits_arg: str) -> list[str]:
    """
    Parse commits from command line argument.

    Accepts:
    - JSON array: '["feat: add auth", "fix: login"]'
    - Newline-separated: "feat: add auth\nfix: login"
    """
    # Try parsing as JSON first
    try:
        return json.loads(commits_arg)
    except json.JSONDecodeError:
        pass

    # Fallback to newline-separated
    return [line.strip() for line in commits_arg.split('\n') if line.strip()]


def print_help():
    """Print usage information."""
    print(__doc__)


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Calculate next semantic version based on commits",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bump-version.py --commits '["feat: add auth"]' --current 1.0.5
  python bump-version.py --file package.json --commits '["feat!: breaking"]'

Commit Format:
  feat: new feature         -> minor bump
  fix: bug fix              -> patch bump
  feat!: breaking change    -> major bump
  BREAKING CHANGE in body   -> major bump
"""
    )

    parser.add_argument(
        "--commits",
        required=True,
        help="Commit messages as JSON array or newline-separated"
    )

    parser.add_argument(
        "--current",
        help="Current version (e.g., 1.0.5)"
    )

    parser.add_argument(
        "--file",
        type=Path,
        help="Path to package file (package.json, pyproject.toml, Cargo.toml)"
    )

    parser.add_argument(
        "--show-bump-type",
        action="store_true",
        help="Show bump type instead of version"
    )

    args = parser.parse_args()

    # Determine current version
    if args.file:
        try:
            current_version = read_version_from_file(args.file)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error reading version from file: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.current:
        current_version = args.current
    else:
        print("Error: Must provide either --file or --current", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    # Parse commits
    try:
        commits = parse_commits(args.commits)
    except Exception as e:
        print(f"Error parsing commits: {e}", file=sys.stderr)
        sys.exit(1)

    if not commits:
        print("Error: No commits provided", file=sys.stderr)
        sys.exit(1)

    # Determine bump type
    bump_type = determine_bump_type(commits)

    if args.show_bump_type:
        print(bump_type)
    else:
        # Calculate and print new version
        new_version = bump_version(current_version, bump_type)
        print(new_version)


if __name__ == "__main__":
    main()
