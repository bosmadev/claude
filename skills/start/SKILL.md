---
name: start
description: Initialize ULTRATHINK mode with Ralph auto-loop. Use when starting work on complex features, planning implementations, or when deep analysis is needed.
argument-hint: [N] [M] [task | review [rN] [rM] [task] | import <source>]
user-invocable: true
context: fork
---
# Start Workflow

**FIRST ACTION:** When this skill is invoked, immediately output: `**SKILL_STARTED:** start`

This signal MUST be emitted before any parsing, logic, or analysis begins.

## Activation

This skill activates **ULTRATHINK** mode for deep analysis and planning. When invoked, **Ralph Mode** auto-activates with parallel agents for persistent autonomous development.

## Argument Parsing (MANDATORY: ALWAYS ECHO PARSED VALUES)

**CRITICAL:** Before proceeding with any action, ALWAYS echo the parsed values back to confirm understanding:

```
Parsed arguments:
- Agents: [N]
- Iterations: [M]
- Mode: [implement|review|import|noreview]
- Post-Review Agents: [rN] (if applicable)
- Post-Review Iterations: [rM] (if applicable)
- Task: [description or "none"]
```

From `$ARGUMENTS`, parse in order:

1. **First number** (optional) = Number of agents to spawn (default: 3)
2. **Second number** (optional) = Iterations per agent (default: 3)
3. **Keywords** (optional) = `review`, `noreview`, `import`
4. **Remaining text** = Task description, path, or `git`

### Natural Language Recognition

Also recognize these natural language variations:

- "use 15 agents" / "with 15 agents" / "15 parallel agents" → agents = 15
- "10 iterations" / "run 10 times" / "iterate 10x" → iterations = 10
- "skip review" / "no review" → noreview mode
- "import from X" / "load X" → import mode

### When In Doubt

If argument parsing is ambiguous, **STOP and ask for confirmation**:

```
I parsed your command as:
- Agents: 5
- Iterations: 3
- Task: "fix the auth"

Is this correct? (yes/no)
```

### Decision Tree

```
/start                                           →  3 agents, 3 iterations, no task (DEFAULT)
/start [task]                                    →  3 agents, 3 iterations, with task
/start [N]                                       →  N agents, 3 iterations, no task
/start [N] [task]                                →  N agents, 3 iterations, with task
/start [N] [M]                                   →  N agents, M iterations, no task
/start [N] [M] [task]                            →  N agents, M iterations, with task
/start [N] [M] noreview [task]                   →  N agents, M iterations, skip post-review
/start [N] [M] review                            →  Review entire codebase (review-only mode)
/start [N] [M] review [path]                     →  Review specific path (review-only mode)
/start [N] [M] review git                        →  Review git diff files (review-only mode)
/start [N] [M] review [rN] [rM] [task]           →  N agents, M iterations, custom post-review (rN agents, rM iterations)
/start [N] [M] import <source>                   →  Import mode (PRD, YAML, GitHub, etc.)
```

### Parsing Logic

```
Parse $ARGUMENTS left-to-right:

1. If $0 is numeric → agents = $0, else agents = 3
2. If $1 is numeric → iterations = $1, else iterations = 3

3. Check keyword at $2:
   a) "noreview"  → postReviewEnabled = false, task = $3+
   b) "import"    → importMode = true, source = $3+
   c) "review"    → Check $3:
      - If $3 is numeric AND $4 is numeric:
        → postReviewAgents = $3
        → postReviewIterations = $4
        → task = $5+
        → postReviewEnabled = true (custom review config)
      - Else:
        → reviewOnlyMode = true
        → reviewScope = $3+ (path, "git", or empty for full codebase)
   d) Otherwise   → task = $2+, postReviewEnabled = true (default)

4. If no task and no special mode → interactive planning mode
```

## Plan File Format (MANDATORY)

When creating or updating a plan file, ALWAYS include the Ralph Configuration block immediately after the status line:

```markdown
# [Plan Title]

**Created:** YYYY-MM-DD
**Last Updated:** YYYY-MM-DDTHH:MM:SSZ
**Status:** Pending Approval | In Progress | Completed

**Ralph Configuration:**
- Implementation Agents: [N from parsed args]
- Implementation Iterations: [M from parsed args]
- Post-Review Agents: [rN or default 5]
- Post-Review Iterations: [rM or default 2]
- Launch Command: `/start [original command]`
```

