#!/usr/bin/env python3
"""Auto-allow hook for Read/Edit/Write operations.
Workaround for Claude Code permission bug (GitHub #6850).
"""
import json
import sys


def main():
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
    sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    main()
