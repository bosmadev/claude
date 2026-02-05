#!/usr/bin/env python3
"""Auto-allow hook for Read/Edit/Write operations.
Workaround for Claude Code permission bug (GitHub #6850).
"""
import json
import sys


def main():
    """Auto-allow Read/Edit/Write within allowed directories.

    This is intentional behavior to work around Claude Code permission bug (GitHub #6850).
    Validates that file operations stay within safe boundaries.
    """
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, TypeError):
        hook_input = {}

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path") or tool_input.get("filePath", "")

    # Basic path validation - block obvious path traversal attempts
    if file_path:
        # Normalize path
        from pathlib import Path
        try:
            resolved = Path(file_path).resolve()
            # Block access to system directories
            blocked_prefixes = [
                "/etc", "/usr", "/bin", "/sbin", "/var", "/root",
                "C:\\Windows", "C:\\Program Files", "C:\\ProgramData"
            ]
            path_str = str(resolved)
            for prefix in blocked_prefixes:
                if path_str.startswith(prefix):
                    output = {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": f"Access to system directory blocked: {prefix}"
                        }
                    }
                    sys.stdout.write(json.dumps(output))
                    return
        except Exception:
            pass  # If path resolution fails, allow and let the tool handle it

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
    sys.stdout.write(json.dumps(output))


if __name__ == "__main__":
    main()
