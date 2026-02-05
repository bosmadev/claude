#!/usr/bin/env python3
"""
Shared Review Parsing Logic — Extract findings from review markdown files.

Used by:
  - post-review.py (PostToolUse hook for /review skill)
  - Future review processing tools

Parses structured review documents (review-agents.md, PR review comments) and
extracts findings with file locations, severity, and descriptions.

Severity mapping:
  Critical/High → TODO-P1
  Medium        → TODO-P2
  Low           → TODO-P3
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

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
    """A single review finding extracted from review markdown."""

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


# ---------------------------------------------------------------------------
# Parsing — extract findings from review markdown
# ---------------------------------------------------------------------------

# Matches file references like `file.ts:42` or `file.ts:42-50`
# Supports common web framework and language file extensions
FILE_LINE_RE = re.compile(
    r"`([^`]+?\.(?:ts|tsx|js|jsx|vue|svelte|astro|py|rs|go|java|rb|css|scss|sass|less|html|md|json|yaml|yml|toml|xml|sh|bash))"
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

    # Validate start_idx bounds
    if start_idx < 0 or start_idx >= len(lines):
        return findings, start_idx

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
    """Parse review markdown and extract all findings with file locations.

    Supports multiple review formats:
    - review-agents.md (from /review skill)
    - PR review comments (from @claude review)
    - OWASP audit reports

    Returns list of Finding objects with file paths, line numbers, severity,
    category, and descriptions.
    """
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
# Utility functions
# ---------------------------------------------------------------------------

def extract_file_references(content: str) -> list[tuple[str, Optional[int], Optional[int]]]:
    """Extract all file references from markdown content.

    Returns list of tuples: (file_path, line_start, line_end)
    Used for quick scanning without full parsing.
    """
    references = []
    for match in FILE_LINE_RE.finditer(content):
        file_path = match.group(1)
        line_start_str = match.group(2)
        line_end_str = match.group(3)

        # Validate line numbers
        line_start = None
        line_end = None

        if line_start_str:
            try:
                line_start = int(line_start_str)
                # Validate positive line numbers
                if line_start < 1:
                    continue  # Skip invalid line numbers
            except (ValueError, TypeError):
                continue

        if line_end_str:
            try:
                line_end = int(line_end_str)
                # Validate positive and ensure end >= start
                if line_end < 1 or (line_start and line_end < line_start):
                    line_end = None  # Ignore invalid end line
            except (ValueError, TypeError):
                line_end = None

        references.append((file_path, line_start, line_end))
    return references


def get_severity_stats(findings: list[Finding]) -> dict[str, int]:
    """Get count of findings by severity level."""
    stats = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    for finding in findings:
        severity = finding.severity.capitalize()
        if severity in stats:
            stats[severity] += 1
    return stats


def get_category_stats(findings: list[Finding]) -> dict[str, int]:
    """Get count of findings by category."""
    stats: dict[str, int] = {}
    for finding in findings:
        category = finding.category or "Uncategorized"
        stats[category] = stats.get(category, 0) + 1
    return stats


def format_finding_summary(finding: Finding) -> str:
    """Format a finding as a single-line summary."""
    location = f"{finding.file_path}:{finding.line_start}"
    if finding.line_end:
        location += f"-{finding.line_end}"
    return f"[{finding.severity}] {finding.category}: {finding.description} ({location})"
