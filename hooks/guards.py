#!/usr/bin/env python3
"""
Guards Consolidated Hook - Plan guardian, plan comments, and skill parsing.

This module consolidates plan-related hooks into a single file
with mode dispatch based on command-line argument.

Usage:
  python3 guards.py guardian          # PostToolUse: Plan drift detection
  python3 guards.py plan-comments     # UserPromptSubmit: Plan comment tracking
  python3 guards.py plan-write-check  # PostToolUse: Check for USER comments
  python3 guards.py skill-parser      # UserPromptSubmit: Parse /start command arguments
  python3 guards.py hook-sync         # PostToolUse: Sync expected-hooks count
  python3 guards.py insights-reminder # PostToolUse: Remind about Insights section
"""

import json
import re
import signal
import sys
from pathlib import Path


# =============================================================================
# Stdin Timeout - Prevent hanging on missing stdin
# =============================================================================

def timeout_handler(signum, frame):
    """Silent exit on timeout - prevents hooks from hanging."""
    sys.exit(0)

# Set 5 second timeout for stdin read operations
signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(5)


# =============================================================================
# Helper Functions
# =============================================================================

def extract_file_path(tool_input: dict) -> str | None:
    """Extract file path from tool input."""
    return (
        tool_input.get("file_path")
        or tool_input.get("filePath")
        or tool_input.get("path")
    )


# =============================================================================
# Plan Rename Tracking (PostToolUse)
# =============================================================================

def track_plan_rename() -> None:
    """
    Track plan file renames and update associated task queue files.

    When a plan file in /plans/ is renamed or moved, this hook:
    1. Finds any task-queue-{old-plan-id}.json referencing the old path
    2. Updates the plan_id and plan_file fields
    3. Renames the queue file to match the new plan ID

    This ensures task queues stay synchronized with their plan files.
    """
    import glob as glob_module

    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})

    # Get the file path that was edited/written
    old_path = extract_file_path(tool_input)
    if not old_path:
        sys.exit(0)

    # Only track plan files
    if "/plans/" not in old_path or not old_path.endswith(".md"):
        sys.exit(0)

    # Check if file was renamed (new_path in tool_result for Write operations)
    new_path = tool_result.get("file_path") if isinstance(tool_result, dict) else None

    # If no rename detected, just exit
    if not new_path or new_path == old_path:
        sys.exit(0)

    # Find queue files that reference the old path
    queue_pattern = ".claude/task-queue-*.json"
    for queue_file in glob_module.glob(queue_pattern):
        try:
            with open(queue_file) as f:
                queue = json.load(f)

            if queue.get("plan_file") == old_path:
                # Extract new plan_id from filename
                import os
                new_id = os.path.basename(new_path).replace(".md", "")

                # Update queue data
                queue["plan_id"] = new_id
                queue["plan_file"] = new_path

                # Write updated queue
                with open(queue_file, "w") as f:
                    json.dump(queue, f, indent=2)

                # Rename queue file to match new plan ID
                new_queue_file = f".claude/task-queue-{new_id}.json"
                if queue_file != new_queue_file:
                    import shutil
                    shutil.move(queue_file, new_queue_file)

                # Log the update
                from datetime import datetime, timezone
                timestamp = datetime.now(timezone.utc).isoformat()

                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": f"Task queue updated: {queue_file} -> {new_queue_file}"
                    }
                }
                print(json.dumps(output))
                break

        except (json.JSONDecodeError, OSError):
            continue

    sys.exit(0)


# =============================================================================
# Plan Guardian (PostToolUse)
# =============================================================================

# New nested structure under .claude/ralph/
RALPH_STATE_FILE = ".claude/ralph/state.json"
GUARDIAN_CONFIG_FILE = ".claude/ralph/guardian/config.json"
PLAN_DIGEST_FILE = ".claude/ralph/guardian/digest.json"
GUARDIAN_LOG_FILE = ".claude/ralph/guardian/log.json"
GUARDIAN_COUNTER_FILE = ".claude/ralph/guardian/counter"

