#!/usr/bin/env python3
"""
/sounds skill - Toggle audio feedback for Claude Code events.

Usage:
    python sounds.py on
    python sounds.py off
    python sounds.py status
"""

import sys
from pathlib import Path


def get_marker_path() -> Path:
    """Get path to sounds-enabled marker file."""
    return Path.home() / ".claude" / "sounds-enabled"


def enable_sounds():
    """Enable audio feedback."""
    marker = get_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()
    print("Audio feedback enabled for this session")
    print("You'll hear sounds for tool calls, commits, errors, and notifications")


def disable_sounds():
    """Disable audio feedback."""
    marker = get_marker_path()
    if marker.exists():
        marker.unlink()
    print("Audio feedback disabled")


def show_status():
    """Show current audio state."""
    marker = get_marker_path()
    if marker.exists():
        print("Audio feedback: ENABLED")
        print("\nSupported events:")
        print("  - Session start/stop")
        print("  - Tool success/failure")
        print("  - Git commits")
        print("  - Permission prompts")
    else:
        print("Audio feedback: DISABLED")
        print("\nRun '/sounds on' to enable")


def main():
    if len(sys.argv) < 2:
        print("Usage: /sounds [on|off|status]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "on":
        enable_sounds()
    elif command == "off":
        disable_sounds()
    elif command == "status":
        show_status()
    else:
        print(f"Unknown command: {command}")
        print("Usage: /sounds [on|off|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
