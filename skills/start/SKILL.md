---
name: start
description: "ULTRATHINK mode with Ralph auto-loop. Default: 3 agents, 3 iterations, Opus."
argument-hint: "[N] [M] [opus|sonnet|sonnet all] [task | noreview | review [rN] [rM] | import <source> | help]"
user-invocable: true
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
- Model: [opus|sonnet] (plan phase / impl phase)
- Mode: [implement|review|import|noreview]
- Post-Review Agents: [rN] (if applicable)
- Post-Review Iterations: [rM] (if applicable)
- Task: [description or "none"]
```

From `$ARGUMENTS`, parse in order:

1. **First number** (optional) = Number of agents to spawn (default: 3)
2. **Second number** (optional) = Iterations per agent (default: 3)
3. **Model keyword** (optional) = `sonnet` or `sonnet all` (see Model Routing below)
4. **Keywords** (optional) = `review`, `noreview`, `import`
5. **Remaining text** = Task description, path, or `git`

### Model Routing (Sonnet-for-Planning / Opus-for-Execution)

| Command | Plan Phase | Impl Phase | TTY Confirmation |
|---------|-----------|-----------|-----------------|
| `/start` | Opus 4.5 | Opus 4.5 | `⚡ All phases: Opus 4.5` |
| `/start sonnet` | Sonnet 4.5 | Opus 4.5 (auto-switch) | `📝 Planning: Sonnet 4.5` → approve → `⚡ Switching to Opus 4.5` |
| `/start sonnet all` | Sonnet 4.5 | Sonnet 4.5 | `💰 Budget mode: Sonnet 4.5 (all phases)` |

**Implementation:** When `sonnet` keyword detected:
- Plan-phase agents: `Task(model="sonnet", ...)`
- After plan approval (ExitPlanMode), output model switch confirmation
- Impl-phase agents: `Task(model="opus", ...)` (unless `sonnet all`)

When `sonnet all` detected:
- ALL agents use `Task(model="sonnet", ...)`

When no model keyword (default):
- ALL agents use `Task(model="opus", ...)`

### Natural Language Recognition

Also recognize these natural language variations:

- "use 15 agents" / "with 15 agents" / "15 parallel agents" → agents = 15
- "10 iterations" / "run 10 times" / "iterate 10x" → iterations = 10
- "skip review" / "no review" → noreview mode
- "import from X" / "load X" → import mode
- "use sonnet" / "budget mode" / "cheap mode" → sonnet all

### When In Doubt

If argument parsing is ambiguous, **STOP and ask for confirmation**:

```
I parsed your command as:
- Agents: 5
- Iterations: 3
- Task: "fix the auth"

Is this correct? (yes/no)
```

### Validation Rules

**Agent count (N):**
- Minimum: 1
- Maximum: 30 (hard cap to prevent resource exhaustion)
- Default: 3

**Iteration count (M):**
- Minimum: 1
- Maximum: 100 (hard cap to prevent infinite loops)
- Default: 3

If user requests values outside these bounds, cap at the limit and warn:
```
Warning: Requested 50 agents, capped at 30 (maximum)
Warning: Requested 200 iterations, capped at 100 (maximum)
```

### Decision Tree

```
/start                                           →  3 agents, 3 iterations, Opus, no task (DEFAULT)
/start [task]                                    →  3 agents, 3 iterations, Opus, with task
/start [N]                                       →  N agents, 3 iterations, no task
/start [N] [M]                                   →  N agents, M iterations, no task
/start [N] [M] [task]                            →  N agents, M iterations, with task
/start sonnet [task]                             →  Sonnet plan → Opus impl, with task
/start sonnet all [task]                         →  Sonnet ALL phases, with task
/start [N] [M] sonnet [task]                     →  N agents, M iter, Sonnet plan → Opus impl
/start [N] [M] sonnet all [task]                 →  N agents, M iter, Sonnet ALL phases
/start [N] [M] noreview [task]                   →  N agents, M iterations, skip post-review
/start [N] [M] review                            →  Review entire codebase (review-only mode)
/start [N] [M] review [path]                     →  Review specific path (review-only mode)
/start [N] [M] review git                        →  Review git diff files (review-only mode)
/start [N] [M] review [rN] [rM] [task]           →  N agents, M iterations, custom post-review
/start [N] [M] import <source>                   →  Import mode (PRD, YAML, GitHub, etc.)
```

### Parsing Logic

```
Parse $ARGUMENTS left-to-right:

