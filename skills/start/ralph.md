# Ralph Mode

Ralph Mode is an autonomous development loop that spawns parallel agents for persistent task completion. It activates automatically with the `/start` command.

## Activation

**Trigger:** `/start` with or without arguments - Ralph Mode is the default behavior.

**Syntax:**
```
/start                              →  3 agents, 3 iterations each (DEFAULT)
/start [task]                       →  3 agents, 3 iterations each
/start [agents] [task]              →  N agents, 3 iterations each
/start [agents] [iterations] [task] →  N agents, M iterations each
```

**Examples:**

| Command | Agents | Iterations/Agent | Total Max |
|---------|--------|------------------|-----------|
| `/start` | 3 | 3 | 9 |
| `/start fix the APIs` | 3 | 3 | 9 |
| `/start 5 fix the APIs` | 5 | 3 | 15 |
| `/start 5 10 fix the APIs` | 5 | 10 | 50 |
| `/start 3 50 build auth` | 3 | 50 | 150 |

## Initialization Sequence (MANDATORY)

When Ralph Mode activates, execute these steps IN ORDER:

### Step 1: Create Task Structure with TaskCreate

IMMEDIATELY use TaskCreate to create a structured task hierarchy with dynamic agent assignment:

**IMPL Tasks (Implementation):**
Create N implementation tasks based on the agent count from `/start N`:

```
TaskCreate({
  subject: "IMPL-1: [Primary implementation path]",
  description: "[Detailed description of implementation work]",
  activeForm: "Implementing [feature]"
})

TaskCreate({
  subject: "IMPL-2: [Edge cases and validation]",
  description: "[Detailed description of edge case handling]",
  activeForm: "Handling edge cases"
})

TaskCreate({
  subject: "IMPL-3: [Alternative approaches/cleanup]",
  description: "[Detailed description of alternatives]",
  activeForm: "Exploring alternatives"
})
```

For `/start 5 [task]`, create 5 IMPL tasks (IMPL-1 through IMPL-5).

**VERIFY Tasks (Blocked by IMPL):**
Create verification tasks that depend on implementation:

```
TaskCreate({
  subject: "VERIFY-1: Run pnpm validate",
  description: "Execute pnpm validate and ensure exit code 0 with no errors",
  activeForm: "Running validation"
})
→ Then use TaskUpdate to set: addBlockedBy: ["IMPL-1", "IMPL-2", "IMPL-3"]

TaskCreate({
  subject: "VERIFY-2: TypeScript check (pnpm tsc)",
  description: "Verify no TypeScript errors remain",
  activeForm: "Checking TypeScript"
})
→ Then use TaskUpdate to set: addBlockedBy: ["IMPL-1", "IMPL-2", "IMPL-3"]

TaskCreate({
  subject: "VERIFY-3: Build verification (pnpm build)",
  description: "Ensure build completes successfully",
  activeForm: "Building project"
})
→ Then use TaskUpdate to set: addBlockedBy: ["IMPL-1", "IMPL-2", "IMPL-3"]

TaskCreate({
  subject: "VERIFY-4: Visual verification (/screen)",
  description: "For UI changes: capture screenshot with /screen, verify visual correctness",
  activeForm: "Capturing visual verification"
})
→ Then use TaskUpdate to set: addBlockedBy: ["VERIFY-3"]
```

**Note:** VERIFY-4 is only required for UI/frontend changes. Skip for backend-only work.

**FINAL Task (Blocked by all VERIFY):**

```
TaskCreate({
  subject: "FINAL: Self-verify and signal completion",
  description: "Verify all criteria met, output completion signals",
  activeForm: "Finalizing completion"
})
→ Then use TaskUpdate to set: addBlockedBy: ["VERIFY-1", "VERIFY-2", "VERIFY-3"]
```

### Step 2: Set Up Shared Task List (MANDATORY)

**Task List Persistence:** Ralph uses `CLAUDE_CODE_TASK_LIST_ID` to share tasks across agents and iterations.

The task list ID is derived from the project directory:
```bash
# Format: project-name (from git repo or directory name)
CLAUDE_CODE_TASK_LIST_ID="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")"
export CLAUDE_CODE_TASK_LIST_ID
```

