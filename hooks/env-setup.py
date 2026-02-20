#!/usr/bin/env python3
"""
Platform Env Setup Hook - SessionStart

Warns on non-Windows platforms when CC env vars point to Windows paths.
CC's env block does NOT expand shell variables — values are passed literally.

On Linux/Mac, set these in your shell profile before launching CC:
  export CLAUDE_CODE_TMPDIR="$HOME/.local/share/claude-tmp"
  export PYTHONPYCACHEPREFIX="$HOME/.claude/.cache/pycache"
  export CLAUDE_SOURCE_DIR="$HOME/source"

This hook detects the mismatch and logs a warning to debug/env-setup.log.
"""

import json
import os
import sys
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from hooks.compat import IS_WINDOWS, setup_stdin_timeout, cancel_stdin_timeout

setup_stdin_timeout(5, debug_label="env-setup.py stdin read")

try:
    _input = sys.stdin.read()
    cancel_stdin_timeout()
    json.loads(_input)  # Validate JSON but we don't need the content
except (json.JSONDecodeError, Exception):
    sys.exit(0)

# On Windows, env block values are correct — nothing to do
if IS_WINDOWS:
    sys.exit(0)

# On Linux/Mac: check if vars look like Windows paths
warnings = []

tmpdir = os.environ.get("CLAUDE_CODE_TMPDIR", "")
if tmpdir and (tmpdir.startswith("C:/") or tmpdir.startswith("C:\\")):
    linux_default = str(Path.home() / ".local" / "share" / "claude-tmp")
    os.makedirs(linux_default, exist_ok=True)
    warnings.append(
        f"CLAUDE_CODE_TMPDIR={tmpdir!r} looks like a Windows path. "
        f"On Linux, set: export CLAUDE_CODE_TMPDIR={linux_default!r}"
    )
    # Override for this session by creating the expected dir
    os.environ["CLAUDE_CODE_TMPDIR"] = linux_default

pycache = os.environ.get("PYTHONPYCACHEPREFIX", "")
if pycache and (pycache.startswith("C:/") or pycache.startswith("C:\\")):
    linux_default = str(Path.home() / ".claude" / ".cache" / "pycache")
    warnings.append(
        f"PYTHONPYCACHEPREFIX={pycache!r} looks like a Windows path. "
        f"On Linux, set: export PYTHONPYCACHEPREFIX={linux_default!r}"
    )
    os.environ["PYTHONPYCACHEPREFIX"] = linux_default

if warnings:
    log_dir = Path.home() / ".claude" / "debug"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "env-setup.log"
    from datetime import datetime
    with open(log_file, "a", encoding="utf-8") as f:
        for w in warnings:
            f.write(f"{datetime.now().isoformat()} - {w}\n")

    # Surface the warning in CC output
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "Linux detected: CC env vars point to Windows paths. "
                "Set CLAUDE_CODE_TMPDIR and PYTHONPYCACHEPREFIX in your shell profile. "
                f"See ~/.claude/debug/env-setup.log for details."
            ),
        }
    }
    print(json.dumps(output))

sys.exit(0)
