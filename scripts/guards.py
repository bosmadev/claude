#!/usr/bin/env python3
"""
Guards Consolidated Hook - Plan guardian, plan comments, skill parsing, and more.

This module consolidates plan-related hooks and skill dispatch into a single file
with mode dispatch based on command-line argument.

Usage:
  python3 guards.py protect              # (disabled) File protection
  python3 guards.py guardian             # PostToolUse: Plan drift detection
  python3 guards.py plan-comments        # UserPromptSubmit: Plan comment tracking
  python3 guards.py plan-write-check     # PostToolUse: Check for USER comments
  python3 guards.py skill-parser         # UserPromptSubmit: Parse /start command arguments
  python3 guards.py insights-reminder    # PostToolUse: Remind about Insights section
  python3 guards.py ralph-enforcer       # Ralph protocol enforcement
  python3 guards.py ralph-agent-tracker  # (deprecated) Redirects to scripts/ralph.py
  python3 guards.py skill-interceptor    # Skill interception and routing
  python3 guards.py skill-validator      # Skill validation checks
  python3 guards.py plan-rename-tracker  # Track plan file renames
  python3 guards.py auto-ralph           # UserPromptSubmit: Auto-spawn Ralph agents for permissive modes
  python3 guards.py quality-deprecation      # PostToolUse: Warn about /quality deprecation
  python3 guards.py fs-guard                 # PreToolUse: Block new file/folder creation and deletion
  python3 guards.py x-post-check             # PostToolUse: Log /x skill Chrome MCP clicks
  python3 guards.py bypass-permissions-guard # PreToolUse: Validate commands in bypass mode
"""

import json
import os
import re
import sys
from pathlib import Path

# sys.path needed when invoked as hook: python scripts/guards.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# =============================================================================
# Stdin Timeout - Prevent hanging on missing stdin (cross-platform)
# =============================================================================

from scripts.compat import setup_stdin_timeout
setup_stdin_timeout(5)


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

    # Only track plan files (normalize separators for Windows)
    if "/plans/" not in old_path.replace("\\", "/") or not old_path.endswith(".md"):
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
            counter = int(counter_path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError, UnicodeDecodeError):
            pass
    counter += 1
    counter_path.write_text(str(counter), encoding="utf-8")

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
        try:
            if re.search(pattern, file_path):
                drift_detected = True
                drift_reason = f"File matches out-of-scope pattern: {file_path}"
                break
        except re.error as e:
            sys.stderr.write(f"plan_guardian: Invalid out_of_scope regex {pattern!r}: {e}\n")
            continue

    if not drift_detected:
        for pattern in scope_creep:
            try:
                if re.search(pattern, file_path):
                    drift_detected = True
                    drift_reason = f"File matches scope-creep indicator: {file_path}"
                    break
            except re.error as e:
                sys.stderr.write(f"plan_guardian: Invalid scope_creep regex {pattern!r}: {e}\n")
                continue

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
# Auto-Ralph Hook (UserPromptSubmit)
# =============================================================================

def auto_ralph_hook() -> None:
    """Auto-spawn Ralph agents based on permission mode.

    When permission_mode is permissive (acceptEdits, bypassPermissions, plan),
    inject Ralph directive suggesting parallel agent spawning.

    Activates only for permissive modes to avoid interfering with default/dontAsk workflows.
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    permission_mode = data.get("permission_mode", "default")

    # Only trigger for permissive modes
    if permission_mode not in ("acceptEdits", "bypassPermissions", "plan"):
        sys.exit(0)

    # Check if this is a task that would benefit from parallelization
    prompt = data.get("prompt", "").lower()

    # Skip if already using /start or other parallelization commands
    if any(cmd in prompt for cmd in ["/start", "/review", "spawn agents", "ralph"]):
        sys.exit(0)

    # Inject Ralph suggestion
    suggestion = """🚀 AUTO-RALPH SUGGESTION

Your permission mode is set to "{mode}", which enables autonomous operation.

For complex multi-step tasks, consider spawning parallel agents:
- Use `/start` for full implementation workflows
- Use `/start 10` to spawn 10 agents (adjust based on task complexity)
- For smaller tasks, 3-5 agents may be sufficient

