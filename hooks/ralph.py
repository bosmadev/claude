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

# Add parent directory to sys.path for hooks imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from hooks.compat import setup_stdin_timeout, cancel_stdin_timeout

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
RALPH_SCRIPT = SCRIPTS_DIR / "ralph.py"


def main() -> None:
    """Delegate to scripts/ralph.py with hook-{mode} command."""
    setup_stdin_timeout(25, debug_label="ralph.py")

    if len(sys.argv) < 2:
        sys.exit(0)

    mode = sys.argv[1]

    # Validate mode to prevent command injection
    valid_modes = {"stop", "session-start", "pre-compact", "subagent-start", "subagent-stop"}
    if mode not in valid_modes:
        sys.exit(0)

    hook_command = f"hook-{mode}"

    # Determine subprocess timeout based on mode
    sub_timeout = {
        "stop": 25,
        "session-start": 8,
        "pre-compact": 8,
        "subagent-start": 8,
        "subagent-stop": 8,
    }.get(mode, 15)

    # Read stdin with timeout protection using threading
    stdin_data = None

    def read_stdin():
        nonlocal stdin_data
        try:
            stdin_data = sys.stdin.buffer.read().decode('utf-8', errors='replace')
        except Exception:
            stdin_data = ""

    reader = threading.Thread(target=read_stdin, daemon=True)
    reader.start()
    reader.join(timeout=sub_timeout - 2)  # Leave 2s for subprocess

    if stdin_data is None:
        # Stdin read timed out
        sys.exit(0)

    cancel_stdin_timeout()

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
        # Log timeout for debugging
        try:
            debug_log = Path.home() / ".claude" / "debug" / "ralph-subprocess-timeout.log"
            debug_log.parent.mkdir(parents=True, exist_ok=True)
            with open(debug_log, "a") as f:
                f.write(f"[{mode}] Subprocess timeout after {sub_timeout}s\n")
        except Exception:
            pass
        sys.exit(0)  # Don't block Claude Code
    except (FileNotFoundError, PermissionError) as e:
        # Log script execution errors
        # Can't find/run script — exit gracefully
        sys.exit(0)

    # Forward stdout/stderr
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    # Preserve exit code
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