# Legacy paths for migration detection
LEGACY_RALPH_STATE_FILE = ".claude/ralph-state.json"
LEGACY_GUARDIAN_CONFIG_FILE = ".claude/guardian-config.json"
LEGACY_PLAN_DIGEST_FILE = ".claude/plan-digest.json"
LEGACY_GUARDIAN_LOG_FILE = ".claude/guardian-log.json"
LEGACY_GUARDIAN_COUNTER_FILE = ".claude/guardian-counter"


def ensure_ralph_dirs() -> None:
    """Ensure Ralph directory structure exists."""
    dirs = [
        Path(".claude/ralph"),
        Path(".claude/ralph/checkpoints"),
        Path(".claude/ralph/guardian"),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def migrate_legacy_guardian_files() -> None:
    """Migrate legacy guardian files to new nested structure."""
    migrations = [
        (LEGACY_RALPH_STATE_FILE, RALPH_STATE_FILE),
        (LEGACY_GUARDIAN_CONFIG_FILE, GUARDIAN_CONFIG_FILE),
        (LEGACY_PLAN_DIGEST_FILE, PLAN_DIGEST_FILE),
        (LEGACY_GUARDIAN_LOG_FILE, GUARDIAN_LOG_FILE),
        (LEGACY_GUARDIAN_COUNTER_FILE, GUARDIAN_COUNTER_FILE),
    ]
    for legacy, new in migrations:
        legacy_path = Path(legacy)
        new_path = Path(new)
        if legacy_path.exists() and not new_path.exists():
            new_path.parent.mkdir(parents=True, exist_ok=True)
            legacy_path.rename(new_path)


def plan_guardian() -> None:
    """Monitor agent actions and detect drift from plan."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    # Migrate legacy files if needed
    migrate_legacy_guardian_files()

    # Check if ralph state exists and guardian is enabled
    state_path = Path(RALPH_STATE_FILE)
    if not state_path.exists():
        sys.exit(0)

    try:
        with open(state_path) as f:
            state = json.load(f)
        if not state.get("guardianEnabled", False):
            sys.exit(0)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    # Check if plan digest exists
    digest_path = Path(PLAN_DIGEST_FILE)
    if not digest_path.exists():
        sys.exit(0)

    # Ensure directories exist for guardian files
    ensure_ralph_dirs()

    # Get sampling rate
    sampling_rate = 5
    config_path = Path(GUARDIAN_CONFIG_FILE)
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            sampling_rate = config.get("sampling_rate", {}).get("default", 5)
        except (json.JSONDecodeError, OSError):
            pass

    # Increment and check counter for sampling
    Path(".claude").mkdir(parents=True, exist_ok=True)
    counter_path = Path(GUARDIAN_COUNTER_FILE)
    counter = 0
    if counter_path.exists():
        try:
            counter = int(counter_path.read_text().strip())
        except (ValueError, OSError):
            pass
    counter += 1
    counter_path.write_text(str(counter))

    if counter % sampling_rate != 0:
        sys.exit(0)

    # Extract tool info
    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})
    file_path = extract_file_path(tool_input)

    if not file_path:
        sys.exit(0)

    # Read plan digest
    try:
        with open(digest_path) as f:
            digest = json.load(f)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    scope_markers = digest.get("scope_markers", {})
    out_of_scope = scope_markers.get("out_of_scope", [])
    scope_creep = scope_markers.get("scope_creep_indicators", [])

    # Check for drift
    drift_detected = False
    drift_reason = ""

    for pattern in out_of_scope:
        if re.search(pattern, file_path):
            drift_detected = True
            drift_reason = f"File matches out-of-scope pattern: {file_path}"
            break

    if not drift_detected:
        for pattern in scope_creep:
            if re.search(pattern, file_path):
                drift_detected = True
                drift_reason = f"File matches scope-creep indicator: {file_path}"
                break

    # Log the check
    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()

    log_entry = {
        "timestamp": timestamp,
        "tool": tool_name,
        "file": file_path,
        "drift_detected": drift_detected,
        "reason": drift_reason
    }

    log_path = Path(GUARDIAN_LOG_FILE)
    try:
        if log_path.exists():
            with open(log_path) as f:
                log_data = json.load(f)
        else:
            log_data = {"checks": []}
        log_data["checks"].append(log_entry)
        log_data["checks"] = log_data["checks"][-100:]
        with open(log_path, "w") as f:
            json.dump(log_data, f, indent=2)
    except (json.JSONDecodeError, OSError):
        pass

    # Output warning if drift detected
    if drift_detected:
        boundaries = digest.get("boundaries", {})
        must_have = ", ".join(boundaries.get("must_have", []))
        must_not = ", ".join(boundaries.get("must_not_have", []))

        warning_msg = f"""PLAN GUARDIAN WARNING

Detected potential drift from implementation plan.

Concern: {drift_reason}

Action: Please verify this change aligns with the plan:
- Review the implementation plan
- If intentional, acknowledge with 'Guardian: Acknowledged'
- If unintended, revert and refocus on plan tasks

Plan boundaries:
- Must have: {must_have}
- Must not have: {must_not}"""

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": warning_msg
            }
        }
        print(json.dumps(output))

    sys.exit(0)


# =============================================================================
# Plan Comments (UserPromptSubmit)
# =============================================================================

def plan_comments() -> None:
    """
    Detect plan context and inject tracking guidelines.
    Also scans /plans/ directory for unprocessed USER: comments.

    Activates when:
    1. permission_mode == "plan" (formal plan mode)
    2. User says "review user comments" or "update the plan"
    3. Recent transcript shows /plans/ file edits (post-approval adjustments)
    4. USER: comments found in any plan file

    Behavior after plan approval:
    - Small adjustments: Auto-apply without re-entering plan mode
    - Significant changes: Shift+Tab to re-enter plan mode
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    permission_mode = data.get("permission_mode", "default")
    prompt = data.get("prompt", "").lower()
    transcript_path = data.get("transcript_path", "")
    cwd = data.get("cwd", ".")

    # Scan for USER comments in plan files
    plans_dir = Path(cwd) / "plans"
    user_comments: dict[str, list[str]] = {}
    if plans_dir.exists():
        for plan in plans_dir.glob("*.md"):
            try:
                content = plan.read_text()
                matches = re.findall(r'USER:.*', content)
                if matches:
                    user_comments[str(plan)] = matches
            except OSError:
                pass

    # Check for recent plan file edits
    recent_plan_edit = False
    if transcript_path:
        try:
            with open(transcript_path) as f:
                # Read last 20 lines
                lines = f.readlines()[-20:]
                recent_plan_edit = "/plans/" in "".join(lines)
        except OSError:
            pass

    # Determine if plan context applies
    is_plan_context = (
        permission_mode == "plan" or
        "review user comments" in prompt or
        "update the plan" in prompt or
        "process user comments" in prompt or
        "/reviewplan" in prompt or
        recent_plan_edit or
        bool(user_comments)
    )

    if not is_plan_context:
        sys.exit(0)  # Allow, no injection

    # Build injection message
    base_msg = """Plan Change Tracking active:
1. Remove ALL existing 🟧 (Orange Square) markers
2. Add 🟧 marker AT END of modified lines (not beginning - avoids breaking markdown)
3. Update "Last Updated" timestamp
4. Process and remove USER: comments"""

    if user_comments:
        files_list = "\n".join(f"  - {f}: {len(c)} comment(s)" for f, c in user_comments.items())
        base_msg += f"""

⚠️ UNPROCESSED USER COMMENTS DETECTED:
{files_list}

MANDATORY: Process each USER: comment NOW:
1. Read the USER: comment
2. Apply the requested change
3. Remove the USER: line
4. Add 🟧 at END of modified line
5. Update "Last Updated" timestamp

Run /reviewplan for thorough processing."""

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": base_msg
        }
    }
    print(json.dumps(output))
    sys.exit(0)