This enables faster completion through parallel execution.

Continue with your current approach, or use `/start` for parallelization.""".format(mode=permission_mode)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": suggestion
        }
    }
    print(json.dumps(output))
    sys.exit(0)


# =============================================================================
# Plan Comments (UserPromptSubmit)
# =============================================================================

EMOJI_PLAN_RULES = """
## Emoji Plan Formatting (MANDATORY)
- Section headers: Add category emoji before title (🔒 Security, ⚡ Performance)
- Table headers: Add status emoji in relevant cells (✅ Done, ⚠️ Risk, ❌ Missing)
- Decision tables: Each row gets a leading emoji for visual scanning
- Comparison matrices: Use emoji columns for quick at-a-glance status
- Priority items: 🔴 Critical, 🟡 Medium, 🟢 Low
"""


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
        _plan_comments_impl()
    except Exception:
        sys.exit(0)  # Never crash — don't block user prompts


def _plan_comments_impl() -> None:
    """Inner implementation for plan_comments (wrapped by top-level safety net)."""
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    permission_mode = data.get("permission_mode", "default")
    prompt = data.get("prompt", "") or ""
    prompt = prompt.lower()
    transcript_path = data.get("transcript_path", "")
    cwd = data.get("cwd", ".")

    # Scan for USER comments in plan files
    plans_dir = Path(cwd) / "plans"
    user_comments: dict[str, list[str]] = {}
    if plans_dir.exists():
        for plan in plans_dir.glob("*.md"):
            try:
                content = plan.read_text(encoding="utf-8", errors="replace")
                matches = re.findall(r'USER:.*', content)
                if matches:
                    user_comments[str(plan)] = matches
            except (OSError, UnicodeDecodeError, ValueError):
                pass

    # Check for recent plan file edits (tail-read only)
    recent_plan_edit = False
    if transcript_path:
        try:
            with open(transcript_path, encoding="utf-8", errors="replace") as f:
                # Seek to last 8KB to avoid loading entire transcript
                try:
                    f.seek(0, 2)  # Seek to end
                    size = f.tell()
                    f.seek(max(0, size - 8192))
                except OSError:
                    pass
                tail = f.read()
                recent_plan_edit = "/plans/" in tail.replace("\\", "/")
        except (OSError, UnicodeDecodeError, ValueError):
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
4. Process and remove USER: comments

Markdown-Safe 🟧 Rules:
- Standard lines: at END of line
- Headings: after text (### Title 🟧)
- Tables: INSIDE last cell before pipe (| Change 🟧 |), NEVER on separator rows
- Code blocks: NEVER inside fences, mark line ABOVE the code block
- Lists: after item text (- Item 🟧)"""

    # Append emoji plan formatting rules
    base_msg += "\n" + EMOJI_PLAN_RULES

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

    # Only check plan files (normalize separators for Windows)
    if "/plans/" not in file_path.replace("\\", "/") or not file_path.endswith(".md"):
        sys.exit(0)

    # Check for USER comments in the file
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
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
# Skill Interceptor (UserPromptSubmit)
# =============================================================================

from scripts.compat import get_claude_home
_claude_home = get_claude_home()
SKILLS_DIR = _claude_home / "skills"

# Cache discovered skill names at module level (populated once per process)
_known_skills: list[str] | None = None


