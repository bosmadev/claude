#!/usr/bin/env python3
"""Screenshot management script for /screen skill.

Operations: list, clean (7 days), delete, find
Storage: $CLAUDE_HOME/skills/screen/screenshots/screen-{timestamp}.png
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directories to sys.path for compat import
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.compat import get_claude_home

SCREENSHOTS_DIR = get_claude_home() / "skills" / "screen" / "screenshots"
FILENAME_PREFIX = "screen-"
FILENAME_SUFFIX = ".png"
RETENTION_DAYS = 7


def parse_timestamp(filename: str) -> datetime | None:
    """Extract datetime from filename like screen-20260123-143052.png."""
    try:
        # Remove prefix and suffix
        timestamp_str = filename.replace(FILENAME_PREFIX, "").replace(FILENAME_SUFFIX, "")
        return datetime.strptime(timestamp_str, "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def get_screenshot_id(filename: str) -> str:
    """Extract ID (HHMMSS) from filename."""
    try:
        timestamp_str = filename.replace(FILENAME_PREFIX, "").replace(FILENAME_SUFFIX, "")
        return timestamp_str.split("-")[1]  # Return HHMMSS part
    except (ValueError, IndexError):
        return filename


def format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def format_date(dt: datetime) -> str:
    """Format datetime for display."""
    return dt.strftime("%b %d, %H:%M")


def get_screenshots() -> list[dict]:
    """Get all screenshots with metadata."""
    screenshots = []

    if not SCREENSHOTS_DIR.exists():
        return screenshots

    for filepath in SCREENSHOTS_DIR.glob(f"{FILENAME_PREFIX}*{FILENAME_SUFFIX}"):
        timestamp = parse_timestamp(filepath.name)
        if timestamp:
            stat = filepath.stat()
            screenshots.append({
                "filename": filepath.name,
                "path": str(filepath),
                "id": get_screenshot_id(filepath.name),
                "timestamp": timestamp,
                "created": format_date(timestamp),
                "size_bytes": stat.st_size,
                "size": format_size(stat.st_size),
            })

    # Sort by timestamp, newest first
    screenshots.sort(key=lambda x: x["timestamp"], reverse=True)
    return screenshots


def cmd_list(args: argparse.Namespace) -> int:
    """List all screenshots."""
    screenshots = get_screenshots()

    if args.limit:
        screenshots = screenshots[: args.limit]

    if args.json:
        # JSON output for programmatic use
        output = [
            {
                "filename": s["filename"],
                "path": s["path"],
                "id": s["id"],
                "created": s["timestamp"].isoformat(),
                "size_bytes": s["size_bytes"],
            }
            for s in screenshots
        ]
        print(json.dumps(output, indent=2))
        return 0

    if not screenshots:
        print(f"No screenshots found in {SCREENSHOTS_DIR}")
        return 0

    # Table output
    print(f"\nScreenshots ({SCREENSHOTS_DIR}):\n")
    print(f"{'ID':<8} | {'Filename':<28} | {'Created':<16} | {'Size':<8}")
    print(f"{'-' * 8}-+-{'-' * 28}-+-{'-' * 16}-+-{'-' * 8}")

    total_size = 0
    for s in screenshots:
        print(f"{s['id']:<8} | {s['filename']:<28} | {s['created']:<16} | {s['size']:<8}")
        total_size += s["size_bytes"]

    print(f"\nTotal: {len(screenshots)} screenshot(s) ({format_size(total_size)})")
    print("\nActions: analyze <id> | delete <id> | clean")
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    """Find a screenshot by ID."""
    screenshots = get_screenshots()
    search_id = args.id

    for s in screenshots:
        if s["id"] == search_id or s["filename"].endswith(f"-{search_id}{FILENAME_SUFFIX}"):
            if args.json:
                print(
                    json.dumps(
                        {
                            "filename": s["filename"],
                            "path": s["path"],
                            "id": s["id"],
                            "created": s["timestamp"].isoformat(),
                            "size_bytes": s["size_bytes"],
                        }
                    )
                )
            else:
                print(s["path"])
            return 0

    # Try partial match
    for s in screenshots:
        if search_id in s["id"] or search_id in s["filename"]:
            if args.json:
                print(
                    json.dumps(
                        {
                            "filename": s["filename"],
                            "path": s["path"],
                            "id": s["id"],
                            "created": s["timestamp"].isoformat(),
                            "size_bytes": s["size_bytes"],
                        }
                    )
                )
            else:
                print(s["path"])
            return 0

    print(f"Screenshot not found: {search_id}", file=sys.stderr)
    return 1


def cmd_clean(args: argparse.Namespace) -> int:
    """Delete screenshots older than retention period."""
    screenshots = get_screenshots()
    cutoff = datetime.now() - timedelta(days=RETENTION_DAYS)

    old_screenshots = [s for s in screenshots if s["timestamp"] < cutoff]

    if not old_screenshots:
        print(f"No screenshots older than {RETENTION_DAYS} days")
        return 0

    total_size = sum(s["size_bytes"] for s in old_screenshots)

    if args.dry_run:
        print(f"Found {len(old_screenshots)} screenshot(s) older than {RETENTION_DAYS} days:\n")
        for s in old_screenshots:
            print(f"  - {s['filename']} ({s['created']}) - {s['size']}")
        print(f"\nTotal: {format_size(total_size)} to free")
        return 0

    # Actually delete
    deleted_count = 0
    deleted_size = 0
    for s in old_screenshots:
        try:
            Path(s["path"]).unlink()
            deleted_count += 1
            deleted_size += s["size_bytes"]
        except OSError as e:
            print(f"Error deleting {s['filename']}: {e}", file=sys.stderr)

    print(f"Deleted {deleted_count} screenshot(s), freed {format_size(deleted_size)}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    """Delete a specific screenshot."""
    screenshots = get_screenshots()
    search_id = args.id

    target = None
    for s in screenshots:
        if s["id"] == search_id or s["filename"].endswith(f"-{search_id}{FILENAME_SUFFIX}"):
            target = s
            break

    # Try partial match
    if not target:
        for s in screenshots:
            if search_id in s["id"] or search_id in s["filename"]:
                target = s
                break

    if not target:
        print(f"Screenshot not found: {search_id}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Would delete: {target['filename']}")
        print(f"Path: {target['path']}")
        print(f"Created: {target['created']}")
        print(f"Size: {target['size']}")
        return 0

    try:
        Path(target["path"]).unlink()
        print(f"Deleted: {target['filename']}")
        return 0
    except OSError as e:
        print(f"Error deleting {target['filename']}: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Screenshot management for /screen skill")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list command
    list_parser = subparsers.add_parser("list", help="List all screenshots")
    list_parser.add_argument("--limit", "-n", type=int, help="Limit number of results")
    list_parser.add_argument("--json", action="store_true", help="Output as JSON")
    list_parser.set_defaults(func=cmd_list)

    # find command
    find_parser = subparsers.add_parser("find", help="Find a screenshot by ID")
    find_parser.add_argument("id", help="Screenshot ID (HHMMSS or partial match)")
    find_parser.add_argument("--json", action="store_true", help="Output as JSON")
    find_parser.set_defaults(func=cmd_find)

    # clean command
    clean_parser = subparsers.add_parser("clean", help=f"Delete screenshots older than {RETENTION_DAYS} days")
    clean_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    clean_parser.set_defaults(func=cmd_clean)

    # delete command
    delete_parser = subparsers.add_parser("delete", help="Delete a specific screenshot")
    delete_parser.add_argument("id", help="Screenshot ID (HHMMSS or partial match)")
    delete_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")
    delete_parser.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