# =============================================================================
# Plan Write Check (PostToolUse)
# =============================================================================

def plan_write_check() -> None:
    """
    Check plan files after write for unprocessed USER comments.
    Fires on PostToolUse for Write/Edit operations on /plans/*.md files.
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = extract_file_path(tool_input)

    if not file_path:
        sys.exit(0)

    # Only check plan files
    if "/plans/" not in file_path or not file_path.endswith(".md"):
        sys.exit(0)

    # Check for USER comments in the file
    try:
        content = Path(file_path).read_text()
        if re.search(r'\bUSER:', content):
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": f"""⚠️ UNPROCESSED USER COMMENTS in {Path(file_path).name}

Plan file still contains USER: comments that need processing.

REQUIRED before continuing:
1. Read each USER: comment
2. Apply the requested change
3. Remove the USER: line
4. Add 🟧 (Orange Square) at END of modified line
5. Update "Last Updated" timestamp

Run /reviewplan for thorough processing."""
                }
            }
            print(json.dumps(output))
    except OSError:
        pass

    sys.exit(0)


# =============================================================================
# Skill Parser (UserPromptSubmit)
# =============================================================================

def skill_parser() -> None:
    """Parse /start command arguments into structured format.

    Injects parsed arguments into context for consistent interpretation.
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    prompt = data.get("prompt", "").strip()

    # Only process /start commands
    if not prompt.startswith("/start"):
        sys.exit(0)

    # Parse arguments
    args_str = prompt[6:].strip()  # Remove "/start"
    tokens = args_str.split()

    result = {
        "agents": 3,
        "iterations": 3,
        "mode": "implement",
        "reviewAgents": 5,
        "reviewIterations": 2,
        "postReviewEnabled": True,
        "task": "",
        "raw": args_str
    }

    i = 0
    # Parse leading numbers
    if i < len(tokens) and tokens[i].isdigit():
        result["agents"] = int(tokens[i])
        i += 1
    if i < len(tokens) and tokens[i].isdigit():
        result["iterations"] = int(tokens[i])
        i += 1

    # Parse keywords
    if i < len(tokens):
        if tokens[i] == "noreview":
            result["mode"] = "implement"
            result["postReviewEnabled"] = False
            i += 1
        elif tokens[i] == "import":
            result["mode"] = "import"
            i += 1
        elif tokens[i] == "review":
            i += 1
            # Check if next tokens are numbers (custom review config)
            if i < len(tokens) and tokens[i].isdigit():
                result["reviewAgents"] = int(tokens[i])
                i += 1
                if i < len(tokens) and tokens[i].isdigit():
                    result["reviewIterations"] = int(tokens[i])
                    i += 1
                # This is custom post-review config, not review-only mode
                result["mode"] = "implement"
            else:
                # Review-only mode
                result["mode"] = "review"

    result["task"] = " ".join(tokens[i:])

    # Build Ralph Configuration template for plan files
    ralph_config = f"""**Ralph Configuration:**
- Implementation Agents: {result["agents"]}
- Implementation Iterations: {result["iterations"]}
- Post-Review Agents: {result["reviewAgents"]}
- Post-Review Iterations: {result["reviewIterations"]}
- Launch Command: `/start {args_str}`"""

    # Inject parsed args with Ralph Configuration template
    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": f"""<skill-parsed-args>
{json.dumps(result, indent=2)}
</skill-parsed-args>