**Where tasks are stored:** `%USERPROFILE%\.claude\tasks\${CLAUDE_CODE_TASK_LIST_ID}\`

This enables:
- All agents share the same task list
- Tasks persist across iterations
- Progress survives context compaction
- Resume capability after session restart

### Step 3: Create Ralph State Files

Execute via Bash to initialize loop state (replace placeholders with actual values):

```bash
mkdir -p .claude/ralph && cat > .claude/ralph/loop.local.md <<'RALPH_EOF'
---
active: true
iteration: 1
max_iterations: [ITERATIONS]
completion_promise: "RALPH_COMPLETE"
agents: [AGENTS]
taskListId: "[CLAUDE_CODE_TASK_LIST_ID]"
---

[TASK_DESCRIPTION]
RALPH_EOF
```

```bash
cat > .claude/ralph/state.json <<'STATE_EOF'
{
  "iteration": 1,
  "maxIterations": [ITERATIONS],
  "agents": [AGENTS],
  "startedAt": "[ISO_TIMESTAMP]",
  "task": "[TASK_DESCRIPTION]",
  "taskListId": "[CLAUDE_CODE_TASK_LIST_ID]",
  "stuckDetection": {
    "consecutiveErrors": [],
    "lastCompletedTask": null,
    "iterationsSinceProgress": 0,
    "buildErrors": []
  },
  "activityLog": []
}
STATE_EOF
```

### Step 4: Create Native Team and Spawn Agents

**CRITICAL:** Use native Agent Teams (TeamCreate + Task with team_name) for agent spawning. Do NOT use ralph.py subprocess spawning.

#### 4a. Initialize Ralph State (utility only)

```bash
python C:/Users/Dennis/.claude/scripts/ralph.py setup [AGENTS] [ITERATIONS] \
    --review-agents [REVIEW_AGENTS] \
    --review-iterations [REVIEW_ITERATIONS] \
    [--skip-review] \
    [--plan PLAN_FILE] \
    "[TASK_DESCRIPTION]"