def _discover_skills() -> list[str]:
    """Scan SKILLS_DIR for subdirectory names."""
    global _known_skills
    if _known_skills is not None:
        return _known_skills
    try:
        _known_skills = sorted(
            d.name
            for d in SKILLS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    except OSError:
        _known_skills = []
    return _known_skills


def skill_interceptor() -> None:
    """Generic slash-command interceptor for all /skill commands except /start.

    Catches user prompts like /review, /commit, /quality, etc. and injects a
    MANDATORY Skill tool invocation directive so Claude never processes the
    slash command as plain text.

    /start is excluded because it has its own dedicated hook with argument parsing.

    Skips injection when the conversation already contains a SKILL_STARTED signal
    (set by skill_validator on PostToolUse:Skill) to avoid duplicate injection on
    re-entry or follow-up prompts in the same conversation turn.
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    prompt = data.get("prompt", "").strip()

    # Must start with / but not /start (which has its own hook)
    if not prompt.startswith("/") or prompt.startswith("/start"):
        sys.exit(0)

    # Extract the command name: first word after /
    # e.g. "/review pr 123" -> "review", "/commit confirm" -> "commit"
    match = re.match(r"^/([a-zA-Z][a-zA-Z0-9_-]*)", prompt)
    if not match:
        sys.exit(0)

    command_name = match.group(1).lower()

    # Verify it is a known skill
    known = _discover_skills()
    if command_name not in known:
        sys.exit(0)

    # Check for SKILL_STARTED signal to avoid re-injection
    # The signal file is per-session, written by skill_validator on PostToolUse:Skill
    signal_file = Path(".claude") / "skill-started.signal"
    if signal_file.exists():
        try:
            signal_data = json.loads(signal_file.read_text(encoding="utf-8"))
            # If the signal was written for this exact prompt, skip injection
            if signal_data.get("prompt") == prompt:
                sys.exit(0)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            pass

    # Extract arguments (everything after the command name)
    args = prompt[len(match.group(0)):].strip()

    # Build the injection directive
    skill_call = f'Skill(skill: "{command_name}"'
    if args:
        skill_call += f', args: "{args}"'
    skill_call += ")"

    directive = f"""MANDATORY SKILL INVOCATION — DO NOT PROCESS AS TEXT

The user typed a slash command: {prompt}

You MUST invoke the Skill tool IMMEDIATELY as your FIRST action.
Do NOT interpret this as a text message. Do NOT explain what you will do.
Do NOT generate any other response before invoking the skill.

REQUIRED tool call:
  {skill_call}

BLOCKING: No other tools or text output until the Skill tool is called."""

    output = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": directive
        }
    }
    print(json.dumps(output))
    sys.exit(0)


# =============================================================================
# Skill Validator (PostToolUse:Skill)
# =============================================================================

def skill_validator() -> None:
    """Write SKILL_STARTED signal after Skill tool executes.

    Called on PostToolUse for the Skill tool. Writes a signal file so that
    skill_interceptor knows the skill was already invoked and does not
    re-inject on subsequent prompts in the same turn.
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name != "Skill":
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    # Write signal file
    signal_file = Path(".claude") / "skill-started.signal"
    signal_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        signal_data = {
            "skill": skill_name,
            "prompt": f"/{skill_name} {tool_input.get('args', '')}".strip(),
        }
        signal_file.write_text(json.dumps(signal_data), encoding="utf-8")
    except OSError:
        pass

    sys.exit(0)


# =============================================================================
# Insights Reminder (PostToolUse)
# =============================================================================

def insights_reminder() -> None:
    """Remind to include Insights section after code edits.

    Rate-limited: only fires once every 10 edits to avoid context bloat.
    The identical 100-byte injection on every edit was accumulating ~30KB
    over long sessions, contributing to compaction failures.
    """
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_result = hook_input.get("tool_result", "")

    # If code was written, remind about insights (rate-limited)
    if "```" in str(tool_result):
        # Rate limit: only inject every 10th qualifying edit
        cwd = hook_input.get("cwd", ".")
        counter_path = Path(cwd) / ".claude" / "insights-counter"
        try:
            counter = int(counter_path.read_text(encoding="utf-8").strip()) if counter_path.exists() else 0
        except (ValueError, OSError):
            counter = 0
        counter += 1
        try:
            counter_path.parent.mkdir(parents=True, exist_ok=True)
            counter_path.write_text(str(counter), encoding="utf-8")
        except OSError:
            pass

        if counter % 10 != 1:  # Fire on 1st, 11th, 21st, etc.
            sys.exit(0)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "MANDATORY: Include ## Insights section with Decision/Trade-off/Watch format per Engineer.md"
            }
        }
        print(json.dumps(output))

    sys.exit(0)


# =============================================================================
# Ralph Agent Tracker — MOVED to scripts/ralph.py agent-tracker subcommand
# The hook in settings.json now calls: <python> <CLAUDE_HOME>/scripts/ralph.py agent-tracker
# =============================================================================