PARSED ARGUMENTS (MUST USE THESE VALUES):
- Agents: {result["agents"]}
- Iterations: {result["iterations"]}
- Mode: {result["mode"]}
- Post-Review Enabled: {result["postReviewEnabled"]}
- Post-Review Agents: {result["reviewAgents"]}
- Post-Review Iterations: {result["reviewIterations"]}
- Task: {result["task"] or "(interactive planning mode)"}

RALPH CONFIGURATION (COPY TO PLAN FILE):
{ralph_config}"""
        }
    }
    print(json.dumps(output))
    sys.exit(0)


# =============================================================================
# Hook Sync (PostToolUse) - Auto-sync expected-hooks count
# =============================================================================

def hook_sync() -> None:
    """Sync expected-hooks count after settings.json modification.

    Fixes for 8 identified silent failure edge cases:
    1. Exact filename match (not substring)
    2. Logging for write failures
    3. File locking for concurrent writes
    4. Use edited file's directory for .expected-hooks
    5. Expand ~ early in process
    6. Log JSON decode errors
    7. Validate hook structure before counting
    8. Clean exit on errors
    """
    import fcntl

    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        # Fix #6: Log JSON decode errors instead of silent exit
        sys.stderr.write(f"hook_sync: Invalid JSON input: {e}\n")
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = extract_file_path(tool_input)

    # Fix #5: Expand ~ early before any checks
    if file_path and file_path.startswith("~"):
        file_path = str(Path(file_path).expanduser())

    # Fix #1: Exact filename match, not substring
    if not file_path:
        sys.exit(0)
    edited_path = Path(file_path)
    if edited_path.name != "settings.json":
        sys.exit(0)

    # Fix #4: Use the actual edited settings.json, not hardcoded path
    settings_path = edited_path if edited_path.exists() else Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        sys.stderr.write(f"hook_sync: Settings file not found: {settings_path}\n")
        sys.exit(0)

    try:
        with open(settings_path) as f:
            settings = json.load(f)
    except json.JSONDecodeError as e:
        # Fix #6: Log malformed JSON
        sys.stderr.write(f"hook_sync: Malformed settings.json: {e}\n")
        sys.exit(0)
    except OSError as e:
        sys.stderr.write(f"hook_sync: Cannot read settings: {e}\n")
        sys.exit(0)

    # Fix #7: Validate hook structure with type checks
    hook_count = 0
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        sys.stderr.write(f"hook_sync: Invalid hooks structure (not dict)\n")
        sys.exit(0)

    for event_name, event_hooks in hooks.items():
        if not isinstance(event_hooks, list):
            continue
        for hook_group in event_hooks:
            if not isinstance(hook_group, dict):
                continue
            inner_hooks = hook_group.get("hooks", [])
            if not isinstance(inner_hooks, list):
                continue
            for hook in inner_hooks:
                if isinstance(hook, dict) and hook.get("type") == "command" and hook.get("command"):
                    hook_count += 1

    # Fix #4: Write .expected-hooks in same directory as settings.json
    expected_path = settings_path.parent / ".expected-hooks"

    # Fix #3: File locking for concurrent writes
    try:
        with open(expected_path, "w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                f.write(str(hook_count))
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except (OSError, BlockingIOError) as e:
        # Fix #2: Log write failures instead of silent pass
        sys.stderr.write(f"hook_sync: Cannot write {expected_path}: {e}\n")

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"Hook count synced: {hook_count} hooks"
        }
    }
    print(json.dumps(output))
    sys.exit(0)


# =============================================================================
# Insights Reminder (PostToolUse)
# =============================================================================

def insights_reminder() -> None:
    """Remind to include Insights section after code edits."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_result = hook_input.get("tool_result", "")

    # If code was written, remind about insights
    if "```" in str(tool_result):
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "MANDATORY: Include ## Insights section with Decision/Trade-off/Watch format per Engineer.md"
            }
        }
        print(json.dumps(output))

    sys.exit(0)