1. If $0 is numeric → agents = $0, else agents = 3
2. If $1 is numeric → iterations = $1, else iterations = 3

3. Check for model keyword at current position:
   a) "sonnet" followed by "all" → modelMode = "sonnet_all", advance 2 positions
   b) "sonnet"                   → modelMode = "sonnet", advance 1 position
   c) Otherwise                  → modelMode = "opus" (default, no advance)

4. Check keyword at current position:
   a) "noreview"  → postReviewEnabled = false, task = remaining
   b) "import"    → importMode = true, source = remaining
   c) "review"    → Check next:
      - If next is numeric AND next+1 is numeric:
        → postReviewAgents = next
        → postReviewIterations = next+1
        → task = remaining
        → postReviewEnabled = true (custom review config)
      - Else:
        → reviewOnlyMode = true
        → reviewScope = remaining (path, "git", or empty for full codebase)
   d) Otherwise   → task = remaining, postReviewEnabled = true (default)

5. If no task and no special mode → interactive planning mode

Model routing based on modelMode:
- "opus"       → All agents: model="opus"
- "sonnet"     → Plan agents: model="sonnet", Impl agents: model="opus"
- "sonnet_all" → All agents: model="sonnet"
```

### Task Ambiguity Detection & Agent Count Recommendations

After parsing the task, analyze it for ambiguity and complexity to determine:
1. Whether to trigger AskUserQuestion for clarification
2. Whether to offer fewer agents for simple tasks

**Ambiguity Score Calculation:**

| Pattern                             | Score | Clarification Needed | Agent Count Offer |
| ----------------------------------- | ----- | -------------------- | ----------------- |
| "implement" + no specific tech      | HIGH  | ✅ ASK (pre-research) | 10 (default)      |
| "add feature" + multiple components | HIGH  | ✅ ASK (pre-research) | 10 (default)      |
| "refactor" + >5 files impacted      | HIGH  | ✅ ASK (pre-research) | 10 (default)      |
| "fix" + single file + clear error   | LOW   | ❌ SKIP               | Offer 2 or 5      |
| "typo", "rename", "docs"            | LOW   | ❌ SKIP               | Offer 2           |

**Detection Keywords:**

```python
HIGH_AMBIGUITY_PATTERNS = [
    ("implement", "without_tech_stack"),      # e.g., "implement auth" (no JWT/OAuth mentioned)
    ("add feature", "multiple_components"),   # e.g., "add user dashboard"
    ("refactor", "many_files"),               # e.g., "refactor API layer" (>5 files)
    ("build", "without_stack"),               # e.g., "build API" (no framework)
]

LOW_AMBIGUITY_PATTERNS = [
    ("fix", "single_file"),                   # e.g., "fix bug in auth.ts"
    ("typo", "any"),                          # e.g., "fix typos in docs"
    ("rename", "any"),                        # e.g., "rename function foo to bar"
    ("update docs", "any"),                   # e.g., "update README"
]
```

**AskUserQuestion Trigger Flow:**

```
Parse task → Calculate ambiguity score
                    ↓
        Score HIGH? (multiple valid approaches)
                    ↓ YES
┌─────────────────────────────────────────────────┐
│ AskUserQuestion (PRE-RESEARCH CLARIFICATION)    │
│                                                 │
│ Example questions:                              │
│ - "Which auth strategy: OAuth, JWT, or          │
│    Session-based?" (Recommended: JWT)           │
│ - "Should this include mobile or web only?"     │
│ - "Monorepo or multi-repo architecture?"        │
│                                                 │
│ Format: Max 4 questions, 2-4 options each       │
│         Auto-add "Other (please specify)"       │
└─────────────────────────────────────────────────┘
                    ↓
        User responds with selections
                    ↓
    Launch Explore agents with refined scope
                    ↓
        Research complete → Multiple solutions found?
                    ↓ YES
┌─────────────────────────────────────────────────┐
│ AskUserQuestion (POST-RESEARCH SELECTION)       │
│                                                 │
│ Example:                                        │
│ "Research found 3 auth libraries:               │
│  - Passport.js (Recommended - most popular)     │
│  - Auth0 SDK (Easiest integration)              │
│  - Custom JWT (Most control)                    │
│  Which should we use?"                          │
└─────────────────────────────────────────────────┘
                    ↓
        User selects option
                    ↓
            Write detailed plan