This block MUST be present for Ralph to execute with correct parameters.

### Examples

| Command                                   | Agents | Iterations | Mode        | Post-Review       | Scope                |
| ----------------------------------------- | ------ | ---------- | ----------- | ----------------- | -------------------- |
| `/start`                                | 3      | 3          | Interactive | 5 agents, 2 iter  | No task (planning)   |
| `/start fix the APIs`                   | 3      | 3          | Implement   | 5 agents, 2 iter  | Task description     |
| `/start 5`                              | 5      | 3          | Interactive | 5 agents, 2 iter  | No task (planning)   |
| `/start 5 fix the APIs`                 | 5      | 3          | Implement   | 5 agents, 2 iter  | Task description     |
| `/start 5 10`                           | 5      | 10         | Interactive | 5 agents, 2 iter  | No task (planning)   |
| `/start 5 10 fix the APIs`              | 5      | 10         | Implement   | 5 agents, 2 iter  | Task description     |
| `/start 5 3 noreview implement auth`    | 5      | 3          | Implement   | Disabled          | Skip post-review     |
| `/start 15 5 review`                    | 15     | 5          | Review only | N/A               | Entire codebase      |
| `/start 15 5 review src/`               | 15     | 5          | Review only | N/A               | Specific path        |
| `/start 15 5 review git`                | 15     | 5          | Review only | N/A               | Git diff files       |
| `/start 5 3 review 10 2 implement auth` | 5      | 3          | Implement   | 10 agents, 2 iter | Custom review config |
| `/start 3 5 import PRD.md`              | 3      | 5          | Import      | 5 agents, 2 iter  | From PRD file        |

## Review Mode

### Review via /start Command

Review mode allows multi-agent code review without implementing changes.

**Activation:** Include `review` keyword after agent/iteration counts.

### Post-Implementation Review (Default ON)

After any `/start` implementation completes, review automatically triggers:

```
Implementation complete! Starting post-implementation review...
(5 agents, 2 iterations - use noreview flag to skip next time)

Spawning review agents...
```

**To disable:** Add `noreview` flag (no dashes):

```bash
/start 15 5 noreview implement auth   # Skip post-implementation review
/start 15 5 implement auth            # Review runs after (default)
```

### Review Agent Workflow

Each spawned review agent follows this protocol:

1. **Receive Context Reset Prompt** (see skills/review/SKILL.md)
2. **Load Assigned Scope** - Files to review
3. **Run Review Skills** (sequentially):
   - `pr-review-toolkit:type-design-analyzer`
   - `pr-review-toolkit:comment-analyzer`
   - `pr-review-toolkit:code-reviewer`
   - `pr-review-toolkit:code-simplifier`
   - `pr-review-toolkit:silent-failure-hunter`
4. **Leave TODO Comments** - Do NOT auto-fix
5. **Report Findings** - Summary to shared log (`.claude/review-agents.md`)
6. **Signal Completion** - But NOT `RALPH_COMPLETE`

### TODO Comment Format

Review agents leave comments using priority-based format:

```typescript
// TODO-P1: [critical issue] - Review agent [ID]     // Security, crashes, blocking
// TODO-P2: [important issue] - Review agent [ID]    // Bugs, performance, quality
// TODO-P3: [improvement] - Review agent [ID]        // Refactoring, docs, tests
```

**Priority mapping:**

- P1: Security vulnerabilities, crashes, blocking bugs
- P2: Performance issues, missing error handling, code quality
- P3: Refactoring, documentation, test coverage

### Git Diff Scope

When using `review git`: use `git diff --name-only HEAD` for uncommitted changes, or `gh pr diff --name-only` for PR-specific review.

### Shared Review Log

Location: `.claude/review-agents.md` - agents report findings in markdown tables. See [ralph.md](ralph.md) for format details.

---

## ULTRATHINK Activation Protocol

When `/start` is invoked, activate extended thinking mode:

### Step 1: Deep Analysis Block

Begin your response with an explicit analysis. Take at least 3000 tokens to:

1. **Restate the task** - Confirm understanding
2. **Map dependencies** - Identify affected files, modules, interfaces
3. **List assumptions** - Make explicit what you're assuming
4. **Consider 3-5 options** for each design decision using this template:

