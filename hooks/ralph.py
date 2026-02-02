#!/usr/bin/env python3
"""
Ralph Hook Wrapper - Thin wrapper that delegates to scripts/ralph.py.

This module reads stdin (hook input JSON), determines the hook mode from
sys.argv[1], and forwards to the main Ralph script for processing.

Usage:
    python3 ralph.py stop             # Stop hook (orchestrator)
    python3 ralph.py session-start    # SessionStart hook
    python3 ralph.py pre-compact      # PreCompact hook
    python3 ralph.py subagent-start   # SubagentStart hook
    python3 ralph.py subagent-stop    # SubagentStop hook
"""

import os
import subprocess
import sys
import threading
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
RALPH_SCRIPT = SCRIPTS_DIR / "ralph.py"

# ---------------------------------------------------------------------------
# Timeout guard — kill process if stdin/subprocess hangs (Windows-safe)
# ---------------------------------------------------------------------------
_TOTAL_TIMEOUT = 25  # seconds — must be less than the hook timeout in settings.json

_kill_timer = threading.Timer(_TOTAL_TIMEOUT, lambda: os._exit(0))
_kill_timer.daemon = True
_kill_timer.start()


def main() -> None:
    """Delegate to scripts/ralph.py with hook-{mode} command."""
    if len(sys.argv) < 2:
        print("Usage: ralph.py [stop|session-start|pre-compact]", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    hook_command = f"hook-{mode}"

    # Determine subprocess timeout based on mode
    sub_timeout = {
        "stop": 25,
        "session-start": 8,
        "pre-compact": 8,
        "subagent-start": 8,
        "subagent-stop": 8,
    }.get(mode, 15)

    # Read stdin for hook input (with implicit timeout from _kill_timer)
    stdin_data = sys.stdin.read()

    # Call scripts/ralph.py hook-{mode}
    try:
        result = subprocess.run(
            [sys.executable, str(RALPH_SCRIPT), hook_command],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=sub_timeout,
        )
    except subprocess.TimeoutExpired:
        sys.exit(0)  # Don't block Claude Code

    # Forward stdout/stderr
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    # Preserve exit code
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