# =============================================================================
# Ralph Agent Tracker (PostToolUse:Task)
# =============================================================================

def ralph_agent_tracker() -> None:
    """Track Ralph agent completion and enforce phase transitions.

    Fires after each Task tool completes. Updates ralph-state.json with:
    - Completed agent count
    - Phase transitions (implementation → review → complete)

    When all agents in a phase complete, injects MANDATORY instructions
    to proceed to next phase.
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")

    # Only trigger on Task completion
    if tool_name != "Task":
        sys.exit(0)

    # Check for ralph state (try new path first, then legacy)
    state_path = Path(RALPH_STATE_FILE)
    if not state_path.exists():
        # Try legacy path for backward compatibility
        state_path = Path(LEGACY_RALPH_STATE_FILE)
        if not state_path.exists():
            sys.exit(0)

    try:
        with open(state_path) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        sys.exit(0)

    # Track completion
    phase = state.get("phase", "implementation")
    completed = state.get("completedAgents", 0) + 1
    state["completedAgents"] = completed

    from datetime import datetime, timezone
    timestamp = datetime.now(timezone.utc).isoformat()

    # Log activity
    activity_log = state.get("activityLog", [])
    activity_log.append({
        "timestamp": timestamp,
        "event": "agent_completed",
        "phase": phase,
        "completed": completed
    })
    state["activityLog"] = activity_log[-50:]  # Keep last 50

    # Determine phase transition
    output_msg = None

    if phase == "implementation":
        expected = state.get("agents", 3)
        if completed >= expected:
            # All implementation agents done → transition to review
            review_config = state.get("review", {"agents": 5, "iterations": 2})
            review_agents = review_config.get("agents", 5)
            review_iterations = review_config.get("iterations", 2)
            task = state.get("task", "Review the implementation")

            state["phase"] = "review"
            state["completedAgents"] = 0  # Reset for review phase

            activity_log.append({
                "timestamp": timestamp,
                "event": "phase_transition",
                "from": "implementation",
                "to": "review"
            })

            output_msg = f"""🔄 RALPH PHASE TRANSITION: Implementation → Review