```

This creates state files only (`.claude/ralph/state.json`, `.claude/ralph/loop.local.md`). It does NOT spawn agents.

#### 4b. Create Native Team

```python
TeamCreate(
    team_name="ralph-impl",
    description="Ralph implementation team for: [TASK_DESCRIPTION]"
)
```

#### 4c. Create Tasks for Work Items

Use TaskCreate for each work unit (IMPL tasks, VERIFY tasks, FINAL task — as defined in Step 1).

#### 4d. Spawn Agents as Teammates

Spawn ALL agents in PARALLEL in a SINGLE message with multiple Task() calls. Each agent MUST include `team_name`:

```python
Task(
    subagent_type="general-purpose",
    model="opus",  # or "sonnet" based on modelMode
    team_name="ralph-impl",  # REQUIRED: joins the native team
    name="agent-1",  # Unique teammate name
    prompt="""RALPH Agent 1/[N] - Phase 2.1: Implementation

**Plan file:** [PLAN_FILE_PATH]

**Your task:** [SPECIFIC_TASK]

**Ralph protocol:**
- Read plan file for context
- Check TaskList for available work
- Claim tasks with TaskUpdate(owner="agent-1")
- Use SendMessage to report progress to team lead
- Mark tasks completed when done
- When you receive a shutdown_request message (JSON with type "shutdown_request"), you MUST respond by calling SendMessage with type="shutdown_response", request_id=(from the message), approve=true. This terminates your process gracefully. Do NOT just say "I can't exit" — use the tool.

**Success criteria:**
[WHAT_DEFINES_COMPLETION]

When complete, output: ULTRATHINK_COMPLETE
"""
)
```

#### 4e. Orchestration via SendMessage

As team lead, monitor agent progress:
- Agents send status updates via `SendMessage(type="message", recipient="team-lead")`
- Use `TaskList` to track overall progress
- Use `SendMessage(type="message", recipient="agent-X")` to redirect stuck agents
- When all IMPL tasks complete, spawn VERIFY+FIX agents
- When VERIFY+FIX completes, run PLAN VERIFICATION (checks plan + artifacts)
- If plan verification finds gaps: read `.claude/ralph/gap-fill-prompts.json` and spawn gap-fill agents
- When plan verification passes, spawn review agents (if enabled)
- Send `SendMessage(type="shutdown_request")` to each agent when done

#### 4f. Teardown

After all agents complete:

```bash
python C:/Users/Dennis/.claude/scripts/ralph.py teardown
```

Then clean up the team:

```python
TeamDelete()
```

**Agent coordination features (native teams provide):**
- Shared TaskList visible to all teammates
- Direct messaging between agents via SendMessage
- Automatic idle notifications when agents stop
- Team agent visibility in statusline
- Native team context in agent prompts

## Completion Criteria (ALL must be TRUE)

Before signaling completion, verify:

1. **All TaskCreate items completed** - Use TaskList to verify every task has `status: "completed"`
2. **pnpm validate passes** - Exit code 0, no errors
3. **pnpm tsc clean** - No TypeScript errors
4. **pnpm build succeeds** - Build completes successfully
5. **Visual verification** (UI changes only) - Screenshot captured and verified with `/screen`
6. **Self-verification confident** - You are 200% sure all is correct

**Anti-Hallucination Check (before completion):**
- Review all outputs for invented content
- Confirm all file paths and function names exist
- Verify no hallucinated APIs or configurations

**COMPLETION PROTOCOL (Multi-Signal Exit)**

Output BOTH of these when ALL conditions are met:

```
<promise>RALPH_COMPLETE</promise>
EXIT_SIGNAL: true
```

**IMPORTANT:** The promise ALONE will NOT trigger loop exit. You MUST include `EXIT_SIGNAL: true` to confirm completion. This prevents premature exits when heuristics detect completion patterns but work is still in progress.

## Work Iteration Protocol

Each iteration using TaskList/TaskUpdate:

1. Read `.claude/ralph/state.json` for context
2. Call `TaskList` to see all tasks and their status
3. Find next task with `status: "pending"` and empty `blockedBy`
4. Use `TaskUpdate` to mark it `status: "in_progress"`
5. Work on that ONE task
6. Run relevant validation (`pnpm tsc`, `pnpm check:fix`, etc.)
7. If success: Use `TaskUpdate` to mark `status: "completed"`, move to next
8. If failure: Log error, attempt fix
9. When all tasks complete: Run full `pnpm validate`
10. If validate passes: Output BOTH:
    ```
    <promise>RALPH_COMPLETE</promise>
    EXIT_SIGNAL: true
    ```

## Stuck Detection

The team lead (you) detects these patterns and pauses for user input:

| Pattern | Threshold | Action |
|---------|-----------|--------|
| Same error repeated | 3 times | Pause, prompt user |
| No task progress | 5 iterations | Pause, prompt user |
| Build fails same way | 3 times | Pause, prompt user |
| Circular dependency | Detected | Pause, prompt user |
| All tasks blocked | No available work | Pause, prompt user |

**Detection Mechanisms:**
- Track `consecutiveErrors[]` in ralph-state.json
- Monitor `iterationsSinceProgress` counter
- Compare `buildErrors[]` for repetition
- Check TaskList for tasks stuck in `blockedBy` state

When stuck:
- Loop PAUSES (not exits)
- User receives notification
- User provides guidance OR types "abort"
- Loop resumes with guidance

## Abort Instructions

To cancel an active Ralph loop:

**Option 1: Chat Command**
- Type "abort ralph" in response

**Option 2: File Deletion**
- Delete `.claude/ralph/loop.local.md`

**Option 3: Force Stop**
- Use Ctrl+C in terminal

**Post-Abort Cleanup:**
1. Any in-progress tasks remain in their current state
2. State files can be manually removed: `rm -rf .claude/ralph/`
3. TaskList will show partial progress for potential resume

---

# Review Agent Protocol

## Context Reset Template

When spawning review agents, use this context reset prompt:

```
# CONTEXT RESET - FRESH REVIEW AGENT

You are a **fresh code reviewer** starting with a clean slate.

## Critical Instructions

1. **DISCARD ASSUMPTIONS** - Do not assume anything from previous agents
2. **INDEPENDENT ANALYSIS** - Form your own opinions about the code
3. **NO AUTO-FIXES** - Leave TODO comments only, do NOT implement fixes
4. **FRESH PERSPECTIVE** - Review as if seeing this code for the first time
5. **SHUTDOWN** - When you receive a shutdown_request (JSON with type "shutdown_request"), call SendMessage with type="shutdown_response", request_id=(from the message), approve=true. Do NOT say "I can't exit" — use the SendMessage tool.
```

## Grand Plan Context Loading

Before reviewing assigned files, load the repository's grand plan:

1. **Read CLAUDE.md** (if exists at repo root)
2. **Read README.md** (if exists)
3. **Scan directory structure** - `find . -type d -maxdepth 3 | head -50`
4. **Check for architecture docs**

## Review Tools

Each agent runs these analysis tools:

1. **Type Design Analysis** - Check type invariants and encapsulation
2. **Comment Accuracy Check** - Verify comments match code behavior
3. **Code Style Review** - Check adherence to project guidelines
4. **Complexity Analysis** - Identify overly complex code
5. **Silent Failure Detection** - Find swallowed errors

## TODO Comment Format

For each issue found, add a comment using priority-based format:

```
// TODO-P1: {description} - Review agent {your_id}   // Critical: security, crashes
// TODO-P2: {description} - Review agent {your_id}   // High: bugs, performance
// TODO-P3: {description} - Review agent {your_id}   // Medium: refactoring, docs
```

### Priority Mapping

| Finding Type | Priority |
|--------------|----------|
| Security vulnerabilities, crashes | P1 |
| Bugs, logic errors, performance | P2 |
| Code smells, refactoring, docs, tests | P3 |

## Report to Shared Log

After reviewing, report to `.claude/review-agents.md`:

```markdown
## Agent {your_id} - Iteration {N}

