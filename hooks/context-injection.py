#!/usr/bin/env python3
"""
Context Injection Hook - Inject Ralph state into subagent startup context

Provides awareness of Ralph protocol state to team agents at startup.
Complements native Agent Teams coordination by injecting Ralph-specific metadata
(phase, iteration progress, build intelligence) that isn't part of native team context.

Hook Type: SubagentStart
Trigger: When a subagent spawns
Output: Additional context with Ralph state summary

Usage:
  python context-injection.py    # Reads stdin JSON, outputs augmented context
"""

import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime


# =============================================================================
# Configuration
# =============================================================================

RALPH_STATE_FILE = ".claude/ralph/state.json"
BUILD_INTELLIGENCE_FILE = ".claude/ralph/build-intelligence.json"
MAX_CONTEXT_CHARS = 500  # Keep injected context concise


# =============================================================================
# Ralph State Reading
# =============================================================================


def read_ralph_state() -> Optional[dict]:
    """Read Ralph state file if it exists."""
    state_path = Path(RALPH_STATE_FILE)
    if not state_path.exists():
        return None

    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def read_build_intelligence() -> Optional[dict]:
    """Read build intelligence file if it exists."""
    bi_path = Path(BUILD_INTELLIGENCE_FILE)
    if not bi_path.exists():
        return None

    try:
        return json.loads(bi_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


# =============================================================================
# Context Formatting
# =============================================================================


def format_phase_context(state: dict) -> str:
    """Format Ralph phase and iteration progress."""
    phase = state.get("phase", "unknown")
    total_agents = state.get("total_agents", 0)
    max_iterations = state.get("max_iterations", 0)

    # Count completed agents
    agents = state.get("agents", [])
    completed = sum(1 for a in agents if a.get("status") == "completed")
    in_progress = sum(1 for a in agents if a.get("status") == "in_progress")

    return (
        f"**Ralph Phase:** {phase.title()} | "
        f"Agents: {completed}/{total_agents} done, {in_progress} active | "
        f"Max iterations: {max_iterations}"
    )


def format_build_intelligence(bi: dict) -> str:
    """Format build intelligence summary."""
    summary = bi.get("summary", {})
    total_struggling = summary.get("total_struggling", 0)

    if total_struggling == 0:
        return "**Build Status:** All agents healthy"

    struggling_agents = []
    agents_data = bi.get("agents", {})
    for agent_id, data in agents_data.items():
        if data.get("struggling"):
            errors = data.get("errors", 0)
            struggling_agents.append(f"{agent_id} ({errors} errors)")

    agents_str = ", ".join(struggling_agents[:3])  # Limit to 3 for brevity
    if len(struggling_agents) > 3:
        agents_str += f" +{len(struggling_agents) - 3} more"

    return f"**Build Status:** {total_struggling} struggling — {agents_str}"


def build_context_block(state: dict, bi: Optional[dict]) -> str:
    """Build the complete Ralph context injection block."""
    lines = ["<!-- Ralph Context Injection -->"]

    # Phase and iteration progress
    lines.append(format_phase_context(state))

    # Build intelligence (if available)
    if bi:
        lines.append(format_build_intelligence(bi))

    # Task summary
    task = state.get("task")
    if task and len(task) < 100:  # Only show short task descriptions
        lines.append(f"**Task:** {task}")

    result = "\n".join(lines)

    # Truncate if too long
    if len(result) > MAX_CONTEXT_CHARS:
        result = result[:MAX_CONTEXT_CHARS - 3] + "..."

    return result


# =============================================================================
# Hook Handler
# =============================================================================


def main() -> None:
    """SubagentStart hook handler for context injection."""
    # Quick exit if not in Ralph mode
    ralph_active = Path(RALPH_STATE_FILE).exists()
    if not ralph_active:
        # Pass through — no Ralph state to inject
        sys.exit(0)

    # Read Ralph state
    state = read_ralph_state()
    if not state:
        # No state file or invalid — pass through
        sys.exit(0)

    # Read build intelligence (optional)
    bi = read_build_intelligence()

    # Build context block
    context_block = build_context_block(state, bi)

    # Output augmented context via SubagentStart hook schema
    # SubagentStart hooks use: {hookEventName, additionalContext}
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": context_block,
        }
    }

    sys.stdout.write(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