```

**Agent Count Offers (Simple Tasks):**

When LOW ambiguity detected, offer fewer agents:

```
Detected simple task: fix typo in README
Recommended: 2 agents, 2 iterations

Continue with 2 agents? (yes/no/specify count)
```

**Question Format Requirements:**

- **Maximum 4 questions** per AskUserQuestion call
- **2-4 options** per question (not including "Other")
- **Auto-add** "Other (please specify)" as final option
- **Mark recommended** with "(Recommended)" suffix
- **Include brief description** for each option (1 sentence max)

**Example Pre-Research Question:**

```markdown
I need clarification on the auth implementation:

1. **Authentication Strategy:**
   - OAuth 2.0 (Best for third-party login)
   - JWT (Recommended - simple, stateless)
   - Session-based (Traditional, server-side state)
   - Other (please specify)

2. **Scope:**
   - Web only
   - Mobile only
   - Both web and mobile (Recommended)
   - Other (please specify)
```

**Example Post-Research Question:**

```markdown
Research found 3 viable auth libraries:

**Which library should we use?**
- Passport.js (Recommended - 22k GitHub stars, extensive middleware ecosystem)
- Auth0 SDK (Easiest integration, managed service)
- Custom JWT implementation (Most control, no dependencies)
- Other (please specify)
```

## Plan File Location and Naming

**Directory:** All plan files are created in `{repo}/.claude/plans/`

**Naming convention:**
- Format: `{type}-{slug}.md`
- Examples:
  - `feature-user-auth.md` - Feature implementation
  - `fix-login-bug.md` - Bug fix
  - `refactor-api-layer.md` - Refactoring work
  - `research-graphql-migration.md` - Research/exploration

**Slug generation:**
- Derived from task description
- Lowercase, hyphen-separated
- Max 50 characters
- Example: "Implement OAuth2 authentication" → `feature-oauth2-authentication.md`

## Plan File Format (MANDATORY)

When creating or updating a plan file, ALWAYS include:

1. **Ralph Configuration block** immediately after the status line
2. **Decision Matrix tables** for all decision points
3. **Emoji-prefixed section headers** for visual scanning
4. **Session name** from `~/.claude/.session-info` (read JSON → `session_name` field; fallback to plan slug)

### Session Name Retrieval

When creating plan files, populate the `**Session:**` field as follows:

1. **Read** `~/.claude/.session-info` JSON file
2. **Extract** the `session_name` field from the JSON
3. **Fallback** to the plan slug (plan file name without extension) if:
   - `.session-info` file is missing
   - File is empty or malformed JSON
   - `session_name` field is null, empty string `""`, or missing

**Note:** The `.session-info` file is overwritten on every session start. Do NOT validate the `session_id` field - trust the `session_name` value directly. If the session hasn't been renamed yet, `session_name` may be an empty string.

**Security:** `session_name` is unsanitized user input from the `/rename` command. Safe for markdown context, but NEVER use in shell commands or file paths without validation (risks: newlines, backticks, special chars).

**Example:**
```json
// ~/.claude/.session-info
{
  "session_id": "abc-123",
  "session_name": "CLAUDE 1",
  "timestamp": "2026-02-06T14:30:00.000Z"
}
```
→ Use `"CLAUDE 1"` in plan frontmatter

**Template:**

```markdown
# [Plan Title]

**Created:** YYYY-MM-DD
**Last Updated:** YYYY-MM-DDTHH:MM:SSZ
**Status:** Pending Approval | In Progress | Completed
**Session:** {session-name}

**Ralph Configuration:**
- Implementation Agents: [N from parsed args]
- Implementation Iterations: [M from parsed args]
- Post-Review Agents: [rN or default 5]
- Post-Review Iterations: [rM or default 2]
- Launch Command: `/start [original command]`

## 🔒 Security Considerations

[Content here]

## 🏗️ Architecture Decisions

### Authentication Strategy

| # | Option | Pros | Cons | 🎯 |
|---|--------|------|------|-----|
| 1 | JWT cookies | - XSS protection<br>- Secure by default | - CORS setup needed | ⭐ |
| 2 | Bearer tokens | - Stateless | - XSS vulnerable |  |

**Recommendation:** Option 1 for enhanced security.

---

## ⚡ Performance Impact

[Content here]

## 📋 Implementation Status

