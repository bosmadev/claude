#!/usr/bin/env python3
"""
Post-Review Hook — Parse review-agents.md findings and inject TODO comments.

Dual-track Solution C: validates that review agent findings have matching
TODO-P1/P2/P3 comments in source code. If not, injects them.

Usage:
  # As a CLI tool:
  python post-review.py --repo-root /path/to/repo
  python post-review.py --dry-run
  python post-review.py --report-only

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
import sys
from dataclasses import dataclass, field
from pathlib import Path

# sys.path needed when invoked as hook: python scripts/post-review.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import shared parsing logic
from review_parser import Finding, parse_review_findings

# Import compat utilities
from scripts.compat import setup_stdin_timeout

# ---------------------------------------------------------------------------
# Timeout guard — prevent hooks from hanging on missing stdin
# ---------------------------------------------------------------------------

setup_stdin_timeout(10)


# ---------------------------------------------------------------------------
# Type definitions (imported from review_parser)
# ---------------------------------------------------------------------------


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
# Deduplication — check if matching TODO already exists
# ---------------------------------------------------------------------------

def _comment_prefix(file_path: str) -> str:
    """Return the comment prefix for the file type."""
    ext = Path(file_path).suffix.lower()
    if ext in (".py", ".rb", ".sh", ".bash", ".yaml", ".yml", ".toml"):
        return "#"
    if ext in (".html", ".md", ".xml", ".svg"):
        return "<!--"
    if ext in (".css", ".scss", ".sass", ".less"):
        return "/*"
    # JS/TS family and other C-style languages
    # Covers: .js .jsx .ts .tsx .vue .svelte .astro .go .rs .java .c .cpp .h .swift .kt
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
    # Validate path to prevent path traversal attacks
    try:
        resolved_path = file_path.resolve()
        # Ensure path doesn't escape repository root (basic sanity check)
        if ".." in file_path.parts:
            return "error: path traversal attempt detected"
    except (OSError, ValueError):
        return "error: invalid file path"

    if not resolved_path.exists():
        return "no_file"

    # Update file_path to use resolved path for all operations
    file_path = resolved_path

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

    # Atomic write with temporary file
    import tempfile
    try:
        # Write to temporary file first
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=file_path.suffix,
            dir=str(file_path.parent),
            delete=False,
            encoding="utf-8"
        ) as tmp:
            tmp.write("".join(file_lines))
            tmp_path = Path(tmp.name)

        # Atomic replace (atomic on POSIX, best-effort on Windows)
        import shutil
        shutil.move(str(tmp_path), str(file_path))
    except OSError as exc:
        # Clean up temp file on error
        if 'tmp_path' in locals() and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
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

    # Validate JSON structure
    if not isinstance(data, dict):
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})

    # Validate tool_input is a dict
    if not isinstance(tool_input, dict):
        sys.exit(0)

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