# =============================================================================
# Quality Deprecation Hook (PostToolUse:Skill)
# =============================================================================

def quality_deprecation_hook() -> None:
    """Emit deprecation warning when /quality is invoked.

    Triggers on PostToolUse:Skill when skill name is "quality".
    Informs user to use VERIFY+FIX phase, /review, or /rule instead.
    """
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    if tool_name != "Skill":
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    skill_name = tool_input.get("skill", "")

    if skill_name != "quality":
        sys.exit(0)

    # Emit deprecation warning
    warning = """⚠️ /quality is deprecated. Use instead:
  - Quality checks: Run automatically in VERIFY+FIX phase during /start
  - CLAUDE.md audit: Automatic in VERIFY+FIX (AskUserQuestion proposals)
  - Setup recommendations: Automatic in VERIFY+FIX (AskUserQuestion proposals)
  - Design review: Included in default /review and VERIFY+FIX
  - Security audit: Included in default /review
  - Behavior rules: /rule add

This skill will be removed in a future release."""

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": warning
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
        content = plan_file.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError, ValueError):
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
        "verify_fix": {
            "agents": 2,
            "iterations": 2
        },
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
# X Post Check (PostToolUse: computer) -- merged from x-guard.py
# =============================================================================

def x_post_check() -> None:
    """PostToolUse hook for computer tool during /x skill.

    Logs click actions when .x-session flag exists.
    Only activates during active /x skill sessions.
    """
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, TypeError):
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name != "computer":
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    action = tool_input.get("action", "")

    if action != "left_click":
        sys.exit(0)

    # Check for .x-session flag file
    session_flag = Path.cwd() / ".claude" / ".x-session"
    if not session_flag.exists():
        sys.exit(0)

    # Log the click action during /x skill
    coordinate = tool_input.get("coordinate", [])
    log_file = Path.home() / ".claude" / "security" / "x-clicks.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(log_file, "a") as f:
            f.write(f"CLICK at {coordinate}\n")
    except OSError:
        pass

    sys.exit(0)


# =============================================================================
# FS Guard (PreToolUse: Write, Bash)
# =============================================================================

def fs_guard() -> None:
    """Prompt user before new file/folder creation or deletion.

    Uses permissionDecision 'ask' to escalate to a TTY prompt when Claude tries to:
    - Create a new file (Write tool to a path that doesn't exist)
    - Delete a file or folder (Bash with rm/del/rmdir/Remove-Item)
    - Create a new folder (Bash with mkdir/New-Item -Type Directory)

    Edits to existing files pass through (handled by auto-allow.py).
    Works in acceptEdits mode — edits are auto-approved, creates/deletes prompt.
    """
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    result = None
    if tool_name == "Write":
        result = _fs_guard_write(tool_input)
    elif tool_name == "Bash":
        result = _fs_guard_bash(tool_input)

    if result:
        print(json.dumps(result))
    sys.exit(0)


def _fs_guard_write(tool_input: dict) -> dict | None:
    """Block Write tool if target file doesn't exist (new file creation)."""
    file_path = extract_file_path(tool_input)
    if not file_path:
        return None

    try:
        target = Path(file_path)
        if not target.exists():
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": (
                        f"New file: {file_path}"
                    ),
                }
            }
    except Exception:
        pass

    return None  # File exists — let auto-allow handle it


def _fs_guard_bash(tool_input: dict) -> dict | None:
    """Block Bash commands that create or delete files/folders."""
    command = tool_input.get("command", "")
    if not command:
        return None

    # Deletion patterns — require command position (start of line, after && ; |)
    # to avoid false positives on filenames like README.md or flags like --format rd
    _CMD = r'(?:^|(?<=&&)|(?<=;)|(?<=\|))\s*'  # command position anchor
    delete_patterns = [
        r'\brm\s',              # Unix rm (must be followed by space)
        r'\brmdir\b',           # rmdir
        r'\bdel\s',             # Windows del (must be followed by space)
        r'\bRemove-Item\b',     # PowerShell
        _CMD + r'rd\s',         # Windows rd — anchored to avoid "third", ".rd"
    ]

    # Creation patterns
    create_patterns = [
        r'\bmkdir\b',           # mkdir (Unix/Windows)
        _CMD + r'md\s',         # Windows md — anchored to avoid ".md", "--format md"
        r'\bNew-Item\b',        # PowerShell
        r'\btouch\s',           # Unix touch (must be followed by space)
    ]

    for pattern in delete_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": (
                        f"Deletion: {command[:200]}"
                    ),
                }
            }

    for pattern in create_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "ask",
                    "permissionDecisionReason": (
                        f"Creation: {command[:200]}"
                    ),
                }
            }

    return None