| # | ✅ Task | 🔴 Risk | 📋 Status |
|---|---------|---------|----------|
| 1 | Auth flow | 🟡 Med | ✅ Done |
| 2 | API layer | 🔴 High | ⏳ WIP |
```

**Plan Template Rules:**
- Every decision point gets a Decision Matrix table
- Section headers use category emojis (🔒 🏗️ ⚡ 📝 🧪 🎨)
- Status tables use status emojis (✅ ⏳ ❌ 🔴 🟡 🟢)
- Related items stay grouped under `<hr>` sections
- Recommended option gets ⭐ in 🎯 column

### Examples

| Command                                   | Agents | Iterations | Model Mode     | Post-Review       | Scope                |
| ----------------------------------------- | ------ | ---------- | -------------- | ----------------- | -------------------- |
| `/start`                                | 3      | 3          | Opus (all)     | 5 agents, 2 iter  | No task (planning)   |
| `/start fix the APIs`                   | 3      | 3          | Opus (all)     | 5 agents, 2 iter  | Task description     |
| `/start sonnet fix auth`               | 3      | 3          | Sonnet→Opus   | 5 agents, 2 iter  | Sonnet plan, Opus impl |
| `/start sonnet all fix auth`           | 3      | 3          | Sonnet (all)   | 5 agents, 2 iter  | Budget mode          |
| `/start 5 3 sonnet build API`          | 5      | 3          | Sonnet→Opus   | 5 agents, 2 iter  | Sonnet plan, Opus impl |
| `/start 5 10`                           | 5      | 10         | Opus (all)     | 5 agents, 2 iter  | No task (planning)   |
| `/start 5 3 noreview implement auth`    | 5      | 3          | Opus (all)     | Disabled          | Skip post-review     |
| `/start 15 5 review`                    | 15     | 5          | Opus (all)     | N/A               | Entire codebase      |
| `/start 15 5 review src/`               | 15     | 5          | Opus (all)     | N/A               | Specific path        |
| `/start 5 3 review 10 2 implement auth` | 5      | 3          | Opus (all)     | 10 agents, 2 iter | Custom review config |
| `/start 3 5 import PRD.md`              | 3      | 5          | Opus (all)     | 5 agents, 2 iter  | From PRD file        |

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
4. **Consider 3-5 options** for each design decision using **Decision Matrix Format**:

| # | Option | Pros | Cons | 🎯 |
|---|--------|------|------|-----|
| 1 | [Option name] | - Pro A<br>- Pro B | - Con A<br>- Con B | ⭐ |
| 2 | [Option name] | - Pro A<br>- Pro B | - Con A<br>- Con B |  |

- Use `<br>` tags to stack multiple items in cells
- Add ⭐ in 🎯 column for recommended option
- Number options sequentially (1, 2, 3...)

### Step 2: Generate Implementation Plan Artifact

Create a structured plan following the **Decision Matrix Format** with emoji-prefixed sections:

**Required Structure:**
1. **Overview** - Brief description with context
2. **Dependencies** - External requirements and constraints
3. **Decision Matrices** - Options analysis for each key decision
4. **Implementation Steps** - Actionable verbs grouped under `<hr>` sections
5. **Verification Checklist** - How to confirm success
6. **Rollback Plan** - Recovery procedure

**Decision Matrix Format (MANDATORY for all options):**

```markdown
| # | Option | Pros | Cons | 🎯 |
|---|--------|------|------|-----|
| 1 | [Option name] | - Pro A<br>- Pro B | - Con A<br>- Con B | ⭐ |
| 2 | [Option name] | - Pro A<br>- Pro B | - Con A<br>- Con B |  |
| 3 | [Option name] | - Pro A<br>- Pro B | - Con A<br>- Con B |  |
```

- **Each decision point gets its own Decision Matrix table**
- **Use `<br>` to stack multiple items in Pros/Cons cells**
- **Add ⭐ emoji in 🎯 column for recommended option**
- **Number options sequentially within each matrix**

**Emoji Section Headers (MANDATORY):**

```markdown
## 🔒 Security Considerations
## ⚡ Performance Impact
## 🏗️ Architecture Changes
## 📝 Documentation Updates
## 🧪 Test Coverage
## 🎨 UI/UX Changes
```

**Status Emojis (use in table cells):**
- **Priority:** 🔴 Critical | 🟡 Medium | 🟢 Low
- **Status:** ✅ Done | ⏳ WIP | ❌ Blocked
- **Risk:** ⚠️ Warning | 🔴 High | 🟡 Med | 🟢 Low

**Grouping Rules:**
- Keep correlated items together under `<hr>` sections
- Don't split related decisions across sections
- Group by domain (auth, API, UI) not by type (decisions, steps)

**Decision Matrix Examples:**

```markdown
## 🔒 Authentication Strategy Decision

