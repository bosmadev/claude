#!/usr/bin/env python3
"""
Session Index Repair Script

Repairs Claude Code sessions-index.json by:
- Finding orphaned session files (on disk but not in index)
- Detecting dead entries (in index but no file on disk)
- Fixing customTitle collisions (append date suffix)
- Backing up before modifications

Usage:
    python repair-sessions-index.py              # Dry-run (report only)
    python repair-sessions-index.py --fix        # Apply fixes
    python repair-sessions-index.py --verbose    # Detailed output
"""

import argparse
import io
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Fix Windows cp1252 encoding for Unicode output
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# UUID pattern for session file detection
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl$",
    re.IGNORECASE
)

# Display limits for orphaned sessions
MAX_VERBOSE_SESSIONS = 10
MAX_DEFAULT_SESSIONS = 5


def format_size(size_bytes: int) -> str:
    """Format byte size as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


def parse_session_file(session_path: Path) -> dict[str, Any] | None:
    """
    Parse a session JSONL file to extract metadata.

    Returns dict with:
        - sessionId: UUID from first message
        - firstPrompt: First user message content (truncated)
        - customTitle: From custom-title event if present
        - messageCount: Total message count
        - created: ISO timestamp from first message
        - modified: ISO timestamp from last message
        - gitBranch: From first message metadata
        - isSidechain: From first message metadata
    """
    try:
        lines = session_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        print(f"  ✗ Failed to read {session_path.name}: {e}", file=sys.stderr)
        return None

    if not lines:
        return None

    session_id = None
    first_prompt = "No prompt"
    custom_title = None
    message_count = 0
    created = None
    modified = None
    git_branch = None
    is_sidechain = False

    # Parse JSONL line by line
    for line in lines:
        if not line.strip():
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Extract sessionId from first line with it
        if not session_id and "sessionId" in data:
            session_id = data["sessionId"]

        # Extract gitBranch and isSidechain from first line
        if git_branch is None and "gitBranch" in data:
            git_branch = data.get("gitBranch", "main")
        if "isSidechain" in data:
            is_sidechain = data.get("isSidechain", False)

        # Extract timestamps
        if "timestamp" in data:
            ts = data["timestamp"]
            if not created:
                created = ts
            modified = ts  # Keep updating to get last timestamp

        # Count messages (look for type: user or type: assistant)
        if data.get("type") in ("user", "assistant", "tool_use", "tool_result"):
            message_count += 1

        # Extract first user prompt
        if data.get("type") == "user" and first_prompt == "No prompt":
            message = data.get("message", {})
            content = message.get("content", "")
            if isinstance(content, str) and content.strip():
                # Truncate to ~80 chars for summary
                first_prompt = content[:80].strip()
                if len(content) > 80:
                    first_prompt += "..."

        # Detect customTitle from custom-title event
        if data.get("type") == "custom-title":
            custom_title = data.get("customTitle")

    if not session_id:
        # Try to extract from filename as fallback
        session_id = session_path.stem

    return {
        "sessionId": session_id,
        "fullPath": str(session_path.absolute()),
        "fileMtime": int(session_path.stat().st_mtime * 1000),  # milliseconds
        "firstPrompt": first_prompt,
        "customTitle": custom_title,
        "summary": first_prompt,  # Placeholder, would need LLM for better summary
        "messageCount": message_count,
        "created": created or datetime.fromtimestamp(session_path.stat().st_ctime, tz=timezone.utc).isoformat(),
        "modified": modified or datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc).isoformat(),
        "gitBranch": git_branch or "main",
        "projectPath": str(session_path.parent.absolute()),
        "isSidechain": is_sidechain,
    }


def find_orphaned_sessions(project_dir: Path, index_data: dict) -> list[dict]:
    """Find session files on disk that are not in sessions-index.json."""
    indexed_ids = {entry["sessionId"] for entry in index_data.get("entries", [])}

    orphaned = []
    for session_file in project_dir.glob("*.jsonl"):
        if not UUID_PATTERN.match(session_file.name):
            continue

        session_id = session_file.stem
        if session_id not in indexed_ids:
            metadata = parse_session_file(session_file)
            if metadata:
                orphaned.append(metadata)

    # Sort by creation date (most recent first)
    orphaned.sort(key=lambda x: x.get("created", ""), reverse=True)
    return orphaned


def find_dead_entries(project_dir: Path, index_data: dict) -> list[dict]:
    """Find index entries with no corresponding .jsonl file."""
    dead = []
    for entry in index_data.get("entries", []):
        session_path = Path(entry["fullPath"])
        if not session_path.exists():
            dead.append(entry)
    return dead


def detect_title_collisions(entries: list[dict]) -> dict[str, list[dict]]:
    """Detect entries with duplicate customTitle values."""
    title_map = defaultdict(list)

    for entry in entries:
        custom_title = entry.get("customTitle")
        if custom_title:
            title_map[custom_title].append(entry)

    # Return only titles with collisions (>1 entry)
    return {title: entries for title, entries in title_map.items() if len(entries) > 1}


def fix_title_collisions(entries: list[dict]) -> None:
    """Fix customTitle collisions by appending date suffix."""
    collisions = detect_title_collisions(entries)

    for title, collision_entries in collisions.items():
        # Sort by creation date
        collision_entries.sort(key=lambda x: x.get("created", ""))

        # Rename all but the first (oldest keeps original name)
        for i, entry in enumerate(collision_entries[1:], start=2):
            # Validate entry structure
            if not isinstance(entry, dict):
                continue

            # Extract date from created timestamp
            created = entry.get("created", "")
            try:
                date_obj = datetime.fromisoformat(created.replace("Z", "+00:00"))
                date_str = date_obj.strftime("%Y-%m-%d")
            except (ValueError, AttributeError, TypeError):
                date_str = "unknown"

            entry["customTitle"] = f"{title} ({date_str})"


def backup_index(index_path: Path) -> Path:
    """Create backup of sessions-index.json before modifications."""
    backup_path = index_path.with_suffix(".json.bak")
    backup_path.write_text(index_path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def repair_project(project_dir: Path, fix: bool, verbose: bool) -> dict:
    """
    Repair sessions-index.json for a single project directory.

    Returns dict with repair statistics.
    """
    index_path = project_dir / "sessions-index.json"

    if not index_path.exists():
        if fix:
            # Bootstrap: create empty index so repair can populate it
            index_path.write_text('{"entries": []}', encoding="utf-8")
            print(f"  ✓ Bootstrapped new sessions-index.json in {project_dir.name}", file=sys.stderr)
        else:
            return {"error": f"sessions-index.json not found in {project_dir} (use --fix to bootstrap)"}

    # Load existing index
    try:
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Failed to read index: {e}"}

    # Count existing entries
    existing_entries = index_data.get("entries", [])
    indexed_count = len(existing_entries)

    # Find orphaned sessions
    orphaned = find_orphaned_sessions(project_dir, index_data)
    orphaned_count = len(orphaned)

    # Find dead entries
    dead = find_dead_entries(project_dir, index_data)
    dead_count = len(dead)

    # Count .jsonl files on disk
    disk_count = len([f for f in project_dir.glob("*.jsonl") if UUID_PATTERN.match(f.name)])

    # Detect title collisions (before fixing)
    collisions_before = detect_title_collisions(existing_entries + orphaned)
    collision_count = sum(len(entries) for entries in collisions_before.values())

    stats = {
        "project_dir": str(project_dir),
        "indexed": indexed_count,
        "on_disk": disk_count,
        "orphaned": orphaned_count,
        "dead": dead_count,
        "collisions": len(collisions_before),
        "collision_entries": collision_count,
        "orphaned_sessions": orphaned[:MAX_VERBOSE_SESSIONS] if verbose else orphaned[:MAX_DEFAULT_SESSIONS],
    }

    if fix:
        # Backup before modifications
        backup_path = backup_index(index_path)
        stats["backup"] = str(backup_path)

        # Remove dead entries
        cleaned_entries = [e for e in existing_entries if e not in dead]

        # Add orphaned sessions
        all_entries = cleaned_entries + orphaned

        # Fix title collisions
        fix_title_collisions(all_entries)

        # Sort by creation date (most recent first)
        all_entries.sort(key=lambda x: x.get("created", ""), reverse=True)

        # Update index data
        index_data["entries"] = all_entries

        # Write updated index
        index_path.write_text(
            json.dumps(index_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        stats["fixed"] = True
        stats["new_total"] = len(all_entries)

    return stats


def run_hook_mode() -> None:
    """Run as SessionStart hook — auto-fix silently, output hook JSON.

    Consumes stdin (hook protocol), runs repair, outputs hook response.
    Only prints to stderr if repairs were actually made.
    """
    # Consume stdin (SessionStart sends JSON we don't need)
    try:
        sys.stdin.read()
    except Exception:
        pass

    claude_dir = Path.home() / ".claude" / "projects"
    if not claude_dir.exists():
        sys.stdout.write('{"continue":true,"suppressOutput":true}')
        return

    # Scan ALL project dirs — those with existing index AND those with JSONL files but no index
    project_dirs = [
        d for d in claude_dir.iterdir()
        if d.is_dir() and (
            (d / "sessions-index.json").exists()
            or any(UUID_PATTERN.match(f.name) for f in d.glob("*.jsonl"))
        )
    ]

    total_fixed = 0
    total_bootstrapped = 0
    for project_dir in project_dirs:
        was_missing = not (project_dir / "sessions-index.json").exists()
        stats = repair_project(project_dir, fix=True, verbose=False)
        if stats.get("fixed") and stats.get("orphaned", 0) > 0:
            total_fixed += stats["orphaned"]
        if was_missing and stats.get("fixed"):
            total_bootstrapped += 1

    if total_fixed > 0 or total_bootstrapped > 0:
        parts = []
        if total_fixed > 0:
            parts.append(f"re-indexed {total_fixed} orphaned session(s)")
        if total_bootstrapped > 0:
            parts.append(f"bootstrapped {total_bootstrapped} new index(es)")
        print(f"[session-repair] {', '.join(parts)}", file=sys.stderr)

    sys.stdout.write('{"continue":true,"suppressOutput":true}')


def main() -> None:
    """Run session index repair across all projects."""
    parser = argparse.ArgumentParser(
        description="Repair Claude Code sessions-index.json files"
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply fixes (default: dry-run only)"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output"
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress output unless fixes applied"
    )
    parser.add_argument(
        "--hook",
        action="store_true",
        help="Run as SessionStart hook (auto-fix, hook JSON output)"
    )
    parser.add_argument(
        "--project",
        type=str,
        help="Repair specific project only (default: all projects)"
    )
    args = parser.parse_args()

    if args.hook:
        run_hook_mode()
        return

    claude_dir = Path.home() / ".claude" / "projects"

    if not claude_dir.exists():
        print(f"✗ Claude projects directory not found: {claude_dir}", file=sys.stderr)
        sys.exit(1)

    # Find all project directories with sessions-index.json
    if args.project:
        project_dirs = [claude_dir / args.project]
        if not project_dirs[0].exists():
            print(f"✗ Project directory not found: {project_dirs[0]}", file=sys.stderr)
            sys.exit(1)
    else:
        # Include dirs with existing index OR dirs with JSONL session files (for bootstrapping)
        project_dirs = [
            d for d in claude_dir.iterdir()
            if d.is_dir() and (
                (d / "sessions-index.json").exists()
                or (args.fix and any(UUID_PATTERN.match(f.name) for f in d.glob("*.jsonl")))
            )
        ]

    if not project_dirs:
        print("✗ No projects with sessions found (use --fix to bootstrap missing indexes)", file=sys.stderr)
        sys.exit(1)

    total_orphaned = 0
    total_dead = 0
    total_collisions = 0
    all_stats = []

    for project_dir in project_dirs:
        stats = repair_project(project_dir, args.fix, args.verbose)
        all_stats.append((project_dir, stats))

        if "error" not in stats:
            total_orphaned += stats["orphaned"]
            total_dead += stats["dead"]
            total_collisions += stats["collisions"]

    # Quiet mode: suppress output when nothing to report
    if args.quiet and total_orphaned == 0 and total_dead == 0 and total_collisions == 0:
        return

    print("Session Index Repair Report")
    print("=" * 60)

    if not args.fix:
        print("⚠ DRY-RUN MODE (use --fix to apply changes)\n")

    for project_dir, stats in all_stats:
        if "error" in stats:
            print(f"\n✗ {project_dir.name}: {stats['error']}", file=sys.stderr)
            continue

        print(f"\nProject: {project_dir.name}")
        print(f"  Indexed: {stats['indexed']} sessions")
        print(f"  On disk: {stats['on_disk']} .jsonl files")
        print(f"  Orphaned: {stats['orphaned']} sessions (not in index)")
        print(f"  Dead entries: {stats['dead']} (in index, no file)")
        print(f"  Title collisions: {stats['collisions']} ({stats['collision_entries']} entries)")

        if stats["orphaned"] > 0 and args.verbose:
            print(f"\n  Top orphaned sessions:")
            for session in stats["orphaned_sessions"]:
                session_id = session["sessionId"][:8]
                # Get actual file size
                session_path = Path(session["fullPath"])
                size = format_size(session_path.stat().st_size if session_path.exists() else 0)
                created = session.get("created", "unknown")[:10]
                first_prompt = session.get("firstPrompt", "")[:60]
                print(f"    {session_id}... | {size:>8} | {created} | \"{first_prompt}...\"")

        if args.fix and stats.get("fixed"):
            print(f"\n  ✓ Repaired index ({stats['new_total']} total sessions)")
            print(f"  ✓ Backup saved: {Path(stats['backup']).name}")

    print(f"\n{'=' * 60}")
    print(f"Total across {len(project_dirs)} project(s):")
    print(f"  Orphaned: {total_orphaned}")
    print(f"  Dead: {total_dead}")
    print(f"  Collisions: {total_collisions}")

    if not args.fix and (total_orphaned > 0 or total_dead > 0 or total_collisions > 0):
        print(f"\n⚠ Run with --fix to repair index")


if __name__ == "__main__":
    main()
