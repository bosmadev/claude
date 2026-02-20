#!/usr/bin/env python3
"""
Memory review tool for MEMORY.md health, optimization, and worktree sync.

Commands:
    analyze  - Find duplicates, stale entries, suggest consolidation
    optimize - Check size vs 200-line CC limit, suggest topic file moves
    pull     - Smart merge from main worktree (diff by heading, merge new entries)
    diff     - Show differences between main and current branch memory files
    help     - Show usage

Usage:
    python memoryreview.py [analyze|optimize|pull|diff|help]
"""

import io
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Force UTF-8 output on Windows (avoids cp1252 UnicodeEncodeError for ✓ ⚠ etc.)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ─── Constants ────────────────────────────────────────────────────────────────

CC_LINE_LIMIT = 200          # Lines auto-injected into system prompt
STALE_DAYS = 30              # Entries older than this are flagged
SECTION_SIZE_WARN = 10       # Sections larger than this -> suggest topic file
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


# ─── Memory file discovery ────────────────────────────────────────────────────

def get_claude_home() -> Path:
    """Return ~/.claude directory."""
    return Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))


def find_project_memory_dir(worktree_root: Path) -> Optional[Path]:
    """Find projects/{slug}/memory/ for a given worktree root."""
    projects_dir = worktree_root / "projects"
    if not projects_dir.exists():
        return None

    # Derive project slug from directory name (CC convention)
    # e.g. C:\Users\Dennis\.claude -> C--Users-Dennis--claude
    raw = str(worktree_root).replace("\\", "/").replace(":", "").replace("/", "--")
    slug = raw.lstrip("-")
    candidate = projects_dir / slug / "memory"
    if candidate.exists():
        return candidate

    # Fallback: find any memory/ dir under projects/
    for p in projects_dir.iterdir():
        if p.is_dir():
            m = p / "memory"
            if m.exists():
                return m
    return None


def get_current_memory_file() -> Optional[Path]:
    """Return path to MEMORY.md for the current worktree."""
    claude_home = get_claude_home()
    mem_dir = find_project_memory_dir(claude_home)
    if mem_dir is None:
        return None
    return mem_dir / "MEMORY.md"


