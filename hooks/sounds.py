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

Hybrid approach: Voice WAVs (from shanraisshan/claude-code-voice-hooks)
for most events, generated tones for high-frequency events.
"""

import json
import math
import os
import struct
import sys
from pathlib import Path

try:
    import winsound
    WINSOUND_AVAILABLE = True
except ImportError:
    WINSOUND_AVAILABLE = False

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


def _generate_wav(frequency: int, duration_ms: int, volume: float = 0.3) -> bytes:
    """Generate a mono 16-bit PCM WAV tone in memory."""
    sample_rate = 22050
    num_samples = int(sample_rate * duration_ms / 1000)
    samples = bytearray()
    for i in range(num_samples):
        t = i / sample_rate
        fade_samples = int(sample_rate * 0.005)
        if i < fade_samples:
            envelope = i / fade_samples
        elif i > num_samples - fade_samples:
            envelope = (num_samples - i) / fade_samples
        else:
            envelope = 1.0
        value = int(volume * envelope * 32767 * math.sin(2 * math.pi * frequency * t))
        samples.extend(struct.pack("<h", max(-32768, min(32767, value))))

    data = bytes(samples)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(data), b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", len(data),
    )
    return header + data


def play_wav(name: str):
    """Play a WAV file from the sounds directory."""
    if not WINSOUND_AVAILABLE:
        return
    try:
        wav_path = SOUNDS_DIR / f"{name}.wav"
        if wav_path.exists():
            winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
    except Exception:
        pass


def play_tone(frequency: int, duration_ms: int, volume: float = 0.3):
    """Play a generated tone through system audio."""
    if not WINSOUND_AVAILABLE:
        return
    try:
        wav_data = _generate_wav(frequency, duration_ms, volume)
        winsound.PlaySound(wav_data, winsound.SND_MEMORY)
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
    """Voice: user pressed Enter."""
    if should_play_sound():
        play_wav("userpromptsubmit")


def handle_notification():
    """Voice: notification/attention."""
    if should_play_sound():
        play_wav("notification")


def handle_permission_request():
    """Voice: permission needed."""
    if should_play_sound():
        play_wav("permissionrequest")


def handle_subagent_start():
    """Voice: subagent spawned."""
    if should_play_sound():
        play_wav("subagentstart")


def handle_subagent_stop():
    """Voice: subagent finished."""
    if should_play_sound():
        play_wav("subagentstop")


def handle_task_completed():
    """Voice: task completed."""
    if should_play_sound():
        play_wav("taskcompleted")


def handle_teammate_idle():
    """Voice: teammate went idle."""
    if should_play_sound():
        play_wav("teammateidle")


def handle_post_tool():
    """Hybrid: voice WAVs for error/commit, generated tone for success."""
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
        else:
            # Quick generated tone for success (voice WAV too verbose for every tool)
            play_tone(880, 250, volume=0.4)

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
