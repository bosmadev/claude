#!/usr/bin/env python3
"""Build Intelligence Hook - Ralph Phase 2.1: Build Failure Detection

PostToolUse hook for Bash commands. Detects build/test/lint failures and writes
findings to .claude/ralph/build-intelligence.json.

Detected failure types:
- Build failures: non-zero exit code, compilation errors
- Test failures: test runner errors, assertion failures
- Lint failures: biome/eslint error patterns

Usage:
    python build-intelligence.py hook    # PostToolUse: Track build failures
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# =============================================================================
# Configuration
# =============================================================================

# Quick exit if not in Ralph mode
def is_ralph_mode() -> bool:
    """Check if running in Ralph subagent mode."""
    return os.environ.get("RALPH_SUBAGENT") == "1"

def get_agent_id() -> str:
    """Get agent ID from environment."""
    return (
        os.environ.get("RALPH_AGENT_ID") or
        os.environ.get("CLAUDE_CODE_AGENT_NAME") or
        "unknown"
    )

# =============================================================================
# Error Detection Patterns
# =============================================================================

BUILD_ERROR_PATTERNS = [
    r"error:",
    r"ERROR:",
    r"compilation failed",
    r"build failed",
    r"\d+ error[s]? generated",
    r"cannot find module",
    r"module not found",
    r"SyntaxError:",
    r"TypeError:",
    r"ReferenceError:",
    r"ImportError:",
    r"ModuleNotFoundError:",
]

TEST_ERROR_PATTERNS = [
    r"FAIL",
    r"FAILED",
    r"AssertionError",
    r"\d+ failed",
    r"Test failed",
    r"test failure",
    r"Error:",
    r"Exception:",
    r"Traceback",
]

LINT_ERROR_PATTERNS = [
    r"biome.*error",
    r"eslint.*error",
    r"✖",  # Common error symbol
    r"\d+ problem[s]? \(",
    r"error FS",  # Biome error codes
]

def detect_errors(output: str, stderr: str) -> list[dict]:
    """Detect error patterns in command output."""
    errors = []
    combined = f"{output}\n{stderr}"

    # Build errors
    for pattern in BUILD_ERROR_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE | re.MULTILINE):
            errors.append({
                "type": "build",
                "pattern": pattern,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            break  # Only count once per type

    # Test errors
    for pattern in TEST_ERROR_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE | re.MULTILINE):
            errors.append({
                "type": "test",
                "pattern": pattern,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            break

    # Lint errors
    for pattern in LINT_ERROR_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE | re.MULTILINE):
            errors.append({
                "type": "lint",
                "pattern": pattern,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            break

    return errors

# =============================================================================
# State Management
# =============================================================================

def get_state_file() -> Path:
    """Get path to build intelligence state file."""
    cwd = os.environ.get("CLAUDE_CODE_WORKING_DIR", os.getcwd())
    state_dir = Path(cwd) / ".claude" / "ralph"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "build-intelligence.json"

def load_state() -> dict:
    """Load build intelligence state."""
    state_file = get_state_file()
    if state_file.exists():
        try:
            return json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"agents": {}}

def save_state(state: dict) -> None:
    """Save build intelligence state."""
    state_file = get_state_file()
    try:
        state_file.write_text(json.dumps(state, indent=2))
    except OSError:
        pass

def update_agent_errors(agent_id: str, errors: list[dict]) -> None:
    """Update error count for an agent."""
    state = load_state()

    if agent_id not in state["agents"]:
        state["agents"][agent_id] = {
            "errors": [],
            "struggling": False
        }

    # Append new errors
    state["agents"][agent_id]["errors"].extend(errors)

    # Check if struggling (3+ errors)
    error_count = len(state["agents"][agent_id]["errors"])
    state["agents"][agent_id]["struggling"] = error_count >= 3

    save_state(state)

# =============================================================================
# Hook Handler
# =============================================================================

def hook_handler() -> None:
    """PostToolUse hook for Bash commands."""
    # Quick exit if not in Ralph mode
    if not is_ralph_mode():
        sys.exit(0)

    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    tool_result = hook_input.get("tool_result", {})
    exit_code = tool_result.get("exit_code", 0)

    # Quick exit on success
    if exit_code == 0:
        sys.exit(0)

    # Failure detected - check for error patterns
    stdout = tool_result.get("stdout", "")
    stderr = tool_result.get("stderr", "")

    errors = detect_errors(stdout, stderr)

    if errors:
        agent_id = get_agent_id()
        update_agent_errors(agent_id, errors)

    # Allow the tool call to proceed
    sys.exit(0)

# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> None:
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage: build-intelligence.py hook", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "hook":
        hook_handler()
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
