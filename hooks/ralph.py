#!/usr/bin/env python3
"""
Ralph Hook Wrapper - Thin wrapper that delegates to scripts/ralph.py.

This module reads stdin (hook input JSON), determines the hook mode from
sys.argv[1], and forwards to the main Ralph script for processing.

Usage:
    python3 ralph.py stop         # Stop hook (orchestrator)
    python3 ralph.py session-start # SessionStart hook
    python3 ralph.py pre-compact   # PreCompact hook
"""

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
RALPH_SCRIPT = SCRIPTS_DIR / "ralph.py"


def main() -> None:
    """Delegate to scripts/ralph.py with hook-{mode} command."""
    if len(sys.argv) < 2:
        print("Usage: ralph.py [stop|session-start|pre-compact]", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    hook_command = f"hook-{mode}"

    # Read stdin for hook input
    stdin_data = sys.stdin.read()

    # Call scripts/ralph.py hook-{mode}
    result = subprocess.run(
        ["python3", str(RALPH_SCRIPT), hook_command],
        input=stdin_data,
        capture_output=True,
        text=True,
    )

    # Forward stdout/stderr
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    # Preserve exit code
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