# =============================================================================
# Bypass-Permissions Guard (PreToolUse)
# =============================================================================

def bypass_permissions_guard() -> None:
    """
    PreToolUse guard for bypass-permissions mode (claude --dangerously-skip-permissions).

    When bypass-permissions mode is active, this guard:
    1. Allows safe commands: python x.py, git read-only, ls, cat, etc.
    2. Blocks destructive commands, git write ops, and repo boundary violations
    3. Reuses threat detection from security-gate.py

    If bypass mode is NOT active, this is a no-op (pass through).
    """
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    # Check if bypass-permissions mode is active
    permission_mode = hook_input.get("permission_mode", "")
    bypass_env = os.environ.get("CLAUDE_BYPASS_PERMISSIONS", "")

    is_bypass_mode = (
        permission_mode == "bypassPermissions" or
        bypass_env.lower() in ("true", "1", "yes")
    )

    if not is_bypass_mode:
        # Not in bypass mode, pass through
        sys.exit(0)

    # Detect profile: nightshift agents get broad dev permissions
    is_nightshift = os.environ.get("NIGHTSHIFT_AGENT", "").lower() in ("true", "1", "yes")

    # In bypass mode — validate command
    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        sys.exit(0)

    def _deny(reason: str):
        """Helper: emit deny decision and exit."""
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason
            }
        }))
        sys.exit(0)

    def _deny_tty_confirm(command_preview: str):
        """Helper: block but instruct Claude to use AskUserQuestion then retry with TTY_CONFIRMED=1 prefix."""
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"⚠️ TTY confirmation required for git write operation.\n\n"
                    f"1. Use AskUserQuestion to confirm with user: \"{command_preview[:120]}\"\n"
                    f"2. After user approves, retry with prefix: TTY_CONFIRMED=1 {command_preview[:120]}\n"
                    f"3. If user denies, do NOT retry."
                )
            }
        }))
        sys.exit(0)

    # ── Universal blocklist (both profiles) ──────────────────────────
    # Commands that are NEVER allowed in bypass mode regardless of profile
    universal_blocklist = [
        r"^rm\s+(-rf?|--recursive)\b",        # recursive delete
        r"^del\s+/[sS]",                       # Windows recursive delete
        r"^rmdir\s+/[sS]",                     # Windows recursive rmdir
        r"^format\b",                           # disk format
        r"^mkfs\b",                             # make filesystem
        r"^dd\s+",                              # raw disk write
        r"^shutdown\b",                         # system shutdown
        r"^reboot\b",                           # system reboot
        r"^reg\s+(add|delete)\b",               # Windows registry modification
        r"^sc\s+(stop|delete|config)\b",        # Windows service control
        r"^net\s+(user|localgroup)\b",          # Windows user/group modification
        r"^icacls\b",                           # Windows permissions
        r"^takeown\b",                          # Windows ownership
        r"^docker\s+(rm|rmi|system\s+prune)\b", # Docker destructive ops
        r"^docker-compose\s+down\b",            # Docker compose down
        r"^kubectl\s+delete\b",                 # Kubernetes destructive
        r"^git\s+push\s+.*--force\b",           # Force push always blocked
        r"^git\s+push\s+.*-f\b",               # Force push shorthand
        r"^git\s+clean\s+-f",                   # Git clean -f
        r"^git\s+reset\s+--hard\b",            # Git reset --hard
        r"^git\s+branch\s+-[dD]\b",            # Git branch delete
    ]

    for pattern in universal_blocklist:
        if re.search(pattern, command, re.IGNORECASE):
            _deny(f"🚫 Bypass-permissions: BLOCKED destructive command")

    # ── Branch protection (both profiles) ────────────────────────────
    # Never allow push/checkout/operations targeting main or *-dev branches
    protected_branch_patterns = [
        r"\bmain\b",
        r"\bmaster\b",
        r"\b\w+-dev(?:\s|$)",  # pulsona-dev, gswarm-dev, cwchat-dev etc. (not pulsona-dev-old)
    ]
    git_write_cmds = r"^git\s+(push|checkout|switch|merge|rebase|reset)\b"
    if re.match(git_write_cmds, command, re.IGNORECASE):
        for bp in protected_branch_patterns:
            if re.search(bp, command):
                # Exception: "git checkout -b *-night-dev" is creating a new branch, allow it
                if re.search(r"checkout\s+-b\s+\S+-night-dev", command, re.IGNORECASE):
                    break
                # Exception: "git push origin *-night-dev" is pushing to night branch, allow it
                if re.match(r"^git\s+push\b", command, re.IGNORECASE) and \
                   re.search(r"\S+-night-dev\b", command):
                    break
                _deny(f"🚫 Bypass-permissions: BLOCKED operation on protected branch (main/*-dev)")

    # ═══════════════════════════════════════════════════════════════════
    # PROFILE: Nightshift (broad dev permissions)
    # ═══════════════════════════════════════════════════════════════════
    if is_nightshift:
        # Nightshift gets broad dev tooling: pip, npm, git, python, etc.
        # Only restrictions: protected branches, other repos, Docker, system files

        # Block Docker container operations (build is OK, run/exec risky)
        if re.match(r"^docker\s+(run|exec|attach|cp)\b", command, re.IGNORECASE):
            _deny("🚫 Nightshift: Docker run/exec not allowed (use Docker in dev worktree only)")

        # Block operations outside nightshift worktree
        # Nightshift worktrees are at D:/source/{repo}/{repo}-night-dev/
        nightshift_worktree = os.environ.get("NIGHTSHIFT_WORKTREE", "")
        if nightshift_worktree:
            # Check for absolute paths in command that escape worktree
            abs_path_match = re.findall(r'[A-Za-z]:[/\\][^\s"\']+|/(?:home|usr|etc|var|tmp|opt|root|mnt|c|d)[/\\][^\s"\']*', command, re.IGNORECASE)
            for p in abs_path_match:
                try:
                    resolved = str(Path(p).resolve()).replace("\\", "/").lower()
                    wt_resolved = str(Path(nightshift_worktree).resolve()).replace("\\", "/").lower()
                    claude_home = str(_claude_home.resolve()).replace("\\", "/").lower()
                    # Allow paths within worktree or ~/.claude
                    if not (resolved.startswith(wt_resolved) or resolved.startswith(claude_home)):
                        _deny(f"🚫 Nightshift: Path outside worktree boundary: {p[:100]}")
                except (OSError, ValueError):
                    pass

        # Nightshift broad allowlist — development tooling
        nightshift_allowlist = [
            # Python ecosystem
            r"^python3?\b",                     # Any python command
            r"^pip3?\s+",                       # pip install/uninstall
            r"^uv\s+",                          # uv package manager
            r"^uvx?\s+",                        # uv tool runner
            r"^ruff\b",                         # linter
            r"^mypy\b",                         # type checker
            r"^pytest\b",                       # test runner
            r"^black\b",                        # formatter
            r"^isort\b",                        # import sorter
            r"^pylint\b",                       # linter
            r"^flake8\b",                       # linter

            # Node.js ecosystem
            r"^node\b",                         # node runtime
            r"^npm\s+",                         # npm commands
            r"^npx\s+",                         # npx runner
            r"^pnpm\s+",                        # pnpm commands
            r"^yarn\b",                         # yarn commands
            r"^tsx?\b",                         # TypeScript execution
            r"^tsc\b",                          # TypeScript compiler
            r"^vitest\b",                       # test runner
            r"^biome\b",                        # linter/formatter
            r"^eslint\b",                       # linter
            r"^prettier\b",                     # formatter
            r"^knip\b",                         # dead code finder

            # Git operations (safe writes — protected branches already checked above)
            r"^git\s+add\b",
            r"^git\s+commit\b",
            r"^git\s+push\b",                  # push (force already blocked above)
            r"^git\s+pull\b",
            r"^git\s+stash\b",
            r"^git\s+checkout\b",              # checkout (protected branches checked above)
            r"^git\s+switch\b",
            r"^git\s+merge\b",                 # merge (protected branches checked above)
            r"^git\s+rebase\b",                # rebase (protected branches checked above)
            r"^git\s+tag\b",
            r"^git\s+worktree\b",
            r"^git\s+cherry-pick\b",
            r"^git\s+config\b",                # repo-level config only
            r"^git\s+submodule\b",

            # Git read-only (always safe)
            r"^git\s+(status|log|diff|show|branch|remote|fetch|rev-parse|describe|ls-files)\b",

            # Build tools
            r"^make\b",
            r"^cmake\b",
            r"^cargo\b",                        # Rust
            r"^go\s+",                          # Go
            r"^dotnet\b",                       # .NET

            # Docker build only (run/exec blocked above)
            r"^docker\s+build\b",
            r"^docker\s+images?\b",
            r"^docker\s+tag\b",
            r"^docker\s+push\b",
            r"^docker-compose\s+build\b",
            r"^docker-compose\s+up\b",
            r"^docker\s+compose\s+(build|up|images?|ps|logs)\b",

            # File system operations (within worktree — boundary checked above)
            r"^mkdir\b",
            r"^cp\b",
            r"^mv\b",
            r"^touch\b",
            r"^chmod\b",
            r"^rm\s+(?!-r)",                   # rm single files OK, rm -r blocked above
            r"^ln\b",                           # symlinks

            # Network tools (read-only)
            r"^curl\b",
            r"^wget\b",
            r"^http\b",                         # httpie

            # Text processing / utilities
            r"^sed\b",
            r"^awk\b",
            r"^sort\b",
            r"^uniq\b",
            r"^diff\b",
            r"^patch\b",
            r"^xargs\b",
            r"^echo\b",
            r"^printf\b",
            r"^tee\b",
            r"^cut\b",
            r"^tr\b",
            r"^env\b",
            r"^export\b",
            r"^source\b",
            r"^\.\s+",                          # . (source) command
        ]

        # Also include the shared read-only allowlist
        shared_readonly = [
            r"^ls\b", r"^cat\b", r"^head\b", r"^tail\b", r"^grep\b", r"^find\b",
            r"^tree\b", r"^pwd\b", r"^which\b", r"^file\b", r"^wc\b", r"^du\b",
            r"^stat\b", r"^readlink\b", r"^realpath\b", r"^base64\b", r"^jq\b",
            r"^xxd\b", r"^od\b", r"^ps\b", r"^pgrep\b", r"^top\b", r"^htop\b",
        ]

        for pattern in nightshift_allowlist + shared_readonly:
            if re.match(pattern, command, re.IGNORECASE):
                sys.exit(0)

        # Nightshift: block unknown commands (conservative)
        _deny(f"🚫 Nightshift guard: Command not in dev allowlist\n\nCommand: {command[:200]}")

    # ═══════════════════════════════════════════════════════════════════
    # PROFILE: /x and default (restrictive — read-only + x.py)
    # ═══════════════════════════════════════════════════════════════════

    # ── TTY Confirmation: git writes require AskUserQuestion first ──
    # Flow: Claude tries git write → guard blocks with instructions →
    # Claude uses AskUserQuestion → user approves →
    # Claude retries with TTY_CONFIRMED=1 prefix → guard allows.
    #
    # Also handle "cd /path && git ..." pattern (strip cd prefix for matching).

    # Strip TTY_CONFIRMED=1 prefix if present
    tty_confirmed = False
    effective_cmd = command
    if re.match(r"^TTY_CONFIRMED=1\s+", command):
        tty_confirmed = True
        effective_cmd = re.sub(r"^TTY_CONFIRMED=1\s+", "", command)

    # Strip leading "cd ... && " prefix for matching (git commands often chained with cd)
    core_cmd = re.sub(r"^cd\s+[^\s]+\s*&&\s*", "", effective_cmd)

    # Git write commands that need TTY confirmation
    tty_confirm_patterns = [
        r"^git\s+add\b",
        r"^git\s+commit\b",
        r"^git\s+push\b",         # non-force (force already in universal blocklist)
        r"^git\s+pull\b",         # modifies working tree
        r"^git\s+rebase\b",       # modifies history
        r"^git\s+merge\b",        # modifies history
        r"^git\s+stash\b",
        r"^git\s+tag\b",
        r"^git\s+checkout\b",     # can modify working tree
        r"^git\s+switch\b",       # can modify working tree
    ]

    for pattern in tty_confirm_patterns:
        if re.match(pattern, core_cmd, re.IGNORECASE):
            if tty_confirmed:
                # User already confirmed via AskUserQuestion — allow through
                # (universal blocklist + branch protection already checked above)
                sys.exit(0)
            else:
                # Block and instruct Claude to confirm with user first
                _deny_tty_confirm(core_cmd)

    # Allowlist patterns for /x bypass mode
    x_allowlist = [
        # Python x.py commands
        r"^python\s+x\.py\b",
        r"^python\s+skills/x/scripts/x\.py\b",
        r"^python3\s+x\.py\b",
        r"^python3\s+skills/x/scripts/x\.py\b",

        # Git read-only
        r"^git\s+(status|log|diff|show|remote|fetch|rev-parse|describe|ls-files)\b",
        r"^git\s+branch\s+(?!-[dD])",          # git branch (list), not -D (delete)

        # File system read-only
        r"^ls\b", r"^cat\b", r"^head\b", r"^tail\b", r"^grep\b", r"^find\b",
        r"^tree\b", r"^pwd\b", r"^which\b", r"^file\b", r"^wc\b", r"^du\b",
        r"^stat\b", r"^readlink\b", r"^realpath\b",

        # Encoding/text processing (read-only)
        r"^base64\b", r"^jq\b", r"^xxd\b", r"^od\b",

        # Process inspection (read-only)
        r"^ps\b", r"^pgrep\b", r"^top\b", r"^htop\b",
    ]

    for pattern in x_allowlist:
        # Match against both full command and cd-stripped version
        if re.match(pattern, command, re.IGNORECASE) or re.match(pattern, core_cmd, re.IGNORECASE):
            sys.exit(0)

    # /x: block everything else
    _deny(f"🚫 Bypass-permissions guard BLOCKED: Command not in allowlist\n\nAllowed: python x.py, git read-only, ls, cat, etc.\nFor dev tooling, use NIGHTSHIFT_AGENT=1\n\nCommand: {command[:200]}")


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> None:
    """Main entry point with mode dispatch."""
    if len(sys.argv) < 2:
        # Missing args - exit gracefully to avoid hook errors
        sys.exit(0)

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
    elif mode == "insights-reminder":
        insights_reminder()
    elif mode == "ralph-enforcer":
        ralph_enforcer()
    elif mode == "ralph-agent-tracker":
        # DEPRECATED: Moved to scripts/ralph.py agent-tracker
        # Redirect to new location for backward compatibility
        import subprocess as _sp
        _ralph_script = str(_claude_home / "scripts" / "ralph.py")
        _result = _sp.run(
            [sys.executable, _ralph_script, "agent-tracker"],
            input=sys.stdin.buffer.read() if not sys.stdin.isatty() else b"",
            capture_output=True
        )
        if _result.stdout:
            sys.stdout.buffer.write(_result.stdout)
        sys.exit(_result.returncode)
    elif mode == "skill-interceptor":
        skill_interceptor()
    elif mode == "skill-validator":
        skill_validator()
    elif mode == "plan-rename-tracker":
        track_plan_rename()
    elif mode == "auto-ralph":
        auto_ralph_hook()
    elif mode == "quality-deprecation":
        quality_deprecation_hook()
    elif mode == "fs-guard":
        fs_guard()
    elif mode == "x-post-check":
        x_post_check()
    elif mode == "bypass-permissions-guard":
        bypass_permissions_guard()
    else:
        # Unknown mode - exit gracefully to avoid hook errors
        sys.exit(0)


if __name__ == "__main__":
    main()
