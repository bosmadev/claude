#!/usr/bin/env python3
"""
Sanitize settings.json by replacing Windows-specific paths with portable equivalents.

Usage:
    python scripts/sanitize-settings.py              # Sanitize in place
    python scripts/sanitize-settings.py --dry-run    # Preview changes without writing
    python scripts/sanitize-settings.py --revert     # Restore from git HEAD
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_repo_root():
    """Get repository root using git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        # Fallback: assume script is in scripts/ subdirectory
        return Path(__file__).parent.parent


def sanitize_path(path_str):
    """
    Replace Windows-specific paths with portable equivalents.

    Replacements (in order):
    1. ~/.claude → ~/.claude (backslash variant)
    2. C:/Users/Dennis/.claude → ~/.claude (forward slash variant)
    3. ${TMPDIR}/claude-tmp → ${TMPDIR}/claude-tmp
    4. C:/Users/Dennis/AppData/Local/Temp/claude-tmp → ${TMPDIR}/claude-tmp
    5. C:\\Users\\Dennis → ~/ (catch-all backslash)
    6. C:/Users/Dennis → ~/ (catch-all forward slash)
    """
    replacements = [
        # Claude config directory (backslash - as it appears in Python strings)
        ("~/.claude", "~/.claude"),
        # Claude config directory (forward slash)
        ("C:/Users/Dennis/.claude", "~/.claude"),
        # Temp directory (backslash)
        ("${TMPDIR}/claude-tmp", "${TMPDIR}/claude-tmp"),
        # Temp directory (forward slash)
        ("C:/Users/Dennis/AppData/Local/Temp/claude-tmp", "${TMPDIR}/claude-tmp"),
        # Catch-all home directory (backslash)
        ("C:\\Users\\Dennis", "~/"),
        # Catch-all home directory (forward slash)
        ("C:/Users/Dennis", "~/"),
    ]

    for old, new in replacements:
        path_str = path_str.replace(old, new)

    return path_str


def sanitize_json(data):
    """Recursively sanitize all strings in JSON structure."""
    if isinstance(data, dict):
        return {k: sanitize_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [sanitize_json(item) for item in data]
    elif isinstance(data, str):
        return sanitize_path(data)
    else:
        return data


def count_replacements(original, sanitized):
    """Count total number of path replacements made."""
    count = 0

    def count_changes(orig, san):
        nonlocal count
        if isinstance(orig, dict) and isinstance(san, dict):
            for k in orig:
                if k in san:
                    count_changes(orig[k], san[k])
        elif isinstance(orig, list) and isinstance(san, list):
            for o, s in zip(orig, san):
                count_changes(o, s)
        elif isinstance(orig, str) and isinstance(san, str):
            if orig != san:
                count += 1

    count_changes(original, sanitized)
    return count


def main():
    parser = argparse.ArgumentParser(
        description="Sanitize settings.json by replacing Windows paths with portable equivalents"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to file",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="Restore settings.json from git HEAD",
    )
    args = parser.parse_args()

    repo_root = get_repo_root()
    settings_path = repo_root / "settings.json"

    if not settings_path.exists():
        print(f"[ERROR] settings.json not found at: {settings_path}", file=sys.stderr)
        return 1

    # Handle revert
    if args.revert:
        try:
            result = subprocess.run(
                ["git", "show", "HEAD:settings.json"],
                capture_output=True,
                text=True,
                check=True,
                cwd=repo_root,
            )
            original_content = result.stdout

            # Validate JSON before writing
            json.loads(original_content)

            settings_path.write_text(original_content, encoding="utf-8")
            print("[SUCCESS] Reverted settings.json from git HEAD")
            return 0
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to retrieve settings.json from git: {e}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON in git HEAD:settings.json: {e}", file=sys.stderr)
            return 1

    # Load current settings
    try:
        original_text = settings_path.read_text(encoding="utf-8")
        original_data = json.loads(original_text)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in settings.json: {e}", file=sys.stderr)
        return 1

    # Sanitize
    sanitized_data = sanitize_json(original_data)
    sanitized_text = json.dumps(sanitized_data, indent=2)

    # Count replacements
    replacement_count = count_replacements(original_data, sanitized_data)

    # Preview or write
    if args.dry_run:
        print("=== DRY RUN: Preview of changes ===\n")
        print(sanitized_text)
        print(f"\n[DRY RUN] Would replace {replacement_count} path(s)")
        return 0
    else:
        # Write sanitized version
        settings_path.write_text(sanitized_text + "\n", encoding="utf-8")
        print(f"[SUCCESS] Sanitized settings.json: {replacement_count} path(s) replaced")

        # Validate by re-parsing
        try:
            json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[WARNING] Output JSON validation failed: {e}", file=sys.stderr)
            return 1

        return 0


if __name__ == "__main__":
    sys.exit(main())
