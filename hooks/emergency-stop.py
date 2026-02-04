#!/usr/bin/env python3
"""
Layered Defense - Layer 5: Emergency Stop

Circuit breaker that monitors security events and triggers emergency
shutdown if threat threshold is exceeded.

Features:
- Tracks security blocks per minute
- Auto-shutdown on 5+ blocks in 1 minute
- Manual kill switch via /security kill
- State persistence across sessions

Integration: PostToolUse hook for monitoring
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# =============================================================================
# Configuration
# =============================================================================

STATE_FILE = Path.home() / ".claude" / "security" / "emergency-state.json"
BLOCK_THRESHOLD = 5  # Blocks per minute to trigger shutdown
TIME_WINDOW = 60  # seconds


# =============================================================================
# State Management
# =============================================================================

def load_state() -> Dict:
    """Load emergency stop state."""
    if not STATE_FILE.exists():
        return {
            "blocks": [],  # List of (timestamp, reason) tuples
            "shutdowns": [],  # List of shutdown events
            "manual_kill": False
        }

    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "blocks": [],
            "shutdowns": [],
            "manual_kill": False
        }


def save_state(state: Dict) -> None:
    """Save emergency stop state."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def record_block(reason: str) -> None:
    """Record a security block event."""
    state = load_state()
    now = time.time()

    # Add new block
    state["blocks"].append({"timestamp": now, "reason": reason})

    # Prune blocks older than time window
    cutoff = now - TIME_WINDOW
    state["blocks"] = [b for b in state["blocks"] if b["timestamp"] > cutoff]

    save_state(state)


def check_threshold() -> Optional[str]:
    """
    Check if block threshold exceeded.

    Returns:
        Optional[str]: Shutdown reason if threshold exceeded
    """
    state = load_state()
    now = time.time()
    cutoff = now - TIME_WINDOW

    # Count recent blocks
    recent_blocks = [b for b in state["blocks"] if b["timestamp"] > cutoff]

    if len(recent_blocks) >= BLOCK_THRESHOLD:
        reasons = [b["reason"] for b in recent_blocks[-5:]]
        return f"""
🚨 EMERGENCY STOP - Security Threshold Exceeded

Detected {len(recent_blocks)} security blocks in the last {TIME_WINDOW}s.

Recent blocks:
{chr(10).join(f"  - {r}" for r in reasons)}

System is shutting down to prevent potential security breach.
Contact user before resuming operations.
        """

    # Check manual kill switch
    if state.get("manual_kill"):
        return """
🚨 EMERGENCY STOP - Manual Kill Switch Activated

User has manually triggered emergency shutdown.
All Claude operations have been stopped.
        """

    return None


def trigger_shutdown(reason: str) -> None:
    """Record shutdown event."""
    state = load_state()
    state["shutdowns"].append({
        "timestamp": time.time(),
        "datetime": datetime.now().isoformat(),
        "reason": reason
    })
    save_state(state)


def clear_state() -> None:
    """Clear emergency stop state (user action)."""
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def activate_kill_switch() -> None:
    """Activate manual kill switch."""
    state = load_state()
    state["manual_kill"] = True
    save_state(state)


# =============================================================================
# Hook Handler
# =============================================================================

def pretool_emergency_check(tool_input: Dict) -> Optional[Dict]:
    """
    PreToolUse hook - check if emergency stop is active.

    Returns:
        Optional[Dict]: Block response if emergency stop active
    """
    shutdown_reason = check_threshold()

    if shutdown_reason:
        trigger_shutdown(shutdown_reason)
        return {
            "type": "block",
            "reason": shutdown_reason
        }

    return None


def posttool_monitor(tool_name: str, tool_output: Dict) -> None:
    """
    PostToolUse hook - monitor for security events.

    Records blocks from security-gate.py for threshold tracking.
    """
    # Check if security-gate blocked this operation
    if isinstance(tool_output, dict) and tool_output.get("blocked"):
        reason = tool_output.get("reason", "unknown")
        record_block(f"security-gate: {reason}")


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """Hook entry point."""
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing hook arguments"}), file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    # Handle manual commands
    if command == "status":
        state = load_state()
        now = time.time()
        cutoff = now - TIME_WINDOW
        recent_blocks = [b for b in state["blocks"] if b["timestamp"] > cutoff]

        print(f"Emergency Stop Status:")
        print(f"  Recent blocks: {len(recent_blocks)}/{BLOCK_THRESHOLD} (last {TIME_WINDOW}s)")
        print(f"  Manual kill: {state.get('manual_kill', False)}")
        print(f"  Total shutdowns: {len(state.get('shutdowns', []))}")
        sys.exit(0)

    elif command == "kill":
        activate_kill_switch()
        print("🚨 Emergency kill switch activated. All Claude operations will be blocked.")
        sys.exit(0)

    elif command == "clear":
        clear_state()
        print("✅ Emergency stop state cleared.")
        sys.exit(0)

    # Hook mode
    if command == "pretool":
        try:
            payload = json.loads(sys.stdin.read())
            tool_input = payload.get("tool_input", {})

            result = pretool_emergency_check(tool_input)

            if result:
                print(json.dumps(result))
                sys.exit(0)

            sys.exit(0)  # Pass through

        except Exception as e:
            print(json.dumps({"error": f"Hook error: {str(e)}"}), file=sys.stderr)
            sys.exit(1)

    elif command == "posttool":
        try:
            payload = json.loads(sys.stdin.read())
            tool_name = payload.get("tool_name", "")
            tool_output = payload.get("tool_output", {})

            posttool_monitor(tool_name, tool_output)
            sys.exit(0)  # Always pass through

        except Exception as e:
            # Silently fail - don't block on monitoring errors
            sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
