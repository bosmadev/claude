#!/usr/bin/env python3
"""
Audio feedback hook handler for Claude Code events.

Usage:
    python sounds.py session-start
    python sounds.py session-stop
    python sounds.py post-tool
    python sounds.py notification

Plays audio only if:
1. ~/.claude/sounds-enabled marker file exists
2. NOT running as subagent (no CLAUDE_CODE_TASK_LIST_ID or CLAUDE_CODE_SUBAGENT)
"""

import json
import os
import sys
from pathlib import Path

try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    WINSOUND_AVAILABLE = False


def should_play_sound() -> bool:
    """Check if audio feedback should play."""
    # Check marker file
    marker = Path.home() / ".claude" / "sounds-enabled"
    if not marker.exists():
        return False

    # Exclude subagents
    if os.environ.get("CLAUDE_CODE_TASK_LIST_ID"):
        return False
    if os.environ.get("CLAUDE_CODE_SUBAGENT"):
        return False

    return True


def play_beep(frequency: int, duration: int, repeat: int = 1):
    """Play a beep sound on Windows."""
    if not WINSOUND_AVAILABLE:
        return

    for _ in range(repeat):
        try:
            winsound.Beep(frequency, duration)
        except Exception:
            pass  # Silently fail if sound can't play


def handle_session_start():
    """Play sound for session start."""
    if should_play_sound():
        play_beep(800, 200)


def handle_session_stop():
    """Play sound for session stop."""
    if should_play_sound():
        play_beep(500, 400)


def handle_post_tool():
    """Play sound for tool success/failure."""
    if not should_play_sound():
        return

    # Read stdin for tool result
    try:
        stdin_data = sys.stdin.read()
        if not stdin_data.strip():
            return

        hook_data = json.loads(stdin_data)
        result = hook_data.get("result", {})

        # Check for errors
        is_error = False
        if isinstance(result, dict):
            is_error = result.get("error") is not None

        # Check for git commit
        tool_name = hook_data.get("tool", {}).get("name", "")
        params = hook_data.get("tool", {}).get("params", {})
        is_git_commit = (
            tool_name == "Bash" and
            isinstance(params, dict) and
            "git commit" in params.get("command", "")
        )

        if is_git_commit:
            play_beep(1200, 150)
        elif is_error:
            play_beep(400, 300)
        else:
            play_beep(1000, 100)

    except Exception:
        pass  # Silently fail on parse errors


def handle_notification():
    """Play sound for notification (permission prompt)."""
    if should_play_sound():
        play_beep(600, 150, repeat=2)


def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    event = sys.argv[1]

    handlers = {
        "session-start": handle_session_start,
        "session-stop": handle_session_stop,
        "post-tool": handle_post_tool,
        "notification": handle_notification,
    }

    handler = handlers.get(event)
    if handler:
        handler()


if __name__ == "__main__":
    main()