| # | Option | Pros | Cons | 🎯 |
|---|--------|------|------|-----|
| 1 | JWT with HTTP-only cookies | - XSS protection<br>- No localStorage risk<br>- Automatic CSRF tokens | - CORS complexity<br>- Cookie size limits | ⭐ |
| 2 | OAuth2 Bearer tokens | - Stateless<br>- Third-party support | - XSS vulnerable<br>- Manual refresh logic |  |
| 3 | Session-based auth | - Simple implementation<br>- Server-side revocation | - Scaling challenges<br>- Redis dependency | |

**Recommendation:** Option 1 (JWT cookies) provides best security for our SPA architecture.

---

## ⚡ Caching Strategy Decision

| # | Option | Pros | Cons | 🎯 |
|---|--------|------|------|-----|
| 1 | React Query with stale-while-revalidate | - Built-in optimistic updates<br>- Smart cache invalidation<br>- Offline support | - 15KB bundle size<br>- Learning curve | ⭐ |
| 2 | Native fetch with manual cache | - Zero dependencies<br>- Full control | - Manual invalidation<br>- No offline support |  |
| 3 | Apollo Client | - GraphQL integration<br>- Normalized cache | - 45KB bundle<br>- GraphQL required |  |

**Recommendation:** Option 1 (React Query) balances DX and performance.
```

**Status Table Examples:**

```markdown
## 📋 Implementation Status

| # | ✅ Feature | 🔴 Risk Level | 📋 Status | 🎯 Owner |
|---|-----------|--------------|----------|---------|
| 1 | Auth flow | 🟡 Medium | ✅ Done | Agent-3 |
| 2 | API cache | 🟢 Low | ⏳ WIP | Agent-5 |
| 3 | Error boundaries | 🔴 High | ❌ Blocked | Agent-7 |
```

**Comparison Matrix Examples:**

```markdown
## 🏗️ Database Migration Comparison