def get_main_worktree_root() -> Optional[Path]:
    """Find the main worktree root via git worktree list."""
    try:
        result = subprocess.run(
            ["git", "-C", str(get_claude_home()), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None

        lines = result.stdout.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("worktree "):
                path = Path(line[len("worktree "):].strip())
                # The first worktree entry is always main
                return path
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def get_main_memory_file() -> Optional[Path]:
    """Return path to MEMORY.md in the main worktree."""
    main_root = get_main_worktree_root()
    if main_root is None:
        return None
    mem_dir = find_project_memory_dir(main_root)
    if mem_dir is None:
        return None
    return mem_dir / "MEMORY.md"


# ─── Parsing helpers ──────────────────────────────────────────────────────────

def parse_sections(text: str) -> dict[str, str]:
    """Split MEMORY.md by ## headings. Returns {heading_text: body_text}."""
    sections: dict[str, str] = {}
    current_heading = "__preamble__"
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_lines or current_heading != "__preamble__":
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections


def extract_dates(text: str) -> list[datetime]:
    """Extract all YYYY-MM-DD dates from text."""
    dates = []
    for m in DATE_RE.finditer(text):
        try:
            dates.append(datetime.strptime(m.group(1), "%Y-%m-%d"))
        except ValueError:
            pass
    return dates


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_analyze() -> None:
    """Analyze MEMORY.md for duplicates, stale entries, and structure issues."""
    mem_file = get_current_memory_file()
    if mem_file is None or not mem_file.exists():
        print("ERROR: Could not locate MEMORY.md")
        print("Expected at: ~/.claude/projects/{slug}/memory/MEMORY.md")
        sys.exit(1)

    text = mem_file.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    sections = parse_sections(text)

    # Remove preamble from section count
    real_sections = {k: v for k, v in sections.items() if k != "__preamble__"}

    print(f"=== MEMORY.md Analysis: {mem_file} ===\n")
    print(f"Total lines: {len(lines)}  (CC limit: {CC_LINE_LIMIT})")
    print(f"Sections (## headings): {len(real_sections)}")

    # Size warning
    if len(lines) >= CC_LINE_LIMIT:
        over = len(lines) - CC_LINE_LIMIT
        print(f"\n⚠  OVER LIMIT by {over} lines — last {over} lines are silently truncated!")
    elif len(lines) > CC_LINE_LIMIT * 0.85:
        remaining = CC_LINE_LIMIT - len(lines)
        print(f"\n⚠  Near limit: {remaining} lines remaining before truncation")
    else:
        remaining = CC_LINE_LIMIT - len(lines)
        print(f"\n✓  {remaining} lines remaining before truncation")

    # Duplicate headings
    heading_re = re.compile(r"^##+ .+")
    headings: list[str] = [ln.strip() for ln in lines if heading_re.match(ln)]
    seen: set[str] = set()
    duplicates: list[str] = []
    for h in headings:
        if h in seen:
            duplicates.append(h)
        seen.add(h)

    if duplicates:
        print(f"\n⚠  Duplicate headings ({len(duplicates)}):")
        for d in duplicates:
            print(f"   - {d}")
    else:
        print("\n✓  No duplicate headings")

    # Stale entries (entries where ALL dates are > STALE_DAYS ago)
    cutoff = datetime.now() - timedelta(days=STALE_DAYS)
    stale: list[str] = []
    for heading, body in real_sections.items():
        dates = extract_dates(heading + " " + body)
        if dates and all(d < cutoff for d in dates):
            stale.append(heading)

    if stale:
        print(f"\n⚠  Potentially stale entries (all dates > {STALE_DAYS} days ago):")
        for s in stale:
            print(f"   - ## {s}")
        print("   Consider archiving or removing outdated entries.")
    else:
        print(f"\n✓  No stale entries (no sections with all dates > {STALE_DAYS} days ago)")

    # Large sections
    large: list[tuple[str, int]] = []
    for heading, body in real_sections.items():
        section_lines = len(body.splitlines()) + 1  # +1 for heading line
        if section_lines > SECTION_SIZE_WARN:
            large.append((heading, section_lines))

    if large:
        print(f"\n📋 Large sections (> {SECTION_SIZE_WARN} lines) — consider moving to topic files:")
        for heading, count in sorted(large, key=lambda x: -x[1]):
            print(f"   - ## {heading}: {count} lines")
    else:
        print(f"\n✓  All sections are ≤ {SECTION_SIZE_WARN} lines")

    print("\n--- Done ---")


def cmd_optimize() -> None:
    """Check MEMORY.md size vs CC 200-line limit and suggest optimizations."""
    mem_file = get_current_memory_file()
    if mem_file is None or not mem_file.exists():
        print("ERROR: Could not locate MEMORY.md")
        sys.exit(1)

    text = mem_file.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    sections = parse_sections(text)
    real_sections = {k: v for k, v in sections.items() if k != "__preamble__"}

    print(f"=== MEMORY.md Optimization Report ===\n")
    print(f"Current: {len(lines)} lines  |  Limit: {CC_LINE_LIMIT} lines")

    if len(lines) >= CC_LINE_LIMIT:
        over = len(lines) - CC_LINE_LIMIT
        print(f"Status: OVER LIMIT — {over} lines are being silently truncated\n")
    else:
        remaining = CC_LINE_LIMIT - len(lines)
        pct = (len(lines) / CC_LINE_LIMIT) * 100
        print(f"Status: {pct:.0f}% full — {remaining} lines available\n")

    # Suggest moving large sections to topic files
    print("Sections that could move to topic files (linked from MEMORY.md):\n")
    candidates: list[tuple[str, int]] = []
    for heading, body in real_sections.items():
        section_lines = len(body.splitlines()) + 1
        if section_lines > SECTION_SIZE_WARN:
            candidates.append((heading, section_lines))

    if not candidates:
        print(f"  None — all sections are ≤ {SECTION_SIZE_WARN} lines")
    else:
        candidates.sort(key=lambda x: -x[1])
        total_movable = sum(c[1] for c in candidates)
        print(f"  {'Section':<45} {'Lines':>5}")
        print(f"  {'-'*45} {'-----':>5}")
        for heading, count in candidates:
            snippet = heading[:43] + ".." if len(heading) > 45 else heading
            print(f"  {snippet:<45} {count:>5}")
        print(f"\n  Total movable: {total_movable} lines → would bring MEMORY.md to "
              f"{len(lines) - total_movable + len(candidates)} lines (one link line per section)")

    # Show existing topic files
    mem_dir = mem_file.parent
    topic_files = [f.name for f in mem_dir.iterdir() if f.suffix == ".md" and f.name != "MEMORY.md"]
    if topic_files:
        print(f"\nExisting topic files in {mem_dir.name}/:")
        for tf in sorted(topic_files):
            size = (mem_dir / tf).stat().st_size
            print(f"  {tf}  ({size} bytes)")

    print("\nNOTE: This command does NOT auto-trim. Edit MEMORY.md manually or create topic files.")
    print("\n--- Done ---")


def cmd_pull() -> None:
    """Smart merge from main worktree: diff by ## heading, merge new entries only."""
    current_file = get_current_memory_file()
    main_file = get_main_memory_file()

    if current_file is None or not current_file.exists():
        print("ERROR: Current branch MEMORY.md not found")
        sys.exit(1)

    if main_file is None or not main_file.exists():
        print("ERROR: Main worktree MEMORY.md not found")
        print("Checked: main worktree via 'git worktree list'")
        sys.exit(1)

    if current_file.resolve() == main_file.resolve():
        print("INFO: Current branch IS the main worktree — nothing to pull")
        sys.exit(0)

    current_text = current_file.read_text(encoding="utf-8", errors="replace")
    main_text = main_file.read_text(encoding="utf-8", errors="replace")

    current_sections = parse_sections(current_text)
    main_sections = parse_sections(main_text)

    # Find sections in main that are missing from current
    new_headings = [h for h in main_sections if h not in current_sections and h != "__preamble__"]
    existing_headings = [h for h in main_sections if h in current_sections and h != "__preamble__"]

    print(f"=== Memory Pull: main → current ===\n")
    print(f"Main file:    {main_file}")
    print(f"Current file: {current_file}\n")
    print(f"Main sections:       {len(main_sections) - (1 if '__preamble__' in main_sections else 0)}")
    print(f"Current sections:    {len(current_sections) - (1 if '__preamble__' in current_sections else 0)}")
    print(f"New (to add):        {len(new_headings)}")
    print(f"Already present:     {len(existing_headings)}")

    if not new_headings:
        print("\n✓ Nothing to merge — current branch already has all main entries")
        return

    print(f"\nNew sections to merge:")
    for h in new_headings:
        body_preview = main_sections[h][:60].replace("\n", " ").strip()
        print(f"  + ## {h}")
        if body_preview:
            print(f"      {body_preview}...")

    # Append new sections to current MEMORY.md
    additions: list[str] = []
    for h in new_headings:
        additions.append(f"\n## {h}\n{main_sections[h]}")

    merged_text = current_text.rstrip() + "\n" + "\n".join(additions) + "\n"
    current_file.write_text(merged_text, encoding="utf-8")

    new_line_count = len(merged_text.splitlines())
    print(f"\n✓ Merged {len(new_headings)} new sections into {current_file}")
    print(f"  Line count: {len(current_text.splitlines())} → {new_line_count}")

    if new_line_count > CC_LINE_LIMIT:
        over = new_line_count - CC_LINE_LIMIT
        print(f"\n⚠  Now OVER CC limit by {over} lines — run /memoryreview optimize")

    print("\n--- Done ---")


def cmd_diff() -> None:
    """Show differences between main and current branch memory files."""
    current_file = get_current_memory_file()
    main_file = get_main_memory_file()

    if current_file is None or not current_file.exists():
        print("ERROR: Current branch MEMORY.md not found")
        sys.exit(1)

    if main_file is None or not main_file.exists():
        print("ERROR: Main worktree MEMORY.md not found")
        sys.exit(1)

    if current_file.resolve() == main_file.resolve():
        print("INFO: Current branch IS the main worktree — no diff")
        sys.exit(0)

    current_text = current_file.read_text(encoding="utf-8", errors="replace")
    main_text = main_file.read_text(encoding="utf-8", errors="replace")

    current_sections = parse_sections(current_text)
    main_sections = parse_sections(main_text)

    current_real = set(k for k in current_sections if k != "__preamble__")
    main_real = set(k for k in main_sections if k != "__preamble__")

    only_in_main = main_real - current_real
    only_in_current = current_real - main_real
    in_both = current_real & main_real

    # Check for content differences in shared sections
    content_diff: list[str] = []
    for h in in_both:
        if current_sections[h].strip() != main_sections[h].strip():
            content_diff.append(h)

    print(f"=== Memory Diff: main vs current ===\n")
    print(f"Main:    {main_file}  ({len(main_text.splitlines())} lines, {len(main_real)} sections)")
    print(f"Current: {current_file}  ({len(current_text.splitlines())} lines, {len(current_real)} sections)")

    if only_in_main:
        print(f"\n+ In main only ({len(only_in_main)}) — these would be added by /memoryreview pull:")
        for h in sorted(only_in_main):
            print(f"  + ## {h}")

    if only_in_current:
        print(f"\n- In current only ({len(only_in_current)}) — branch-specific entries:")
        for h in sorted(only_in_current):
            print(f"  - ## {h}")

    if content_diff:
        print(f"\n~ Content differs ({len(content_diff)}) — same heading, different body:")
        for h in sorted(content_diff):
            mc = len(main_sections[h].splitlines())
            cc = len(current_sections[h].splitlines())
            print(f"  ~ ## {h}  (main: {mc} lines, current: {cc} lines)")

    if not only_in_main and not only_in_current and not content_diff:
        print("\n✓ Memory files are identical")
    else:
        print(f"\nSummary: +{len(only_in_main)} main-only  -{len(only_in_current)} current-only  "
              f"~{len(content_diff)} content-diff")

    print("\n--- Done ---")


def cmd_help() -> None:
    """Show usage and examples."""
    print("""=== /memoryreview — Memory File Health & Sync ===

COMMANDS

  /memoryreview [analyze]   Analyze MEMORY.md: duplicates, stale entries,
                            consolidation suggestions (default command)

  /memoryreview optimize    Check size vs 200-line CC system prompt limit.
                            Suggests which sections to move to topic files.
                            Does NOT auto-trim — manual edits required.

  /memoryreview pull        Smart merge from main worktree:
                            - Diffs by ## heading sections
                            - Adds new headings from main to current branch
                            - Keeps branch-specific entries untouched
                            - Never overwrites or deletes existing content

  /memoryreview diff        Show differences between main and current branch:
                            - Sections only in main (can be pulled)
                            - Sections only in current (branch-specific)
                            - Sections with different content

  /memoryreview help        Show this message

NOTES

  - MEMORY.md path: ~/.claude/projects/{slug}/memory/MEMORY.md
  - CC auto-injects first 200 lines into every system prompt
  - Lines beyond 200 are silently truncated
  - Topic files (e.g. debugging.md) can hold detail, linked from MEMORY.md
  - 'pull' is safe: only appends, never removes

EXAMPLES

  # Daily health check
  /memoryreview

  # Before a long session — check if near limit
  /memoryreview optimize

  # Working on feature branch — sync latest from main
  /memoryreview pull

  # Preview before pulling
  /memoryreview diff
""")


# ─── Entrypoint ───────────────────────────────────────────────────────────────

COMMANDS = {
    "analyze": cmd_analyze,
    "optimize": cmd_optimize,
    "pull": cmd_pull,
    "diff": cmd_diff,
    "help": cmd_help,
}


def main() -> None:
    cmd = sys.argv[1].lower() if len(sys.argv) > 1 else "analyze"

    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print(f"Valid commands: {', '.join(COMMANDS)}")
        sys.exit(1)

    COMMANDS[cmd]()


if __name__ == "__main__":
    main()
