#!/usr/bin/env python3
"""
Post-Review Hook — Parse review-agents.md findings and inject TODO comments.

Dual-track Solution C: validates that review agent findings have matching
TODO-P1/P2/P3 comments in source code. If not, injects them.

Usage:
  # As a CLI tool:
  python3 post-review.py --repo-root /path/to/repo
  python3 post-review.py --dry-run
  python3 post-review.py --report-only

  # As a Claude Code hook (PostToolUse:Skill):
  Reads JSON from stdin, checks if the completed skill was "review",
  then runs the injection pipeline.

Severity mapping:
  Critical/High → TODO-P1
  Medium        → TODO-P2
  Low           → TODO-P3
"""

from __future__ import annotations

import argparse
import json
import re
import os
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Timeout guard — prevent hooks from hanging on missing stdin
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import threading
    _timeout_timer = threading.Timer(10, lambda: os._exit(0))
    _timeout_timer.daemon = True
    _timeout_timer.start()
else:
    def _timeout_handler(_signum: int, _frame: object) -> None:
        sys.exit(0)

    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(10)


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

type Severity = str  # "Critical" | "High" | "Medium" | "Low"

SEVERITY_TO_PRIORITY: dict[str, str] = {
    "critical": "P1",
    "high": "P1",
    "medium": "P2",
    "low": "P3",
}


@dataclass
class Finding:
    """A single review finding extracted from review-agents.md."""

    category: str
    severity: Severity
    file_path: str
    line_start: int
    line_end: int | None
    description: str
    raw_issue: str = ""

    @property
    def priority(self) -> str:
        return SEVERITY_TO_PRIORITY.get(self.severity.lower(), "P2")

    @property
    def todo_tag(self) -> str:
        return f"TODO-{self.priority}"

    def todo_comment(self, lang: str = "//") -> str:
        """Generate the TODO comment string."""
        desc = self.description.strip()
        return f"{lang} {self.todo_tag}: [{self.category}] {desc}"