| Feature | Option A | Option B | Option C |
|---------|---------|---------|---------|
| Performance | ✅ Fast | 🟡 Medium | ❌ Slow |
| Complexity | 🟢 Simple | 🟡 Moderate | 🔴 Complex |
| Rollback | ✅ Safe | ⚠️ Manual | ❌ Risky |
| Cost | 🟢 Low | 🟡 Med | 🔴 High |
```

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
- **Auto-cleanup stale review report**: Grep source files for `TODO-P[123]:` (exclude `skills/`, `agents/`). If zero remain, delete `.claude/review-agents.md` — the report is stale since all findings are resolved

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

## Agent Spawning via Native Team Agents (MANDATORY)

After parsing arguments and creating/validating the plan, you MUST create a native team and spawn agents as teammates. All agents are spawned in PARALLEL in a SINGLE message with multiple Task() calls that include `team_name`.

### Execution Flow

1. Parse `$ARGUMENTS` per Decision Tree
2. Echo parsed values for confirmation
3. If task provided: Create/update plan file with Ralph Configuration block
4. **Initialize Ralph state** via `ralph.py setup` (state files only, no spawning)
5. **Create native team** via `TeamCreate(team_name="ralph-impl")`
6. **Create tasks** via TaskCreate for each work unit
7. **Spawn ALL agents in PARALLEL** via multiple Task() calls with `team_name="ralph-impl"` (includes implementation agents + git-coordinator)
8. Each implementation agent:
   - Joins the native team as a teammate
   - Receives agent number and total count in prompt
   - Gets phase name and specific task assignment
   - Uses correct model (opus/sonnet based on modelMode)
   - Loads plan file for context
   - Coordinates via SendMessage and shared TaskList
   - Follows anti-hallucination standard
   - **NO git operations** - git-coordinator handles ALL commits/pushes
   - Signals completion via `TaskUpdate(status="completed")` + `SendMessage(recipient="team-lead")`
9. **Monitor progress** — As team lead, watch for idle notifications and completed tasks
10. After all agents complete: Check `.claude/ralph/retry-queue.json` for failed tasks
11. If retry queue has entries: Spawn additional agents for retries
12. **Shutdown team** — Send shutdown_request to each agent, then TeamDelete()
13. Report completion summary

### Team Creation (MANDATORY)

Before spawning any agents, create the native team:

```python
TeamCreate(
    team_name="ralph-impl",
    description="Ralph implementation team for: [TASK_DESCRIPTION]"
)
```

### Spawning Pattern (MANDATORY)

**CRITICAL:** All agents MUST be spawned in a SINGLE message with multiple Task() calls. Each MUST include `team_name` and `name` parameters.

Example: Spawning 3 agents in parallel (single message, 3 Task calls):

```python
Task(
    subagent_type="general-purpose",
    model="opus",  # or "sonnet" based on modelMode
    mode="acceptEdits",  # if auto-accept enabled
    team_name="ralph-impl",  # REQUIRED: joins native team
    name="oauth-impl-1",  # REQUIRED: descriptive {role}-{N} name
    prompt="""RALPH Agent 1/3 (oauth-impl-1) - Phase 2.1: Implementation

**Plan file:** C:\\Users\\Dennis\\.claude\\plans\\feature-auth.md

**Your task:** Implement OAuth flow with PKCE

**Capability:** Backend auth token exchange, PKCE challenge generation

**Ralph protocol:**
- Check TaskList for available work
- Claim tasks with TaskUpdate(owner="oauth-impl-1")
- Use SendMessage(recipient="team-lead") to report progress
- Mark tasks completed via TaskUpdate(status="completed")
- Signal team-lead: SendMessage(recipient="team-lead", content="Task X completed: [summary]")
- When you receive a shutdown_request message (JSON with type "shutdown_request"), respond by calling SendMessage with type="shutdown_response", request_id=(from the message), approve=true

**Specifically:**
1. Read plan file for architectural context
2. Implement token exchange endpoint
3. Add PKCE challenge generation
4. Update session management

**Success criteria:**
- All endpoints functional
- Tests passing
- Types correct
- Push commits to remote before completion
"""
)

Task(
    subagent_type="general-purpose",
    model="opus",
    mode="acceptEdits",
    team_name="ralph-impl",
    name="login-ui-1",  # Descriptive: what this agent does
    prompt="""RALPH Agent 2/3 (login-ui-1) - Phase 2.1: Implementation

**Plan file:** C:\\Users\\Dennis\\.claude\\plans\\feature-auth.md

**Your task:** Add frontend login UI

**Capability:** Frontend React components, OAuth redirect flow, UX states

**Ralph protocol:**
- Check TaskList for available work
- Claim tasks with TaskUpdate(owner="login-ui-1")
- Use SendMessage(recipient="team-lead") to report progress
- Mark tasks completed via TaskUpdate(status="completed")
- Signal team-lead: SendMessage(recipient="team-lead", content="Task X completed: [summary]")
- When you receive a shutdown_request message (JSON with type "shutdown_request"), respond by calling SendMessage with type="shutdown_response", request_id=(from the message), approve=true

**Specifically:**
1. Create login form component
2. Implement OAuth redirect flow
3. Add loading states
4. Handle auth errors

**Success criteria:**
- UI matches design
- Accessibility checked
- Push commits to remote before completion
"""
)