| Option   | Pros                   | Cons                   | Use Case    | Recommendation |
| -------- | ---------------------- | ---------------------- | ----------- | -------------- |
| Option 1 | - Pro A`<br>`- Pro B | - Con A`<br>`- Con B | When to use | Priority rank  |
| Option 2 | - Pro A`<br>`- Pro B | - Con A`<br>`- Con B | When to use | Priority rank  |

### Step 2: Generate Implementation Plan Artifact

Create a structured plan with: Overview, Dependencies, Steps (actionable verbs), Verification, Rollback Plan.

### Step 3: Safety Check

Before implementing, verify:

- No deprecated patterns being used
- No breaking changes to public APIs
- No removal of features without migration path
- No security vulnerabilities introduced
- No performance regressions

### Analysis Dimensions

Analyze every change through these lenses:

| Dimension                 | Key Questions                                                      |
| ------------------------- | ------------------------------------------------------------------ |
| **Technical**       | Rendering performance, state complexity, bundle size, memory usage |
| **Accessibility**   | WCAG AAA, screen reader support, keyboard nav, color contrast 7:1  |
| **Scalability**     | Long-term maintenance, modularity, team scalability                |
| **User Experience** | Cognitive load, feedback clarity, learning curve                   |

---

## Core Rules (CRITICAL)

- **Artifacts First:** NEVER start coding without generating an Implementation Plan Artifact
- **Build Integrity:** Run `pnpm validate` before confirming completion, resolving ALL warnings/errors
- **Browser Verify:** Use browser automation to visually verify UI changes
- **Root Cause:** NEVER apply band-aid fixes (`@ts-ignore`, `any`, `unknown`). Fix upstream interfaces
- **Knip/Biome:** Scan for unused imports, dead variables, unreachable exports - remove immediately
- **Question:** Always ask questions and provide detailed explanations with recommendations

## Anti-Hallucination Standard

**Priority Order:** Accuracy > Determinism > Completeness > Speed

All work MUST follow these four phases:

### 1. ANALYSIS Phase

- Restate the task in your own words
- List all known facts and constraints
- Identify unknowns that need clarification

### 2. ASSUMPTIONS CHECK Phase

- Explicitly list every assumption being made
- **STOP** and ask user if any assumption is unclear or risky
- Never proceed with uncertain inputs

### 3. BUILD Phase

- Execute ONLY with confirmed inputs
- Reference specific code/docs for every decision
- No invented APIs, paths, or configurations

### 4. SELF-VERIFICATION Phase

- Review output for any invented content
- Confirm all references exist in codebase
- Verify no hallucinated function names, paths, or behaviors

## MCP Availability for Agents

Spawned agents have access to: `context7` (docs), `serena` (semantic code analysis).

For web research, see CLAUDE.md "Web Research Fallback Chain" - agents MUST use the full browser fallback chain, not just WebFetch.

---

## Task Management

Use TaskCreate/TaskUpdate/TaskList for structured work:

```
TaskCreate({
  subject: "Implement feature X",
  description: "Details...",
  activeForm: "Implementing feature X"
})
```

- Mark `in_progress` when starting work
- Mark `completed` immediately when done
- ONE `in_progress` at a time
- On "resume"/"continue", check task list for next step

## Trigger Modes

### YOLO Mode

**Trigger:** "YOLO", "Fix it", "Debug", Build Errors

- Assume consent - execute the fix
- Aggressive refactor upstream interfaces
- Self-correct Biome errors before output

### PLAN Mode

**Trigger:** "PLAN"

- READ-ONLY: No file edits, modifications, or system changes
- End with clarifying question OR readiness to proceed

## Commit Tracking

Changes are automatically tracked during RALPH sessions via the change-tracker hook.

**Location:** `{repo-root}/.claude/commit.md`

**How it works:**

1. Hook detects file modifications during session
2. Automatically logs to `.claude/commit.md` with timestamps
3. When ready to commit, run `/commit` to generate `pending-commit.md`
4. Review and run `/commit confirm` to finalize

**Manual tracking (if needed):**

```
/commit log <file> <action> <description>
/commit show
```

## Browser Verification

See CLAUDE.md "Web Research Fallback Chain" for browser selection.