@dataclass
class InjectionReport:
    """Summary of post-review injection results."""

    agent_inserted: int = 0
    hook_injected: int = 0
    already_existed: int = 0
    skipped_no_file: int = 0
    skipped_stale_line: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.agent_inserted} agent-inserted, "
            f"{self.hook_injected} hook-injected, "
            f"{self.already_existed} already existed"
        )

    def detail(self) -> str:
        lines = [
            f"Agent-inserted (already had TODO): {self.agent_inserted}",
            f"Hook-injected (newly added):       {self.hook_injected}",
            f"Already existed (exact match):     {self.already_existed}",
            f"Skipped (file not found):          {self.skipped_no_file}",
            f"Skipped (line out of range):       {self.skipped_stale_line}",
        ]
        if self.errors:
            lines.append(f"Errors: {len(self.errors)}")
            for err in self.errors[:5]:
                lines.append(f"  - {err}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parsing — extract findings from review-agents.md
# ---------------------------------------------------------------------------

# Matches file references like `file.ts:42` or `file.ts:42-50`
FILE_LINE_RE = re.compile(
    r"`([^`]+?\.(?:ts|tsx|js|jsx|py|rs|go|java|rb|css|scss|html|md|json|yaml|yml|toml))"
    r"(?::(\d+)(?:-(\d+))?)?`"
)

# Table row: | content | content | ... |
TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")

# Numbered list finding: 1. **Title**\n   - File: `path:line`\n   - Description
NUMBERED_FINDING_RE = re.compile(
    r"^\d+\.\s+\*\*(.+?)\*\*\s*$"
)


def _infer_severity_from_section(section_title: str) -> Severity:
    """Infer severity from the section heading."""
    title_lower = section_title.lower()
    if "critical" in title_lower:
        return "Critical"
    if "high" in title_lower:
        return "High"
    if "medium" in title_lower:
        return "Medium"
    if "low" in title_lower:
        return "Low"
    return "Medium"


def _parse_table_findings(
    lines: list[str],
    start_idx: int,
    category: str,
    severity: Severity,
) -> tuple[list[Finding], int]:
    """Parse a markdown table and extract findings.

    Returns (findings, next_line_index).
    """
    findings: list[Finding] = []
    idx = start_idx

    # Skip header row
    if idx < len(lines) and TABLE_ROW_RE.match(lines[idx]):
        idx += 1
    # Skip separator row (|---|---|...)
    if idx < len(lines) and re.match(r"^\s*\|[\s\-:|]+\|\s*$", lines[idx]):
        idx += 1

    # Parse data rows
    while idx < len(lines):
        row_match = TABLE_ROW_RE.match(lines[idx])
        if not row_match:
            break

        row_text = row_match.group(1)
        cells = [c.strip() for c in row_text.split("|")]

        # Extract file:line from any cell
        file_match = FILE_LINE_RE.search(row_text)
        if file_match:
            file_path = file_match.group(1)
            line_start = int(file_match.group(2)) if file_match.group(2) else 1
            line_end = int(file_match.group(3)) if file_match.group(3) else None

            # The issue/description is typically the first or last meaningful cell
            issue_text = cells[0] if cells else ""
            desc_text = cells[-1] if len(cells) > 1 else issue_text

            # If the first cell looks like the issue name and last is description
            # use the description; otherwise combine them
            description = desc_text if desc_text and desc_text != file_path else issue_text

            findings.append(Finding(
                category=category,
                severity=severity,
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                description=description,
                raw_issue=issue_text,
            ))

        idx += 1

    return findings, idx


def _parse_numbered_findings(
    lines: list[str],
    start_idx: int,
    category: str,
    severity: Severity,
) -> tuple[list[Finding], int]:
    """Parse numbered list findings (Critical section format).

    Format:
    1. **Title**
       - File: `path:line-line`
       - Description text
    """
    findings: list[Finding] = []
    idx = start_idx

    while idx < len(lines):
        title_match = NUMBERED_FINDING_RE.match(lines[idx])
        if not title_match:
            # Stop if we hit a heading or blank section
            if lines[idx].startswith("#") or (
                lines[idx].strip() == "---"
            ):
                break
            idx += 1
            continue

        title = title_match.group(1)
        file_path = ""
        line_start = 1
        line_end = None
        description = title

        # Scan sub-items
        idx += 1
        while idx < len(lines) and lines[idx].startswith("   "):
            line = lines[idx].strip()

            # File: `path:line`
            file_match = FILE_LINE_RE.search(line)
            if file_match and line.lower().startswith("- file:"):
                file_path = file_match.group(1)
                line_start = int(file_match.group(2)) if file_match.group(2) else 1
                line_end = int(file_match.group(3)) if file_match.group(3) else None
            elif line.startswith("- ") and not line.lower().startswith("- file:"):
                # Description line
                description = line[2:].strip()

            idx += 1

        if file_path:
            findings.append(Finding(
                category=category,
                severity=severity,
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                description=description,
                raw_issue=title,
            ))

    return findings, idx


def parse_review_findings(content: str) -> list[Finding]:
    """Parse review-agents.md and extract all findings with file locations."""
    lines = content.splitlines()
    findings: list[Finding] = []

    current_category = ""
    current_severity = "Medium"
    idx = 0

    while idx < len(lines):
        line = lines[idx]

        # Track section headings for category/severity context
        if line.startswith("## "):
            section = line[3:].strip()
            current_severity = _infer_severity_from_section(section)

        elif line.startswith("### "):
            subsection = line[4:].strip()
            # Category is often in the subsection, e.g. "### Security (OWASP)"
            # or "### Error Handling"
            current_category = re.sub(r"\s*\(.*?\)\s*$", "", subsection).strip()

            # Override severity from parent section for subsections under
            # "High Priority Findings", "Critical Findings", etc.

        # Detect table start (header row with pipes)
        if TABLE_ROW_RE.match(line):
            # Check if next line is separator
            if idx + 1 < len(lines) and re.match(
                r"^\s*\|[\s\-:|]+\|\s*$", lines[idx + 1]
            ):
                table_findings, idx = _parse_table_findings(
                    lines, idx, current_category, current_severity
                )
                findings.extend(table_findings)
                continue

        # Detect numbered list findings
        if NUMBERED_FINDING_RE.match(line):
            numbered_findings, idx = _parse_numbered_findings(
                lines, idx, current_category, current_severity
            )
            findings.extend(numbered_findings)
            continue

        idx += 1

    return findings


# ---------------------------------------------------------------------------
# Deduplication — check if matching TODO already exists
# ---------------------------------------------------------------------------

def _comment_prefix(file_path: str) -> str:
    """Return the comment prefix for the file type."""
    ext = Path(file_path).suffix.lower()
    if ext in (".py", ".rb", ".sh", ".bash", ".yaml", ".yml", ".toml"):
        return "#"
    if ext in (".html", ".md"):
        return "<!--"
    if ext in (".css", ".scss"):
        return "/*"
    # Default: JS/TS/Go/Rust/Java style
    return "//"


def _has_matching_todo(
    file_lines: list[str],
    target_line: int,
    finding: Finding,
    tolerance: int = 3,
) -> bool:
    """Check if a matching TODO-P1/P2/P3 comment exists within +/- tolerance lines.

    Deduplication uses two heuristics:
    1. Exact priority tag match (e.g. TODO-P1) within the tolerance window
       AND a keyword overlap with the finding description.
    2. Any TODO-P{1,2,3} that contains the finding's category name.
    """
    tag = finding.todo_tag
    category_lower = finding.category.lower()
    # Extract significant keywords from description (3+ chars, not common)
    desc_words = {
        w.lower()
        for w in re.findall(r"[a-zA-Z]{3,}", finding.description)
    } - {"the", "and", "for", "not", "with", "from", "that", "this", "are"}

    start = max(0, target_line - tolerance - 1)  # 0-indexed
    end = min(len(file_lines), target_line + tolerance)

    for i in range(start, end):
        line = file_lines[i]
        if tag in line:
            # Check for keyword overlap
            line_lower = line.lower()
            if category_lower in line_lower:
                return True
            matches = sum(1 for w in desc_words if w in line_lower)
            if matches >= 2 or (len(desc_words) <= 2 and matches >= 1):
                return True
        # Also match any TODO-P tag with exact category mention
        if re.search(r"TODO-P[123]", line) and category_lower in line.lower():
            return True

    return False


# ---------------------------------------------------------------------------
# Injection — insert TODO comments into source files
# ---------------------------------------------------------------------------

def _inject_todo(
    file_path: Path,
    finding: Finding,
    dry_run: bool = False,
) -> str:
    """Inject a TODO comment into the source file.

    Returns one of: "injected", "existed", "no_file", "stale_line", "error:..."
    """
    if not file_path.exists():
        return "no_file"

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return f"error: {exc}"

    file_lines = content.splitlines(keepends=True)
    target_line = finding.line_start

    # Validate line number is in range
    if target_line < 1 or target_line > len(file_lines) + 1:
        return "stale_line"

    # Check for existing matching TODO
    lines_no_endings = [l.rstrip("\n\r") for l in file_lines]
    if _has_matching_todo(lines_no_endings, target_line, finding):
        return "existed"

    if dry_run:
        return "injected"

    # Determine indentation from target line
    if target_line <= len(file_lines):
        target_content = file_lines[target_line - 1]
        indent_match = re.match(r"^(\s*)", target_content)
        indent = indent_match.group(1) if indent_match else ""
    else:
        indent = ""

    # Build the TODO comment
    comment_prefix = _comment_prefix(str(file_path))
    todo_text = finding.todo_comment(lang=comment_prefix)

    # For HTML/CSS comments, close them
    if comment_prefix == "<!--":
        todo_line = f"{indent}{todo_text} -->\n"
    elif comment_prefix == "/*":
        todo_line = f"{indent}{todo_text} */\n"
    else:
        todo_line = f"{indent}{todo_text}\n"

    # Insert ABOVE the target line
    insert_idx = target_line - 1
    file_lines.insert(insert_idx, todo_line)

    try:
        file_path.write_text("".join(file_lines))
    except OSError as exc:
        return f"error: {exc}"

    return "injected"


# ---------------------------------------------------------------------------
# Pipeline — orchestrate parse → deduplicate → inject
# ---------------------------------------------------------------------------

def run_pipeline(
    repo_root: Path,
    *,
    dry_run: bool = False,
    report_only: bool = False,
) -> InjectionReport:
    """Main pipeline: parse review-agents.md → inject TODOs."""
    report = InjectionReport()

    review_path = repo_root / ".claude" / "review-agents.md"
    if not review_path.exists():
        report.errors.append(f"Review file not found: {review_path}")
        return report

    try:
        content = review_path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        report.errors.append(f"Cannot read review file: {exc}")
        return report

    findings = parse_review_findings(content)

    if not findings:
        report.errors.append("No findings with file locations extracted")
        return report

    for finding in findings:
        # Resolve file path relative to repo root
        # Strip any leading lib/ or src/ if the file doesn't exist as-is
        file_path = repo_root / finding.file_path
        if not file_path.exists():
            # Try common prefixes
            for prefix in ("", "src/", "lib/", "app/"):
                candidate = repo_root / prefix / finding.file_path
                if candidate.exists():
                    file_path = candidate
                    break

        if report_only:
            # Just count — check if TODO exists without modifying
            if not file_path.exists():
                report.skipped_no_file += 1
                continue

            try:
                lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
            except (OSError, UnicodeDecodeError, ValueError):
                report.skipped_no_file += 1
                continue

            if _has_matching_todo(lines, finding.line_start, finding):
                report.already_existed += 1
            else:
                # Would need injection
                report.hook_injected += 1
            continue

        # Inject
        result = _inject_todo(file_path, finding, dry_run=dry_run)

        match result:
            case "injected":
                report.hook_injected += 1
            case "existed":
                report.already_existed += 1
            case "no_file":
                report.skipped_no_file += 1
            case "stale_line":
                report.skipped_stale_line += 1
            case _ if result.startswith("error:"):
                report.errors.append(result)

    return report


# ---------------------------------------------------------------------------
# Hook entry point — PostToolUse:Skill
# ---------------------------------------------------------------------------

def hook_post_review() -> None:
    """Claude Code hook: runs after the /review skill completes.

    Reads PostToolUse JSON from stdin. Checks if the completed tool is the
    Skill tool with skill="review". If so, runs the injection pipeline.
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Only trigger after the Skill tool completes for "review"
    if tool_name != "Skill":
        sys.exit(0)

    skill_name = tool_input.get("skill", "")
    if skill_name != "review":
        sys.exit(0)

    # Determine repo root from cwd
    cwd = data.get("cwd", ".")
    repo_root = Path(cwd)

    # Check if review-agents.md exists (may not if review just started)
    review_path = repo_root / ".claude" / "review-agents.md"
    if not review_path.exists():
        sys.exit(0)

    # Run the pipeline (not dry-run — actually inject)
    report = run_pipeline(repo_root)

    # Emit hook output
    if report.hook_injected > 0 or report.already_existed > 0:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": (
                    f"POST-REVIEW TODO INJECTION COMPLETE\n\n"
                    f"{report.summary()}\n\n"
                    f"{report.detail()}\n\n"
                    f"Run `/repotodo list` to see all TODOs."
                ),
            }
        }
        print(json.dumps(output))

    sys.exit(0)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI and hook dispatch."""
    # If called as a hook (first arg is a hook mode), dispatch to hook handler
    if len(sys.argv) >= 2 and sys.argv[1] == "hook":
        hook_post_review()
        return

    # Otherwise, run as CLI tool
    parser = argparse.ArgumentParser(
        description="Post-review TODO injector: parse review-agents.md and inject TODO comments.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root directory (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Only report alignment counts, do not inject",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed output",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()

    if args.verbose:
        print(f"Repository root: {repo_root}")
        print(f"Review file:     {repo_root / '.claude' / 'review-agents.md'}")
        print()

    report = run_pipeline(
        repo_root,
        dry_run=args.dry_run,
        report_only=args.report_only,
    )

    # Print results
    prefix = "[DRY RUN] " if args.dry_run else ""
    prefix = "[REPORT] " if args.report_only else prefix

    print(f"{prefix}{report.summary()}")

    if args.verbose:
        print()
        print(report.detail())

    if report.errors:
        print(f"\nErrors ({len(report.errors)}):", file=sys.stderr)
        for err in report.errors:
            print(f"  - {err}", file=sys.stderr)

    # Exit code: 0 if no errors, 1 if errors
    sys.exit(1 if report.errors and not report.hook_injected else 0)


if __name__ == "__main__":
    main()
