#!/usr/bin/env python3
"""
JSONL Surrogate Sanitizer

Scans JSONL session files for invalid Unicode surrogates and cleans them.
Prevents API Error 400 "invalid high surrogate" issues.

Usage:
    python scripts/fix-surrogates.py <path-to-jsonl>
    python scripts/fix-surrogates.py --all
    python scripts/fix-surrogates.py --all --dry-run
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path


def detect_surrogates(text: str) -> bool:
    """Check if text contains unpaired surrogates (U+D800-U+DFFF)."""
    if not isinstance(text, str):
        return False
    # Check for unpaired surrogates in the string
    return bool(re.search(r'[\uD800-\uDFFF]', text))


def detect_escaped_surrogates(text: str) -> bool:
    """Check if text contains escaped surrogate sequences like \\uD800."""
    if not isinstance(text, str):
        return False
    # Pattern matches \uD800 through \uDFFF (surrogate range)
    return bool(re.search(r'\\u[dD][89abAB][0-9a-fA-F]{2}', text))


def clean_surrogates(text: str) -> str:
    """Replace unpaired surrogates with replacement character U+FFFD."""
    if not isinstance(text, str):
        return text
    # Replace unpaired surrogates with replacement character
    cleaned = re.sub(r'[\uD800-\uDFFF]', '\uFFFD', text)
    return cleaned


def clean_escaped_surrogates(text: str) -> str:
    """Remove or replace escaped surrogate sequences."""
    if not isinstance(text, str):
        return text
    # Replace escaped surrogates with replacement character
    cleaned = re.sub(r'\\u[dD][89abAB][0-9a-fA-F]{2}', r'\\uFFFD', text)
    return cleaned


def clean_json_recursive(obj):
    """Recursively clean surrogates from JSON object."""
    if isinstance(obj, dict):
        return {k: clean_json_recursive(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_json_recursive(item) for item in obj]
    elif isinstance(obj, str):
        # Clean both actual surrogates and escaped sequences
        cleaned = clean_surrogates(obj)
        cleaned = clean_escaped_surrogates(cleaned)
        return cleaned
    return obj


def process_jsonl_file(file_path: Path, dry_run: bool = False) -> dict:
    """
    Process a JSONL file and clean surrogates.

    Returns:
        dict with keys: scanned (int), issues_found (int), fixed (bool)
    """
    result = {
        "scanned": 0,
        "issues_found": 0,
        "fixed": False
    }

    if not file_path.exists():
        print(f"File not found: {file_path}")
        return result

    lines = []
    has_issues = False

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for line_num, line in enumerate(f, 1):
                result["scanned"] += 1
                line = line.rstrip('\n')

                if not line.strip():
                    lines.append(line)
                    continue

                try:
                    # Parse JSON
                    data = json.loads(line)

                    # Check for surrogates
                    line_str = json.dumps(data, ensure_ascii=False)
                    if detect_surrogates(line_str) or detect_escaped_surrogates(line):
                        has_issues = True
                        result["issues_found"] += 1

                        # Clean the data
                        cleaned_data = clean_json_recursive(data)
                        cleaned_line = json.dumps(cleaned_data, ensure_ascii=False)
                        lines.append(cleaned_line)
                    else:
                        lines.append(line)

                except json.JSONDecodeError as e:
                    print(f"  Line {line_num}: JSON decode error - {e}")
                    # Keep original line if JSON is malformed
                    lines.append(line)

    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return result

    # Write back if issues found and not dry run
    if has_issues and not dry_run:
        # Create backup
        backup_path = file_path.with_suffix(file_path.suffix + '.bak')
        try:
            shutil.copy2(file_path, backup_path)

            # Write cleaned content
            with open(file_path, 'w', encoding='utf-8') as f:
                for line in lines:
                    f.write(line + '\n')

            result["fixed"] = True

        except Exception as e:
            print(f"Error writing file {file_path}: {e}")
            # Restore from backup if write failed
            if backup_path.exists():
                shutil.copy2(backup_path, file_path)

    return result


def find_all_jsonl_files() -> list[Path]:
    """Find all JSONL files in the sessions directory."""
    claude_home = Path.home() / '.claude'
    sessions_dir = claude_home / 'sessions'

    if not sessions_dir.exists():
        return []

    # Find all .jsonl files recursively
    return sorted(sessions_dir.rglob('*.jsonl'))


def main():
    parser = argparse.ArgumentParser(
        description='Scan and clean invalid Unicode surrogates from JSONL session files'
    )
    parser.add_argument(
        'file',
        nargs='?',
        help='Path to JSONL file to process'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='Process all JSONL files in ~/.claude/sessions/'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Report issues without fixing'
    )

    args = parser.parse_args()

    if not args.file and not args.all:
        parser.error('Either provide a file path or use --all')

    # Determine files to process
    if args.all:
        files = find_all_jsonl_files()
        if not files:
            print("No JSONL files found in ~/.claude/sessions/")
            return 0
        print(f"Found {len(files)} JSONL files to scan")
    else:
        files = [Path(args.file)]

    # Process files
    total_scanned = 0
    total_issues = 0
    total_fixed = 0

    for file_path in files:
        result = process_jsonl_file(file_path, dry_run=args.dry_run)
        total_scanned += result["scanned"]
        total_issues += result["issues_found"]

        if result["issues_found"] > 0:
            status = "would fix" if args.dry_run else ("fixed" if result["fixed"] else "error")
            print(f"  {file_path.name}: {result['issues_found']} issues found, {status}")
            if result["fixed"]:
                total_fixed += 1

    # Summary
    print("\n" + "="*60)
    print(f"Files scanned: {len(files)}")
    print(f"Lines scanned: {total_scanned}")
    print(f"Issues found: {total_issues}")
    if not args.dry_run:
        print(f"Files fixed: {total_fixed}")
    print("="*60)

    if args.dry_run and total_issues > 0:
        print("\nRun without --dry-run to fix issues")

    return 0


if __name__ == '__main__':
    sys.exit(main())