For Ralph agents: use round-robin browser allocation across ports 9222-9225. Cross-check workflow: verify on Browser A, confirm on Browser B.

## Infrastructure

### Hooks

Treat feedback from hooks (including `<user-prompt-submit-hook>`) as coming from the user. If blocked by a hook, adjust actions or ask user to check configuration.

### Artifact Context

- Path: `<appDataDir>/brain/<conversation-id>/`
- Key files: `implementation_plan.md`, `task.md`, `walkthrough.md`
- On "resume"/"continue": check `task.md` for next incomplete step

### Progress Updates

For longer tasks, provide updates at reasonable intervals:

- Concise (8-10 words max)
- Example: "Fixed 3 of 10 type errors. Moving to API layer next."

### Code References

Use `file_path:line_number` format: `src/services/process.ts:712`

## Behavioral Rules

- **Verbosity:** Match response length to query complexity. Default to MINIMAL. Expand for ULTRATHINK mode.
- **Proactiveness:** Execute clear requests, take obvious follow-ups. Don't surprise with unexpected changes.
- **Objectivity:** Technical accuracy over validation. Disagree when necessary.

## Output Format

- Use `##` for top-level, `###` for subsections
- Use 4 backticks for code containing 3-backtick fences
- Add `// filepath: /path/to/file` for file edits
- Use `-` for bullets (4-6 max per list)
- Structure: Actions -> Artifacts -> How to Run -> Notes

## Python 3.14+

- **Package Manager:** `uv` ONLY (`uv add`, `uv sync`). PROHIBIT `pip install` or `poetry`
- **Typing (PEP 695):** `type UserID = int`, `list[str]` (not `List[str]`)
- **Pydantic v2:** `model_config = ConfigDict(...)`, `model_validate()` / `model_dump()`

## Auto Accept Mode

When spawning agents, check for auto-accept: `CLAUDE_AUTO_ACCEPT=true` env var OR `.claude/ralph/state.json` → `autoAccept: true`. If enabled, set `mode: "acceptEdits"` for Task agents.

---

## Environment Variables

| Variable                     | Purpose               | Default      |
| ---------------------------- | --------------------- | ------------ |
| `CLAUDE_CODE_TASK_LIST_ID` | Shared task list name | Project name |
| `CLAUDE_AUTO_ACCEPT`       | Auto-accept edits     | `false`    |

See [ralph.md](ralph.md) for task list setup and state file details.

## State Persistence

See [ralph.md](ralph.md) for state file formats (all in `.claude/ralph/` directory).

---

## Plan Change Tracking

See CLAUDE.md "Plan Files (MANDATORY)" for change marker rules (🟧 emoji at END of lines).

## Emoji Plan Output Format (MANDATORY)

All plan tables and sections MUST use emoji-prefixed headers for visual scanning:

**Section headers:** Add category emoji before title.

```markdown
## 🔒 Security Considerations
## ⚡ Performance Impact
## 🏗️ Architecture Changes
## 📝 Documentation Updates
## 🧪 Test Coverage
## 🎨 UI/UX Changes
```

**Table headers:** Add status emoji in relevant cells.

```markdown
| # | ✅ Feature | ⚠️ Risk | 📋 Status |
|---|-----------|---------|----------|
| 1 | Auth flow | 🔴 High | ✅ Done  |
| 2 | API cache | 🟡 Med  | ⏳ WIP   |
```

**Decision tables:** Each row gets a leading emoji for visual scanning.
**Comparison matrices:** Use emoji columns for at-a-glance status.
**Priority items:** 🔴 Critical, 🟡 Medium, 🟢 Low.

---

## Sub-File References

For detailed documentation on specific topics:

- **[ralph.md](ralph.md)** - Ralph Mode initialization, work loop, completion criteria, stuck detection, review agents, plan guardian
- **[import.md](import.md)** - Import tasks from PRD files, YAML, GitHub Issues, or PR descriptions

## Ralph Orchestrator Invocation (MANDATORY)

After parsing arguments and creating/validating the plan, you MUST invoke the Ralph orchestrator script with all dynamic parameters:

```bash
python C:/Users/Dennis/.claude/scripts/ralph.py loop [AGENTS] [ITERATIONS] \
    --review-agents [REVIEW_AGENTS] \
    --review-iterations [REVIEW_ITERATIONS] \
    [--skip-review] \
    [--plan PLAN_FILE] \
    [--backend task|subprocess|auto] \
    "[TASK_DESCRIPTION]"
```