Task(
    subagent_type="general-purpose",
    model="opus",
    mode="acceptEdits",
    team_name="ralph-impl",
    name="api-middleware-1",  # Descriptive: what this agent does
    prompt="""RALPH Agent 3/3 (api-middleware-1) - Phase 2.1: Implementation

**Plan file:** C:\\Users\\Dennis\\.claude\\plans\\feature-auth.md

**Your task:** Update API middleware for auth

**Capability:** Express/Fastify middleware, JWT validation, rate limiting

**Ralph protocol:**
- Check TaskList for available work
- Claim tasks with TaskUpdate(owner="api-middleware-1")
- Use SendMessage(recipient="team-lead") to report progress
- Mark tasks completed via TaskUpdate(status="completed")
- Signal team-lead: SendMessage(recipient="team-lead", content="Task X completed: [summary]")
- When you receive a shutdown_request message (JSON with type "shutdown_request"), respond by calling SendMessage with type="shutdown_response", request_id=(from the message), approve=true

**Specifically:**
1. Add JWT validation middleware
2. Implement refresh token rotation
3. Add rate limiting
4. Update error responses

**Success criteria:**
- Middleware tests passing
- Security review passed
- Push commits to remote before completion
"""
)
```

### Model Routing (MANDATORY)

Based on parsed `modelMode`, set the `model` parameter for each Task:

| Model Mode     | Plan Phase Agents   | Impl Phase Agents   |
| -------------- | ------------------- | ------------------- |
| `opus`       | `model="opus"`    | `model="opus"`    |
| `sonnet`     | `model="sonnet"`  | `model="opus"`    |
| `sonnet_all` | `model="sonnet"`  | `model="sonnet"`  |

**Phase detection:**
- If in Plan Mode OR before ExitPlanMode: Use plan phase model
- If after ExitPlanMode: Use impl phase model
- If `sonnet all`: ALL phases use `model="sonnet"`

### Auto-Accept Detection

Check for auto-accept before spawning:

1. Read `.claude/ralph/state.json` → look for `autoAccept: true`
2. OR check env var `CLAUDE_AUTO_ACCEPT=true`
3. If enabled: Set `mode="acceptEdits"` for all Task calls
4. If disabled: Omit `mode` parameter (defaults to interactive)

### Agent Prompt Template (MANDATORY)

Each agent prompt MUST include:

```
RALPH Agent {X}/{N} ({agent_name}) - Phase {phase_number}: {phase_name}

**Plan file:** {absolute_path_to_plan}

**Your task:** {specific_task_description}

**Capability:** {what_this_agent_specializes_in}

**Ralph protocol:**
- Check TaskList for available work
- Claim tasks with TaskUpdate(owner="{agent_name}")
- Use SendMessage(recipient="team-lead") to report progress
- Mark tasks completed via TaskUpdate(status="completed")
- Signal team-lead: SendMessage(recipient="team-lead", content="Task X completed: [summary]")
- When you receive a shutdown_request message (JSON with type "shutdown_request"), respond by calling SendMessage with type="shutdown_response", request_id=(from the message), approve=true

**Specifically:**
{detailed_steps_or_requirements}

**Success criteria:**
{what_defines_completion}
- Push commits to remote before completion
```

**Required fields:**
- `{X}/{N}` - Agent number and total (e.g., "3/10")
- `{agent_name}` - Descriptive name matching the Task `name` param (e.g., "oauth-impl-1")
- `{phase_number}` - Current phase (e.g., "2.1")
- `{phase_name}` - Phase description (e.g., "Implementation")
- `{absolute_path_to_plan}` - Full path to plan file
- `{specific_task_description}` - What this agent should do
- `{what_this_agent_specializes_in}` - Capability hint for team lead routing (1 line)
- `{detailed_steps_or_requirements}` - Breakdown of work
- `{what_defines_completion}` - Clear completion criteria

**Agent naming convention (MANDATORY):**
- Format: `{role}-{N}` where role describes what the agent does
- Examples: `oauth-impl-1`, `login-ui-2`, `api-middleware-1`, `db-migration-1`
- For research: `{topic}-researcher-1` (e.g., `maestro-researcher-1`)
- For review: `{scope}-reviewer-1` (e.g., `auth-reviewer-1`)
- git-coordinator keeps its name as-is

**Required Task() parameters:**
- `team_name="ralph-impl"` - Joins the native team
- `name="{role}-{N}"` - Descriptive teammate name (NOT "agent-{X}")
- `model="opus"` or `"sonnet"` - Based on modelMode
- `mode="acceptEdits"` - If auto-accept enabled

### Git Coordinator Pattern (MANDATORY for Multi-Agent Sessions)

When spawning >1 implementation agent, ALWAYS include a git-coordinator agent to prevent git conflicts.

**Why needed:** Multiple agents cannot safely execute concurrent git operations (add, commit, push, rebase). The git-coordinator is the single write point for all git operations.

**Spawning:**

```python
# Spawn AFTER implementation agents, before monitoring
Task(
  subagent_type="general-purpose",
  model="haiku",  # Lightweight, low cost
  team_name="ralph-impl",
  name="git-coordinator",
  prompt="""Git Coordinator Agent

**Role:** Handle ALL git operations for this Ralph session

**Protocol:**
1. Monitor SendMessage from implementation agents (type="work_complete")
2. Collect change summaries as agents complete work
3. Wait for team-lead signal: type="create_commit"
4. Execute atomic commit with aggregated message
5. Push if autoPush=true
6. Report status back to team-lead via SendMessage

**Git Operations (ONLY git-coordinator may execute):**
- git add <files>
- git commit -m "message"
- git push --force-with-lease origin <branch>

**Prohibited for implementation agents:**
- NO Bash tool usage for git commands
- Agents make code changes via Edit/Write ONLY
- Agents signal completion via SendMessage to git-coordinator

**Success criteria:**
- Single atomic commit created
- All changes from agents included
- Push successful (if authorized)
- Team-lead notified via SendMessage

When complete, mark your task as completed via TaskUpdate(status="completed") and send:
SendMessage(recipient="team-lead", content="Git operations complete: [commit hash], [N] files, pushed=[yes/no]")
"""
)
```

**Communication protocol:**

```typescript
// Implementation agent → Git-coordinator (after completing work)
SendMessage({
  recipient: "git-coordinator",
  type: "work_complete",
  summary: "Implemented feature X in files Y, Z",
  files: ["lib/auth.ts", "lib/oauth.ts"]
})

