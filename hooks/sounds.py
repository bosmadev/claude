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

Uses in-memory WAV generation played through system audio (speakers/headphones).
winsound.Beep() is NOT used — it targets the PC speaker which is disabled/muted
on most modern PCs and doesn't work in VSCode terminals.
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
    """Generate a mono 16-bit PCM WAV tone in memory.

    Args:
        frequency: Tone frequency in Hz (200-2000 recommended)
        duration_ms: Duration in milliseconds
        volume: Volume 0.0-1.0 (0.3 default — not too loud)
    """
    sample_rate = 22050  # CD-quality not needed for beeps
    num_samples = int(sample_rate * duration_ms / 1000)
    samples = bytearray()
    for i in range(num_samples):
        t = i / sample_rate
        # Apply fade-in/fade-out envelope (first/last 5ms) to avoid clicks
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
    # WAV header: RIFF + fmt + data chunks
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(data), b"WAVE",
        b"fmt ", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16,
        b"data", len(data),
    )
    return header + data


def play_tone(frequency: int, duration_ms: int, volume: float = 0.3):
    """Play a tone through system audio (speakers/headphones)."""
    if not WINSOUND_AVAILABLE:
        return
    try:
        wav_data = _generate_wav(frequency, duration_ms, volume)
        winsound.PlaySound(wav_data, winsound.SND_MEMORY)
    except Exception:
        pass  # Silently fail if audio unavailable


def play_chord(tones: list[tuple[int, int]]):
    """Play a sequence of tones (frequency, duration_ms)."""
    for freq, dur in tones:
        play_tone(freq, dur)


def handle_session_start():
    """Rising two-note chord: session starting."""
    if should_play_sound():
        play_chord([(523, 120), (659, 180)])  # C5 → E5


def handle_session_stop():
    """Falling tone: session ending."""
    if should_play_sound():
        play_chord([(659, 120), (440, 250)])  # E5 → A4


def handle_post_tool():
    """Different sounds for success/error/commit."""
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
            # Triumphant three-note: C5 → E5 → G5
            play_chord([(523, 100), (659, 100), (784, 200)])
        elif is_error:
            # Low descending: error
            play_chord([(349, 200), (262, 300)])  # F4 → C4
        else:
            # Quick single tick: tool success (subtle, not annoying)
            play_tone(880, 60, volume=0.15)  # A5, very short + quiet

    except Exception:
        pass


def handle_notification():
    """Double-tap attention sound for permission prompts."""
    if should_play_sound():
        play_chord([(698, 100), (698, 100)])  # F5 × 2


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