| File | Line | Priority | Comment |
|------|------|----------|---------|
| src/components/Button.tsx | 42 | P2 | Missing null check |

**Files reviewed:** {count}
**TODOs added:** {count}
```

## Completion Signal

When finished reviewing all assigned files:

```
AGENT_COMPLETE: true
Agent ID: {your_id}
Findings: {N} TODOs added
Files reviewed: {count}
```

This does **NOT** trigger loop exit. Only the orchestrator can signal `RALPH_COMPLETE`.

---

# Plan Guardian Integration

Plan Guardian is a background monitoring system that detects drift from the implementation plan during Ralph sessions.

## Overview

When `/start` spawns agents, Plan Guardian:

1. **Activates** automatically when plan is approved
2. **Generates** a plan digest (`.claude/ralph/guardian/digest.json`) from the implementation plan
3. **Monitors** agent work via hooks, sampling every N actions
4. **Injects** warnings to agents when drift is detected

## Activation Flow

```
/start 30 10
         ↓
Plan Mode → Implementation Plan created
         ↓
User approves plan
         ↓
PLAN GUARDIAN ACTIVATES
         ↓
Generate plan-digest.json
         ↓
30 implementation agents spawn
         ↓
Guardian samples work (every 5 actions)
         ↓
If drift detected → inject warning
         ↓
Implementation complete → Verify+Fix agents
         ↓
Verify+Fix complete → Review agents
         ↓
RALPH_COMPLETE
```

## Plan Digest Structure

The digest is auto-generated from the approved implementation plan:

```json
{
  "version": "1.0",
  "source_documents": ["plans/example-plan.md"],
  "core_problem": {
    "statement": "Description of the problem being solved",
    "not_solving": ["Out-of-scope items"]
  },
  "boundaries": {
    "must_have": ["Required features/fixes"],
    "must_not_have": ["Forbidden changes"],
    "constraints": ["Technical constraints"]
  },
  "scope_markers": {
    "in_scope": ["Files/features in scope"],
    "out_of_scope": ["Explicitly excluded items"],
    "scope_creep_indicators": ["Patterns that suggest drift"]
  }
}
```

## Guardian Configuration

Located at `.claude/ralph/guardian/config.json`:

```json
{
  "enabled": true,
  "sampling_rate": {
    "default": 5,
    "phase_overrides": {
      "implementation": 3,
      "review": 10
    }
  },
  "sensitivity": "normal",
  "thresholds": {
    "notice": 0.8,
    "warn": 0.6,
    "drift": 0.4,
    "halt": 0.2
  }
}
```

## Drift Detection Indicators

1. **File outside scope** - Agent modifying files not in plan
2. **Feature creep** - Adding functionality not requested
3. **Constraint violation** - Breaking explicit constraints
4. **Pattern match** - Actions matching `scope_creep_indicators`

## Warning Injection

When drift detected, Guardian injects a warning:

```
⚠️ PLAN GUARDIAN WARNING

Detected potential drift from implementation plan.
Score: 0.55 (threshold: 0.6)

Concern: Modifying src/utils/newFeature.ts not in plan scope

Action: Please verify this change aligns with the plan:
- Review plans/example-plan.md
- If intentional, acknowledge with "Guardian: Acknowledged"
- If unintended, revert and refocus on plan tasks

Plan boundaries:
- In scope: Issues 2-6 from plan
- Out of scope: New plugin development
```

## Disabling Plan Guardian

To disable for a session:

```bash
# In ralph-state.json
{
  "guardianEnabled": false
}
```

Or set environment variable:

```bash
RALPH_GUARDIAN_DISABLED=true claude
```

## Related Files

- `scripts/guards.py` - PostToolUse hook for sampling (guardian and plan-write-check modes)
- `.claude/ralph/guardian/digest.json` - Auto-generated plan digest
- `.claude/ralph/guardian/config.json` - Guardian configuration
- `.claude/ralph/guardian/log.json` - Warning history
