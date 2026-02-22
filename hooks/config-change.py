#!/usr/bin/env python3
"""
ConfigChange Hook - Async audit logger + smart permission suggester.

Fires when settings.json, settings.local.json, or skills/** change mid-session.

Actions:
1. Audit log to ~/.claude/debug/config-changes.log
2. Diff old vs new permissions
3. Detect overly-specific entries and suggest generalizations
4. Suggest settings.json (permanent) vs settings.local.json (local-only)

Registered as: ConfigChange hook (async) in settings.json

Stdin schema (ConfigChange event):
  {
    "event": "config_changed",
    "config_type": "user_settings" | "local_settings" | "skill",
    "file_path": "/path/to/changed/file",
    "old_content": "...",  # may be null for new files
    "new_content": "..."
  }
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add parent dir for hooks imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hooks.compat import setup_stdin_timeout, get_claude_home

setup_stdin_timeout(10)

CLAUDE_HOME = get_claude_home()
LOG_DIR = CLAUDE_HOME / "debug"
LOG_FILE = LOG_DIR / "config-changes.log"

# ─── Generalization Rules ────────────────────────────────────────────────────
# Each rule: (pattern_to_detect, suggested_generalization, description)
GENERALIZATION_RULES = [
    # python ~/.claude/scripts/statusline.py | head -30
    (
        r"python3?\s+[^\s]*\.claude[/\\]scripts[/\\](\w+\.py)\s+\S.*",
        r"python ~/.claude/scripts/*.py *",
        "Specific script + args → wildcard script pattern",
    ),
    # python ~/.claude/hooks/utils.py auto-rename abc-123 slug
    (
        r"python3?\s+[^\s]*\.claude[/\\]hooks[/\\](\w+\.py)\s+\S.*",
        r"python ~/.claude/hooks/*.py *",
        "Specific hook + args → wildcard hook pattern",
    ),
    # python /home/dennis/.claude/scripts/guards.py ...  (absolute path)
    (
        r"python3?\s+/[^\s]+\.claude[/\\]scripts[/\\](\w+\.py)\s*.*",
        r"python ~/.claude/scripts/*.py *",
        "Absolute path script → tilde wildcard pattern",
    ),
    # Pipe chains: command | head -30 or | tail -10
    (
        r".*\|\s*(?:head|tail)\s+-\d+.*",
        None,  # No single suggestion; flag as overly specific
        "Pipe chain with head/tail — consider removing output limit",
    ),
    # Full absolute paths (not ~/.claude)
    (
        r"python3?\s+/(?:home|Users)/[^\s]+/\.claude/[^\s]+",
        r"python ~/.claude/... (use ~ not absolute path)",
        "Absolute user path → tilde-relative path",
    ),
    # node absolute paths
    (
        r"node\s+/(?:home|Users)/[^\s]+/\.claude[/\\][^\s]+",
        r"node ~/.claude/... (use ~ not absolute path)",
        "Absolute node path → tilde-relative path",
    ),
]

# Indicators of an overly-specific entry
SPECIFIC_INDICATORS = [
    r"[/\\]home[/\\]\w+[/\\]",      # /home/username/
    r"[/\\]Users[/\\]\w+[/\\]",     # /Users/username/
    r"C:[/\\]Users[/\\]\w+",        # C:\Users\username
    r"\|\s*head\s+-\d+",            # | head -N
    r"\|\s*tail\s+-\d+",            # | tail -N
    r"python3\s+",                   # python3 (should be python)
    r"'[^']{20,}'",                  # Long quoted string (specific args)
    r'"[^"]{20,}"',                  # Long double-quoted string
]


# ─── Audit Logger ────────────────────────────────────────────────────────────

def log_change(config_type: str, file_path: str, summary: str) -> None:
    """Append a structured entry to the config-changes audit log."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = f"[{ts}] {config_type} | {file_path}\n  {summary}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except OSError:
        pass  # Async hook — never block Claude


# ─── Permission Diff ─────────────────────────────────────────────────────────

def extract_permissions(content_str: str | None) -> list[str]:
    """Parse allow list from settings JSON string. Returns [] on error."""
    if not content_str:
        return []
    try:
        data = json.loads(content_str)
        return data.get("permissions", {}).get("allow", [])
    except (json.JSONDecodeError, AttributeError):
        return []


def diff_permissions(old_perms: list[str], new_perms: list[str]) -> list[str]:
    """Return newly added permission entries (in new but not old)."""
    old_set = set(old_perms)
    return [p for p in new_perms if p not in old_set]


# ─── Specificity Detection ────────────────────────────────────────────────────

def is_overly_specific(entry: str) -> list[str]:
    """Return list of matched specificity indicators for an entry."""
    matched = []
    for pattern in SPECIFIC_INDICATORS:
        if re.search(pattern, entry, re.IGNORECASE):
            matched.append(pattern)
    return matched


def suggest_generalization(entry: str) -> tuple[str | None, str | None]:
    """
    Return (suggested_replacement, description) for an overly specific entry.
    Returns (None, None) if no rule matches.
    """
    for pattern, suggestion, description in GENERALIZATION_RULES:
        if re.search(pattern, entry, re.IGNORECASE):
            return suggestion, description
    return None, None


# ─── Output (TTY suggestion) ─────────────────────────────────────────────────

def build_suggestion_output(
    added: list[str],
    config_type: str,
) -> str | None:
    """
    Build human-readable suggestion text for specific permission entries.
    Returns None if no suggestions needed.
    """
    lines = []
    for entry in added:
        indicators = is_overly_specific(entry)
        if not indicators:
            continue

        suggestion, desc = suggest_generalization(entry)

        lines.append(f"\n\u26a0\ufe0f  Overly-specific permission detected:")
        lines.append(f"   Entry:  {entry}")
        if desc:
            lines.append(f"   Reason: {desc}")
        if suggestion:
            lines.append(f"   Suggest: {suggestion}")

        # Recommend permanent vs local
        if config_type == "local_settings":
            lines.append(
                "   Scope: Currently in settings.local.json (local only).\n"
                "          If you want this on all machines, add to settings.json instead."
            )
        else:
            lines.append(
                "   Scope: In settings.json (permanent, all machines).\n"
                "          For machine-specific rules, use settings.local.json instead."
            )

    return "\n".join(lines) if lines else None


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit(0)

    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    config_type = event.get("config_type", "unknown")
    file_path = event.get("file_path", "unknown")
    old_content = event.get("old_content")
    new_content = event.get("new_content", "")

    # Summarize for audit log
    change_summary = f"config_type={config_type}"
    if new_content and old_content:
        change_summary += " (modified)"
    elif not old_content:
        change_summary += " (created)"
    else:
        change_summary += " (deleted)"

    log_change(config_type, file_path, change_summary)

    # Only analyze permission changes for settings files
    if config_type not in ("user_settings", "local_settings"):
        sys.exit(0)

    old_perms = extract_permissions(old_content)
    new_perms = extract_permissions(new_content)
    added = diff_permissions(old_perms, new_perms)

    if not added:
        sys.exit(0)

    # Log added entries
    log_change(
        config_type,
        file_path,
        f"New permissions ({len(added)}): " + " | ".join(added[:5])
        + ("..." if len(added) > 5 else ""),
    )

    suggestion_text = build_suggestion_output(added, config_type)
    if suggestion_text:
        # Output via hookSpecificOutput so CC shows it in TTY
        output = {
            "hookSpecificOutput": {
                "hookEventName": "ConfigChange",
                "additionalContext": suggestion_text,
            }
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