All {expected} implementation agents completed.

**MANDATORY NEXT STEP:**
Spawn {review_agents} review agents IN PARALLEL:

```
Task(subagent_type: "general-purpose", prompt: "RALPH Review Agent 1/{review_agents}: Review implementation for {task}")
Task(subagent_type: "general-purpose", prompt: "RALPH Review Agent 2/{review_agents}: Review implementation for {task}")
... (spawn all {review_agents} agents in a single message)
```

Review agents should:
1. Check for bugs, security issues, performance problems
2. Leave TODO comments (do NOT auto-fix)
3. Report findings to .claude/review-agents.md

**DO NOT** output completion signals yet. Spawn review agents NOW."""

    elif phase == "review":
        review_config = state.get("review", {"agents": 5, "iterations": 2})
        expected = review_config.get("agents", 5)
        if completed >= expected:
            # All review agents done → signal completion
            state["phase"] = "complete"
            state["completedAt"] = timestamp

            activity_log.append({
                "timestamp": timestamp,
                "event": "phase_transition",
                "from": "review",
                "to": "complete"
            })

            output_msg = f"""✅ RALPH LOOP COMPLETE

All {expected} review agents completed.

**MANDATORY FINAL STEP:**
Output BOTH completion signals NOW:

```
<promise>RALPH_COMPLETE</promise>
EXIT_SIGNAL: true
```

This will allow the session to exit properly.

