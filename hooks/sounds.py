#!/usr/bin/env python3
"""
Audio feedback hook handler for Claude Code events.

Usage:
    python sounds.py <event>

Events: session-start, session-stop, post-tool, notification, setup,
        pre-compact, user-prompt-submit, subagent-start, subagent-stop,
        stop, permission-request, task-completed, teammate-idle

Plays audio only if:
1. ~/.claude/sounds-enabled marker file exists
2. NOT running as subagent (no CLAUDE_CODE_TASK_LIST_ID or CLAUDE_CODE_SUBAGENT)

Voice WAVs (from shanraisshan/claude-code-voice-hooks) for key events.
No sound on successful tool completion (too noisy).
"""

import json
import os
import sys
from pathlib import Path

# Add parent directory to path so hooks.compat import works when run as script
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from hooks.compat import play_sound as _play_sound

SOUNDS_DIR = Path(__file__).parent / "sounds"


def should_play_sound() -> bool:
    """Check if audio feedback should play."""
    marker = Path.home() / ".claude" / "sounds-enabled"
    if not marker.exists():
        return False
    if os.environ.get("CLAUDE_CODE_TASK_LIST_ID"):
        return False
    if os.environ.get("CLAUDE_CODE_SUBAGENT"):
        return False
    return True


def play_wav(name: str):
    """Play a WAV file from the sounds directory."""
    try:
        wav_path = SOUNDS_DIR / f"{name}.wav"
        _play_sound(wav_path)
    except Exception:
        pass


# --- Event Handlers ---

def handle_session_start():
    """Voice: session starting."""
    if should_play_sound():
        play_wav("sessionstart")


def handle_session_stop():
    """Voice: session ending."""
    if should_play_sound():
        play_wav("sessionend")


def handle_stop():
    """Voice: process stopping."""
    if should_play_sound():
        play_wav("stop")


def handle_setup():
    """Voice: initial setup."""
    if should_play_sound():
        play_wav("setup")


def handle_pre_compact():
    """Voice: context compression."""
    if should_play_sound():
        play_wav("precompact")


def handle_user_prompt_submit():
    """Voice: user pressed Enter. (disabled — redundant feedback)"""
    pass


def handle_notification():
    """Voice: permissionrequest.wav for permission prompts only. Other notifications silent."""
    if not should_play_sound():
        return
    try:
        stdin_data = sys.stdin.read()
        if stdin_data.strip():
            import json as _json
            data = _json.loads(stdin_data)
            if data.get("notification_type") == "permission_prompt":
                play_wav("permissionrequest")
    except Exception:
        pass


def handle_permission_request():
    """Voice: permission needed."""
    if should_play_sound():
        play_wav("permissionrequest")


def handle_subagent_start():
    """Voice: subagent spawned. (disabled — too frequent during team ops)"""
    pass


def handle_subagent_stop():
    """Voice: subagent finished. (disabled — too frequent during team ops)"""
    pass


def handle_task_completed():
    """Voice: task completed."""
    if should_play_sound():
        play_wav("taskcompleted")


def handle_teammate_idle():
    """Voice: teammate went idle."""
    if should_play_sound():
        play_wav("teammateidle")


def handle_post_tool():
    """Voice WAVs for error/commit only. No sound on success."""
    if not should_play_sound():
        return

    try:
        stdin_data = sys.stdin.read()
        if not stdin_data.strip():
            return

        hook_data = json.loads(stdin_data)
        result = hook_data.get("result", {})

        is_error = False
        if isinstance(result, dict):
            is_error = result.get("error") is not None

        tool_name = hook_data.get("tool", {}).get("name", "")
        params = hook_data.get("tool", {}).get("params", {})
        is_git_commit = (
            tool_name == "Bash"
            and isinstance(params, dict)
            and "git commit" in params.get("command", "")
        )

        if is_git_commit:
            play_wav("pretooluse-git-committing")
        elif is_error:
            play_wav("posttoolusefailure")
        # No sound on success — too noisy when tools fire rapidly

    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        sys.exit(0)

    event = sys.argv[1]
    handlers = {
        "session-start": handle_session_start,
        "session-stop": handle_session_stop,
        "stop": handle_stop,
        "setup": handle_setup,
        "pre-compact": handle_pre_compact,
        "user-prompt-submit": handle_user_prompt_submit,
        "post-tool": handle_post_tool,
        "notification": handle_notification,
        "permission-request": handle_permission_request,
        "subagent-start": handle_subagent_start,
        "subagent-stop": handle_subagent_stop,
        "task-completed": handle_task_completed,
        "teammate-idle": handle_teammate_idle,
    }
    handler = handlers.get(event)
    if handler:
        handler()


if __name__ == "__main__":
    main()