// Team-lead → Git-coordinator (after all agents complete)
SendMessage({
  recipient: "git-coordinator",
  type: "create_commit",
  message: "feat(auth): implement OAuth2 flow\n\n- Added PKCE\n- Token rotation\n- Refresh mechanism",
  autoPush: true
})

// Git-coordinator → Team-lead (after commit/push)
SendMessage({
  recipient: "team-lead",
  type: "commit_created",
  commitHash: "a1b2c3d4",
  filesChanged: 2,
  pushed: true
})
```

**Benefits:**
- ✅ No git lock conflicts
- ✅ Single atomic commit (clean history)
- ✅ Safe push with --force-with-lease
- ✅ Easy rollback (single commit = single revert)

**Reference:** See `agents/git-coordinator.md` for full protocol documentation.

---

### Retry Queue Check (MANDATORY)

After all agent tasks show `status: "completed"` in TaskList, check for retries:

```bash
# Check if retry queue exists
if [ -f .claude/ralph/retry-queue.json ]; then
    # Parse JSON and spawn agents for failed tasks
    # Use same Task() pattern as initial spawn
    # Include retry count in agent prompt: "RALPH Agent X/N (Retry 1)"
fi
```

### Post-Review Phase (If Enabled)

After implementation completes, run PLAN VERIFICATION then optionally REVIEW:

**Phase 2.5: Plan Verification (always runs)**
1. Output: "Implementation complete! Running plan verification..."
2. `ralph.py` spawns plan-verifier agent (uses `agents/plan-verifier.md` protocol)
3. Verifier reads plan file AND referenced artifacts (HTML mockups, design specs)
4. Cross-references plan tasks against actual code changes via git diff + Serena
5. If gaps found: writes gap-fill prompts to `.claude/ralph/gap-fill-prompts.json`
6. Team lead reads gap-fill prompts and spawns targeted IMPL agents for missing tasks
7. Re-verifies after gap-fill (up to 3 iterations)
8. Proceeds to review only when plan verification PASSES

**Phase 3: Review (if `postReviewEnabled = true`, default)**
1. Send `shutdown_request` to all implementation agents
2. Spawn review agents using same Task() pattern with `team_name="ralph-impl"`
3. Set agent prompts to review mode (see skills/review/SKILL.md)
4. Review agents use `disallowedTools: [Write, Edit, MultiEdit]`
5. Review agents leave TODO-P1/P2/P3 comments
6. Review agents report findings to `.claude/review-agents.md`
7. After review complete: Send `shutdown_request` to review agents, then `TeamDelete()`
8. **Auto-cleanup**: After TeamDelete, grep source files for remaining `TODO-P[123]:`. If **zero** remain, delete `.claude/review-agents.md` (stale report — all findings resolved). If TODOs remain, keep the report as reference.

**Review agent counts:**
- Default: 5 review agents, 2 iterations
- Custom: Use `postReviewAgents` and `postReviewIterations` from parsing

## Related Skills

- **`/commit`** - Create commits from `.claude/commit.md` with branch-aware naming
- **`/commit log`** - Manually log file changes (auto-tracked by hooks)
- **`/screen`** - Capture screenshots for visual verification
- **`/code-standards`** - Run Biome, Knip, accessibility, and architecture checks