### Parameter Mapping

| Parsed Value                          | CLI Argument                  |
| ------------------------------------- | ----------------------------- |
| `agents` (default: 3)               | First positional arg          |
| `iterations` (default: 3)           | Second positional arg         |
| `postReviewAgents` (default: 5)     | `--review-agents`           |
| `postReviewIterations` (default: 2) | `--review-iterations`       |
| `postReviewEnabled = false`         | `--skip-review`             |
| Plan file path                        | `--plan`                    |
| Backend mode                          | `--backend` (default: auto) |
| Task description                      | Final quoted argument         |

### Spawn Backend (Hybrid Architecture)

| Backend        | Behavior                                            | UI Visibility                          |
| -------------- | --------------------------------------------------- | -------------------------------------- |
| `task`       | All agents via Claude Task tool                     | ✅ Cyan "x local agents" in statusline |
| `subprocess` | All agents via `claude --print` subprocess        | ❌ Invisible processes                 |
| `auto`       | Task for ≤10 agents, batched with overflow for >10 | ✅ Partial visibility                  |

**Default:** `auto` — gives Task tool UI visibility for most workloads.

When using `task` backend, agents appear in Claude Code's `/tasks` dropdown with real-time status. Each Task tool agent gets its own 200k context window with full MCP access (Serena, Context7).

### Setup / Teardown (Hybrid Architecture)

For advanced control, use `setup` + manual Task spawning + `teardown`:

```bash
# 1. Initialize session infrastructure (state, team, inboxes)
python C:/Users/Dennis/.claude/scripts/ralph.py setup 10 3 --backend task "My task"

# 2. Spawn agents manually via Task tool (gives UI visibility)
#    Each agent reads team config from .claude/ralph/team-{session}/config.json

# 3. Clean up after completion
python C:/Users/Dennis/.claude/scripts/ralph.py teardown
```

### Example Invocations

```bash
# /start → defaults (auto backend)
python C:/Users/Dennis/.claude/scripts/ralph.py loop 3 3 --review-agents 5 --review-iterations 2

# /start 50 15 review 15 10 implement auth
python C:/Users/Dennis/.claude/scripts/ralph.py loop 50 15 \
    --review-agents 15 --review-iterations 10 \
    --plan /path/to/plan.md \
    "implement auth"

# /start 10 5 noreview quick fix (Task backend for UI visibility)
python C:/Users/Dennis/.claude/scripts/ralph.py loop 10 5 --skip-review --backend task "quick fix"

# Force subprocess backend (legacy behavior)
python C:/Users/Dennis/.claude/scripts/ralph.py loop 15 5 --backend subprocess "Use subprocess"
```

### Execution Flow

1. Parse `$ARGUMENTS` per Decision Tree
2. Echo parsed values for confirmation
3. If task provided: Create/update plan file with Ralph Configuration block
4. Invoke `ralph.py loop` with ALL dynamic parameters (including `--backend`)
5. Ralph orchestrator initializes team infrastructure (inboxes, heartbeat, relay)
6. Agents spawned in batches (≤10 per batch for >10 agents)
7. Agents load role configs from `~/.claude\agents\` via round-robin
8. Inter-agent coordination via file-based inbox system (Hybrid Gamma)
9. Wait for `RALPH_COMPLETE` + `EXIT_SIGNAL`
10. Report completion summary

**CRITICAL:** Do NOT spawn agents manually via Task tool. Let ralph.py handle orchestration - it manages:

- Parallel agent spawning with batching (>10 agents)
- Agent config assignment (19 configs in ~/.claude `\agents\ `)
- Inter-agent inboxes and heartbeat monitoring
- Task reclamation (crashed agent's work re-assigned)
- Iteration tracking and stuck detection
- Post-review phase
- Completion signals and structured shutdown

## Related Skills

- **`/commit`** - Create commits from `.claude/commit.md` with branch-aware naming
- **`/commit log`** - Manually log file changes (auto-tracked by hooks)
- **`/screen`** - Capture screenshots for visual verification
- **`/code-standards`** - Run Biome, Knip, accessibility, and architecture checks
