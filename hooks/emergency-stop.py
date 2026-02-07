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
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Import ACID transaction primitives
from transaction import atomic_write_json, transactional_update


# =============================================================================
# Configuration
# =============================================================================

# Load configuration from environment or config file
def _load_config():
    """Load emergency stop configuration from environment or defaults."""
    config_file = Path.home() / ".claude" / "security" / "emergency-config.json"
    defaults = {
        "block_threshold": 5,
        "time_window": 60,
    }

    # Try environment variables first
    env_threshold = os.environ.get("CLAUDE_EMERGENCY_THRESHOLD")
    env_window = os.environ.get("CLAUDE_EMERGENCY_WINDOW")

    if env_threshold:
        try:
            defaults["block_threshold"] = int(env_threshold)
        except ValueError:
            pass

    if env_window:
        try:
            defaults["time_window"] = int(env_window)
        except ValueError:
            pass

    # Try config file
    if config_file.exists():
        try:
            with open(config_file, "r") as f:
                config = json.load(f)
                defaults.update(config)
        except (json.JSONDecodeError, OSError):
            pass

    return defaults

_CONFIG = _load_config()
STATE_FILE = Path.home() / ".claude" / "security" / "emergency-state.json"
BLOCK_THRESHOLD = _CONFIG["block_threshold"]
TIME_WINDOW = _CONFIG["time_window"]


# =============================================================================
# State Management
# =============================================================================

def load_state() -> Dict:
    """Load emergency stop state with integrity checking."""
    default_state = {
        "blocks": [],  # List of (timestamp, reason) tuples
        "shutdowns": [],  # List of shutdown events
        "manual_kill": False,
        "integrity_marker": "claude_emergency_state_v1"
    }

    if not STATE_FILE.exists():
        return default_state

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)

        # Validate structure integrity
        if state.get("integrity_marker") != "claude_emergency_state_v1":
            # File tampered or corrupted - preserve but start fresh counts
            state["blocks"] = []
            state["integrity_marker"] = "claude_emergency_state_v1"

        # Ensure required keys exist
        for key in ["blocks", "shutdowns", "manual_kill"]:
            if key not in state:
                state[key] = default_state[key]

        return state
    except (json.JSONDecodeError, KeyError, TypeError):
        return default_state


def save_state(state: Dict) -> None:
    """Save emergency stop state atomically."""
    atomic_write_json(STATE_FILE, state, fsync=True)


def record_block(reason: str) -> None:
    """Record a security block event with transactional update."""
    # Validate and truncate reason to prevent disk exhaustion
    if not isinstance(reason, str):
        reason = str(reason)
    reason = reason[:500]  # Limit reason length

    # Default state for new files
    default_state = {
        "blocks": [],
        "shutdowns": [],
        "manual_kill": False,
        "integrity_marker": "claude_emergency_state_v1"
    }

    # Update function for transactional_update
    def update_fn(state):
        now = time.time()

        # Ensure state has required fields
        if not isinstance(state, dict):
            state = default_state.copy()
        for key in default_state:
            if key not in state:
                state[key] = default_state[key]

        # Add new block
        state["blocks"].append({"timestamp": now, "reason": reason})

        # Prune blocks older than time window
        cutoff = now - TIME_WINDOW
        state["blocks"] = [b for b in state["blocks"] if b["timestamp"] > cutoff]

        # Ensure integrity marker
        state["integrity_marker"] = "claude_emergency_state_v1"

        return state

    # Transactional update with exclusive locking
    transactional_update(
        STATE_FILE,
        update_fn,
        default=default_state,
        fsync=True
    )


# Severity weights for different block types
SEVERITY_WEIGHTS = {
    "secret_leak": 5,      # Critical - immediate concern
    "blocked_command": 3,  # High - potentially dangerous
    "sandbox_violation": 2, # Medium - boundary issues
    "default": 1           # Low - minor issues
}


def check_threshold() -> Optional[str]:
    """
    Check if block threshold exceeded using severity-weighted scoring.

    Returns:
        Optional[str]: Shutdown reason if threshold exceeded
    """
    state = load_state()
    now = time.time()
    cutoff = now - TIME_WINDOW

    # Count recent blocks with severity weighting
    recent_blocks = [b for b in state["blocks"] if b["timestamp"] > cutoff]

    # Calculate weighted score
    total_score = 0
    for block in recent_blocks:
        reason = block.get("reason", "")
        weight = SEVERITY_WEIGHTS.get("default", 1)
        for key, w in SEVERITY_WEIGHTS.items():
            if key in reason.lower():
                weight = w
                break
        total_score += weight

    # Threshold is now severity-weighted (5 low = 1 critical)
    if total_score >= BLOCK_THRESHOLD * SEVERITY_WEIGHTS["default"] * 5:
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
    PostToolUse hook - monitor for security events from all sources.

    Records blocks from security-gate.py and other hooks for threshold tracking.
    """
    # Check if security-gate blocked this operation
    if isinstance(tool_output, dict) and tool_output.get("blocked"):
        reason = tool_output.get("reason", "unknown")
        record_block(f"security-gate: {reason}")

    # Monitor for blocks from other hook sources
    if isinstance(tool_output, dict):
        hook_output = tool_output.get("hookSpecificOutput", {})
        if isinstance(hook_output, dict):
            decision = hook_output.get("permissionDecision", "")
            if decision == "deny":
                reason = hook_output.get("permissionDecisionReason", "unknown")
                source = hook_output.get("hookEventName", "unknown-hook")
                record_block(f"{source}: {reason}")

    # Alert user if approaching threshold (80% of threshold)
    state = load_state()
    now = time.time()
    cutoff = now - TIME_WINDOW
    recent_blocks = [b for b in state["blocks"] if b["timestamp"] > cutoff]

    if len(recent_blocks) >= int(BLOCK_THRESHOLD * 0.8):
        alert_file = STATE_FILE.parent / "emergency-alert.txt"
        try:
            alert_file.write_text(
                f"WARNING: {len(recent_blocks)}/{BLOCK_THRESHOLD} blocks in last {TIME_WINDOW}s\n"
                f"Approaching emergency shutdown threshold.\n"
                f"Recent blocks: {[b['reason'] for b in recent_blocks[-3:]]}\n"
            )
        except OSError:
            pass


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """Hook entry point."""
    if len(sys.argv) < 2:
        sys.exit(0)

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
            payload = json.loads(sys.stdin.buffer.read().decode('utf-8', errors='replace'))
            tool_input = payload.get("tool_input", {})

            result = pretool_emergency_check(tool_input)

            if result:
                print(json.dumps(result))
                sys.exit(0)

            sys.exit(0)  # Pass through

        except Exception:
            sys.exit(0)

    elif command == "posttool":
        try:
            payload = json.loads(sys.stdin.buffer.read().decode('utf-8', errors='replace'))
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