**Summary:**
- Implementation agents: {state.get("agents", "?")} completed
- Review agents: {expected} completed
- Task: {state.get("task", "N/A")}
- Duration: {state.get("startedAt", "?")} → {timestamp}"""

    # Write updated state
    try:
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass

    # Output phase transition instructions
    if output_msg:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": output_msg
            }
        }
        print(json.dumps(output))

    sys.exit(0)


# =============================================================================
# Ralph Enforcer (PostToolUse:ExitPlanMode)
# =============================================================================

def ralph_enforcer() -> None:
    """Enforce Ralph agent spawning after plan approval.

    Triggers on ExitPlanMode and checks if:
    1. A plan file exists with Ralph Configuration
    2. If so, injects MANDATORY instructions to spawn agents

    This prevents the common failure mode where plan is approved
    but agents are never spawned.
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")

    # Only trigger on ExitPlanMode
    if tool_name != "ExitPlanMode":
        sys.exit(0)

    # Find the most recent plan file
    cwd = Path.cwd()
    plans_dir = cwd / "plans"
    if not plans_dir.exists():
        sys.exit(0)

    plan_files = sorted(plans_dir.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not plan_files:
        sys.exit(0)

    plan_file = plan_files[0]

    # Read the plan and extract Ralph Configuration
    try:
        content = plan_file.read_text()
    except OSError:
        sys.exit(0)

    # Look for Ralph Configuration block
    ralph_match = re.search(
        r'\*\*Ralph Configuration:\*\*.*?'
        r'- Implementation Agents: (\d+).*?'
        r'- Implementation Iterations: (\d+).*?'
        r'- Post-Review Agents: (\d+).*?'
        r'- Post-Review Iterations: (\d+)',
        content, re.DOTALL
    )

    if not ralph_match:
        sys.exit(0)

    impl_agents = int(ralph_match.group(1))
    impl_iterations = int(ralph_match.group(2))
    review_agents = int(ralph_match.group(3))
    review_iterations = int(ralph_match.group(4))

    # Extract task from plan title or Launch Command
    task_match = re.search(r'- Launch Command: `/start[^`]*task:\s*([^`]+)`', content)
    task = task_match.group(1).strip() if task_match else "Complete the implementation plan"

    # Create Ralph state file
    from datetime import datetime, timezone
    state = {
        "iteration": 1,
        "maxIterations": impl_iterations,
        "agents": impl_agents,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "phase": "implementation",
        "review": {
            "agents": review_agents,
            "iterations": review_iterations
        },
        "planFile": str(plan_file),
        "guardianEnabled": True,
        "stuckDetection": {
            "consecutiveErrors": [],
            "lastCompletedTask": None,
            "iterationsSinceProgress": 0,
            "buildErrors": []
        },
        "activityLog": []
    }

    state_path = cwd / ".claude" / "ralph" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass

    # Generate agent spawn instructions
    agent_prompts = []
    for i in range(1, impl_agents + 1):
        agent_prompts.append(f'Task(subagent_type: "general-purpose", prompt: "RALPH Agent {i}/{impl_agents}: {task}")')

    spawn_instructions = "\n".join(agent_prompts[:5])  # Show first 5 as example
    if impl_agents > 5:
        spawn_instructions += f"\n... and {impl_agents - 5} more agents"

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"""🚀 RALPH AGENT SPAWNING REQUIRED

Plan approved. Ralph state initialized.

**Configuration Detected:**
- Implementation: {impl_agents} agents × {impl_iterations} iterations
- Post-Review: {review_agents} agents × {review_iterations} iterations
- Task: {task}

**MANDATORY NEXT STEP:**
You MUST now spawn {impl_agents} agents IN PARALLEL using a single message with multiple Task tool calls:

```
{spawn_instructions}
```

**DO NOT** implement directly. Spawn the agents NOW.

After all implementation agents complete:
1. Spawn {review_agents} review agents
2. Wait for review completion
3. Output: RALPH_COMPLETE + EXIT_SIGNAL

State file created: {state_path}"""
        }
    }
    print(json.dumps(output))
    sys.exit(0)


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> None:
    """Main entry point with mode dispatch."""
    if len(sys.argv) < 2:
        print("Usage: guards.py [protect|guardian|plan-comments|plan-write-check|skill-parser|hook-sync|insights-reminder|ralph-enforcer|ralph-agent-tracker|plan-rename-tracker]", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "protect":
        # protect_files() removed - was causing TTY issues
        sys.exit(0)
    elif mode == "guardian":
        plan_guardian()
    elif mode == "plan-comments":
        plan_comments()
    elif mode == "plan-write-check":
        plan_write_check()
    elif mode == "skill-parser":
        skill_parser()
    elif mode == "hook-sync":
        hook_sync()
    elif mode == "insights-reminder":
        insights_reminder()
    elif mode == "ralph-enforcer":
        ralph_enforcer()
    elif mode == "ralph-agent-tracker":
        ralph_agent_tracker()
    elif mode == "plan-rename-tracker":
        track_plan_rename()
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
