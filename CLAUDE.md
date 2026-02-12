# Claude Code Configuration (Based on 2.1.39)

## Directory Structure

```
~/.claude/
├── .github/                    # GitHub templates and workflows
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── ISSUE_TEMPLATE/
│   └── workflows/claude.yml
├── agents/                     # Agent configuration files (25 files)
├── hooks/                      # Claude Code hook handlers (14 files)
├── output-styles/              # Response formatting styles
├── scripts/                    # CLI utilities (30 scripts)
├── skills/                     # Skill definitions (/commands, 16 skills)
├── CLAUDE.md                   # Core patterns (this file)
├── settings.json               # Hook registrations
└── README.md                   # Public-facing documentation
```

## Pending Files Convention

All temporary pending files MUST be created in `{repo}/.claude/` directory, never in repo root:

| File              | Correct Location                     | Wrong Location               |
| ----------------- | ------------------------------------ | ---------------------------- |
| pending-commit.md | `{repo}/.claude/pending-commit.md` | `{repo}/pending-commit.md` |
| pending-pr.md     | `{repo}/.claude/pending-pr.md`     | `{repo}/pending-pr.md`     |
| commit.md         | `{repo}/.claude/commit.md`         | Already correct              |

This keeps repo root clean and prevents accidental commits of temporary files.

## ACID Data Integrity

All state files use transactional primitives from `hooks/transaction.py`:

| File                     | Pattern        | Timeout | Why                            |
| ------------------------ | -------------- | ------- | ------------------------------ |
| `sessions-index.json`  | OCC (lockless) | N/A     | Low write contention           |
| `ralph/progress.json`  | Locked R/W     | 5s      | High-conflict agent updates    |
| `commit.md`            | Atomic write   | N/A     | Sequential hooks, crash safety |
| `receipts.json`        | Locked append  | 5s      | Audit trail integrity          |
| `emergency-state.json` | Locked R/W     | 5s      | Cross-platform safety          |

**Import pattern:**

```python
from hooks.transaction import atomic_write_json, transactional_update, locked_read_json
```

**Error handling:** Catch `LockTimeoutError` for graceful degradation, `ValidationError` for schema issues.

**Test coverage:** Run `python -m pytest scripts/test_transaction.py -v` (21 tests)

## Frontend Visual Verification

When editing frontend files (pages, components, styles), verify changes visually:

**Files requiring verification:**

- `app/**/*.tsx` - Next.js pages and layouts
- `components/**/*.tsx` - React components
- `styles/**/*.css` - Stylesheets
- `public/**/*` - Static assets

**Verification workflow:**

1. PostToolUse hook detects frontend edit → outputs suggestion
2. Run `/launch` to start dev server and open browsers
3. Check for visual regressions, console errors, network issues
4. Document findings in response

**Exceptions (skip verification):**

- README/documentation changes
- Test file edits (`*.test.tsx`, `*.spec.tsx`)
- Type definition changes (`*.d.ts`)
- Config files (`*.config.ts`, `*.config.js`)

## Plan Files (MANDATORY)

All plans in `/plans/` MUST follow Plan Change Tracking:

**Required Frontmatter:**

```markdown
# Plan Title

**Created:** YYYY-MM-DD
**Last Updated:** YYYY-MM-DDTHH:MM:SSZ
**Status:** Pending Approval | In Progress | Completed
**Session:** {session-name}
```

**On every plan update:**

1. Remove ALL existing 🟧 (Orange Square) markers
2. Add 🟧 marker AT END of modified lines (not beginning - avoids breaking markdown)
3. Update "Last Updated" timestamp
4. If `USER:` comments found - process, remove, mark changed line with 🟧 at end

**Change Marker Format (Markdown-Safe Rules):**

```markdown
### Section Title 🟧    <- Correct: marker at END
Some changed content 🟧

🟧 ### Title            <- WRONG: breaks markdown heading
```

**Element-specific rules:**

| Element        | Rule                                                      | Example                              |
| -------------- | --------------------------------------------------------- | ------------------------------------ |
| Headings       | Marker at END of heading text                             | `### Section Title 🟧`             |
| Paragraphs     | Marker at END of line                                     | `Some changed content 🟧`          |
| Lists          | After item text                                           | `- Item description 🟧`            |
| Tables (cells) | INSIDE last cell, before closing `\|`                    | `\| value \| changed 🟧 \|`           |
| Table headers  | INSIDE last header cell, before closing `\|`             | `\| Col A \| Col B 🟧 \|`             |
| Separator rows | NEVER mark (`\|---\|---\|` rows)                           | Leave untouched                      |
| Code blocks    | NEVER inside fences -- mark the line ABOVE the code block | `Changed code below 🟧` then fence |
| Inline code    | Marker OUTSIDE backticks                                  | `` `value` 🟧 ``                     |

**Marker Lifecycle:**

1. **Strip first**: Remove ALL existing 🟧 markers from the entire document
2. **Then mark**: Add 🟧 only to lines changed in this edit pass
3. **Result**: Only current changes are marked; stale markers never accumulate

**Never ask user:**

- "How do you want to provide feedback?"
- "Should I proceed with the plan?"
- Any confirmation about plan workflow itself

**To process USER comments:** Run `/reviewplan`

**Emoji formatting (all plans):**

- Section headers get category emojis (🔒🏗️⚡📝🧪🎨)
- Table rows get status emojis (✅⚠️❌🟢🟡🔴)
- Decision tables use emoji-first compact format
- Comparison matrices use emoji column headers

## Mermaid Theme Standard

Claude Code Orange theme with rounded shapes (no diamonds):

```mermaid
%%{init: {'theme': 'dark', 'themeVariables': { 'primaryColor': '#0c0c14', 'primaryTextColor': '#fcd9b6', 'primaryBorderColor': '#c2410c', 'lineColor': '#ea580c', 'edgeLabelBackground': '#18181b'}}}%%
graph TD
    A["Node"] --> B(["Decision?"])
    style A fill:#0c0c14,stroke:#ea580c,stroke-width:3px,color:#fcd9b6
    style B fill:#18181b,stroke:#fb923c,stroke-width:3px,color:#fff7ed
```

**Shape Guide:**

- `["text"]` = Rectangle (actions, endpoints)
- `(["text"])` = Stadium/pill (decisions) - USE THIS instead of diamonds
- Avoid `{"text"}` diamonds - makes charts look like chess boards

**Color Palette:**

- Background: `#09090b` (near-black)
- Node fill: `#0c0c14` (dark navy)
- Decision fill: `#18181b` (zinc-900)
- Border/Lines: `#ea580c` (orange-600)
- Text: `#fcd9b6` (peach)
- Success nodes: `#16a34a` border (green)
- Debug nodes: `#8b5cf6` border (violet)

## Build Numbering Convention

Build IDs are **auto-detected** from CHANGELOG.md — no manual assignment needed.

**Branching Model:**

| Branch              | Purpose                   | Build ID Source                        |
| ------------------- | ------------------------- | -------------------------------------- |
| `main`            | Production                | Auto from CHANGELOG.md via `/commit` |
| `{repo}-dev`      | Development (PRs to main) | Auto from CHANGELOG.md via `/openpr` |
| `feature/b{id}-*` | Legacy feature branches   | From branch name (backward compat)     |

**Examples:**

- `claude-dev` - Development branch for bosmadev/claude
- `pulsona-dev` - Development branch for bosmadev/pulsona
- `cwchat-dev` - Development branch for bosmadev/cwchat

**Build ID Auto-Detection:**

- `/commit` on `main`: reads CHANGELOG.md → highest Build N → injects `Build N+1`
- `/openpr` from `*-dev`: reads CHANGELOG.md → highest Build N → PR title: `Build N+1`
- Legacy `b{N}` branches: extracted from branch name (backward compat)
- Fallback: `Build 1` if no CHANGELOG.md or no existing builds

**Why Build IDs:**

- Track changes across non-linear merge history
- Link PR summaries to specific work items
- Enable automated CHANGELOG grouping
- Survive squash merges and rebases

**Workflow:**

1. Work on `claude-dev` → make commits (no Build ID needed)
2. Run `/openpr` → auto-detects `Build N+1` → creates PR
3. Squash merge to main → `changelog.ts` picks up Build ID → CHANGELOG entry
4. Direct commits to main → `/commit` auto-injects Build ID

## CHANGELOG Automation

Automated changelog generation via GitHub Actions workflow (`claude.yml`):

### Workflow: @claude prepare → Review → Squash Merge → Auto CHANGELOG

1. **@claude prepare** - Bot creates PR with:

   - Aggregated commit summary (grouped by file)
   - Build ID extracted from branch name
   - Review checklist
2. **Review** - Team reviews PR via GitHub UI

   - Add comments, request changes
   - Approve when ready
3. **Squash Merge** - Merge PR to main:

   - GitHub Actions triggers automatically
   - Reads PR body for commit aggregation
   - Extracts build ID from branch name
   - Generates CHANGELOG entry
4. **Auto Release** - GitHub Actions creates tag + release:

   - Reads new version from package.json
   - Creates annotated git tag `v{version}`
   - Creates GitHub Release with CHANGELOG entry as notes
   - Skips if tag already exists
5. **CHANGELOG Entry Format:**

```markdown
---

## [![v{version}](https://img.shields.io/badge/v{version}-{date}--{date}-333333.svg)](https://github.com/bosmadev/{repo}/pull/{pr}) | Build {id}

{summary}

- [x] {change_1}
- [x] {change_2}
```

- Badge links to PR (if `(#N)` in commit subject) or commit SHA
- `333333` dark badge color, `[x]` checkboxes
- `---` separator between entries

6. **Release Format:**

- Tag: `v{version}` (e.g., `v1.2.3`)
- Title: `Release v{version}`
- Body: Extracted CHANGELOG entry for the build
- Created by: `github-actions[bot]`

### Key Points

**Worktree Behavior:**

- Working branches do NOT edit CHANGELOG directly
- All CHANGELOG updates happen via GitHub Actions post-merge
- Prevents merge conflicts and duplication

**Build ID Injection:**

- **Main branch:** `/commit` auto-reads CHANGELOG.md for highest Build N, injects `Build N+1` into commit subject
- **Feature branches:** Build ID comes from branch name (`feature/b101-auth` → `Build 101`) via `/openpr` squash merge
- `changelog.ts` requires `Build N` in commit subject to trigger — format: `Build 3: feat: description`

**Version Bumping:**

- Uses `scripts/aggregate-pr.py --bump` logic
- Follows semantic versioning (major.minor.patch)
- Auto-detects version type from PR labels or commit messages

**Manual Override:**

- Edit CHANGELOG directly on main if needed
- Use conventional commit format in PR title to influence versioning
- Add `skip-changelog` label to PR to bypass automation
- Add `skip-release` label to PR to bypass release creation

## 3-Layer Model Routing

Token-efficient model assignment via permanent, native mechanisms:

| Layer                            | Mechanism                                                      | Scope             | Effect                                 |
| -------------------------------- | -------------------------------------------------------------- | ----------------- | -------------------------------------- |
| **L1: Global Default**     | `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` in `settings.json` env | ALL subagents     | All forked skills run as Sonnet        |
| **L2: Skill Fork**         | `context: fork` in SKILL.md frontmatter                      | The skill itself  | Skill runs as Sonnet subagent (via L1) |
| **L3: Per-Agent Override** | `model="opus"` in `Task()` calls                           | Individual agents | Overrides L1 for agents needing Opus   |

### Skills Model Assignment

| Skill           | Fork?   | Model       | Rationale                                      |
| --------------- | ------- | ----------- | ---------------------------------------------- |
| `/start`      | No      | Opus (main) | Complex orchestration, spawns Opus agents (L3) |
| `/repotodo`   | No      | Opus (main) | Critical code changes across files             |
| `/reviewplan` | No      | Opus (main) | Spawns research agents                         |
| `/review`     | No fork | Opus (main) | Spawns Task agents with model="sonnet"         |
| `/commit`     | Fork    | Sonnet (L1) | Pattern matching, no code changes              |
| `/openpr`     | Fork    | Sonnet (L1) | Reads commits, generates PR body               |
| `/screen`     | Fork    | Sonnet (L1) | Screenshot management                          |
| `/youtube`    | Fork    | Sonnet (L1) | Transcription management                       |
| `/launch`     | Fork    | Sonnet (L1) | Browser verification                           |
| `/token`      | Fork    | Haiku       | Token status/refresh                           |

### Complete Model Routing Matrix

| Component | Model | Effort | Context | Layer | Notes |
|-----------|-------|--------|---------|-------|-------|
| `/start` main | Opus 4.6 | High | 200K | — | Complex orchestration |
| `/start` impl agents | Opus 4.6 | High | 200K | L3 | Task(model="opus") override |
| `/start` plan agents | Opus 4.6 | Med | 200K | L3 | Planning phase |
| `/start sonnet` plan | Sonnet 4.5 | N/A | 200K | L3 | Budget-mode planning |
| `/review` main | Opus 4.6 | Med | 200K | — | Orchestration only |
| `/review` agents | Sonnet 4.5 | N/A | 1M | L3 | Read-only, extended context |
| `/repotodo` | Opus 4.6 | High | 200K | — | Critical code changes |
| `/reviewplan` | Opus 4.6 | Med | 200K | — | Plan edits only |
| `/commit` | Sonnet 4.5 | N/A | 200K | L2 | Fork, pattern matching |
| `/openpr` | Sonnet 4.5 | N/A | 200K | L2 | Fork, read commits |
| `/screen` | Sonnet 4.5 | N/A | 200K | L2 | Fork, screenshots |
| `/youtube` | Sonnet 4.5 | N/A | 200K | L2 | Fork, transcription |
| `/launch` | Sonnet 4.5 | N/A | 200K | L2 | Fork, browser |
| `/token` | Haiku 4.5 | N/A | 200K | L2 | Fork, token mgmt |
| `/rule` | Sonnet 4.5 | N/A | 200K | L2 | Fork, settings |
| `/init-repo` | Sonnet 4.5 | N/A | 200K | L2 | Fork, templates |
| VERIFY+FIX scoped | Opus 4.6 | Med | 200K | — | Per-task checks |
| VERIFY+FIX full | Opus 4.6 | High | 200K | — | Final gate |
| VERIFY+FIX plan | Opus 4.6 | Med | 200K | — | Plan checks |
| Post-review agents | Sonnet 4.5 | N/A | 1M | L3 | Read-only review |
| Ralph impl agents | Opus 4.6 | High | 200K | L3 | Task(model="opus") |
| Ralph work-stealing | Opus 4.6 | High | 200K | L3 | Same as impl |
| Ralph retry queue | Opus 4.6 | High | 200K | L3 | Retries need best quality |
| GH Actions (auto PR) | Sonnet 4.5 | N/A | 200K | — | Default trigger |
| GH Actions: Summarize | Sonnet 4.5 | N/A | 1M | — | Large PRs |
| GH Actions: Review | Sonnet 4.5 | N/A | 1M | — | Full repo context |
| GH Actions: Security | Opus 4.6 | Med | 200K | — | OWASP depth |
| GH Actions: Custom | User picks | Varies | Varies | — | workflow_dispatch |
| Specialist agents (7) | Opus | — | — | .md | go, nextjs, python, refactor, verify-fix, owasp, coordinator |
| Review agents (13) | Sonnet | — | — | .md | a11y, api, arch, commit, db, doc, perf, secret, security + more |
| Ops agents (6) | Sonnet | — | — | .md | build-error, e2e, devops, scraper, pr-gen, plan-verify |
| Git coordinator (1) | Haiku | — | — | .md | Lightweight git ops |

**Legend:**
- **Effort:** Low, Med, High (Opus only)
- **Layer:** L1 = Global default, L2 = Skill fork, L3 = Per-agent override, .md = Agent config
- **[1m]:** Extended 1M context window for large file review

---

## Agent Shutdown Protocol

All team agents (IMPL, VERIFY+FIX, review) MUST handle shutdown gracefully:

When you receive a `shutdown_request` message (JSON with `type: "shutdown_request"`), respond by calling `SendMessage` with `type="shutdown_response"`, `request_id` from the message, and `approve=true`. This terminates your process. **Never** respond with "I can't exit" or "close the window" — always use the `SendMessage` tool.

## Skill Commands

For complete skill command tables with all argument combinations, see [README.md > Skills Reference](./README.md#skills-reference).

16 skills available: `/start`, `/review`, `/commit`, `/openpr`, `/init-repo`, `/repotodo`, `/reviewplan`, `/launch`, `/screen`, `/youtube`, `/token`, `/rule`, `/chats`, `/help`, `/serena-workflow`, `/init-repo`

## Web Research Fallback Chain

When fetching web content (research, scouting, documentation), use this fallback chain:

```
1. WebFetch(url)              → Fast, public URLs
2. Playwriter navigate        → If auth/session needed
3. claude-in-chrome            → Debug/inspect via DevTools
```

| Scenario            | Browser          |
| ------------------- | ---------------- |
| Simple public page  | WebFetch         |
| Requires login/auth | Playwriter       |
| Debug/inspect       | claude-in-chrome |

| Browser          | Auth | CDP | Best For              |
| ---------------- | ---- | --- | --------------------- |
| WebFetch         | No   | No  | Simple public pages   |
| Playwriter MCP   | Yes  | Yes | Auth flows, sessions  |
| claude-in-chrome | Yes  | Yes | DevTools, inspection  |

**Note:** Serena is for CODE ANALYSIS only - NOT a browser. For subagents fetching web content, always include this fallback chain in prompts.

## Work-Stealing Queue

Ralph agents use atomic task claiming to prevent idle agents:

```python
# In ralph.py - atomic task claiming with file lock
def claim_next_task(agent_id: str) -> Optional[Task]:
    with FileLock(".claude/ralph/queue.lock"):
        queue = load_queue()
        for task in queue:
            if task.status == "pending" and not task.claimed_by:
                task.claimed_by = agent_id
                task.status = "in_progress"
                save_queue(queue)
                return task
    return None
```

Queue file location: `{project}/.claude/task-queue-{plan-id}.json`

## Ralph Defense-in-Depth

```
┌─────────────────────────────────────────────────────────────────┐
│                     DEFENSE IN DEPTH (7 LAYERS)                  │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: External Script → Orchestrates loop, creates state      │
│ Layer 2: Skill → Invokes script, spawns agents                   │
│ Layer 3: Hook  → Validates protocol, injects reminders           │
│ Layer 4: Context → Always-visible protocol rules                 │
│ Layer 5: Push Gate → MUST push before completion allowed         │
│ Layer 6: Exit  → Validates completion signals                    │
│ Layer 7: VERIFY+FIX → Build/type/lint checks + auto-fix         │
└─────────────────────────────────────────────────────────────────┘
```

### Layer 5: Push Gate (Must Push Before Completion)

Ralph agents MUST push their work to remote before signaling completion. This prevents lost work from uncommitted/unpushed changes, orphaned local branches, and silent failures.

**Enforcement Flow:**

```mermaid
%%{init: {'theme': 'dark', 'themeVariables': { 'primaryColor': '#0c0c14', 'primaryTextColor': '#fcd9b6', 'primaryBorderColor': '#c2410c', 'lineColor': '#ea580c', 'secondaryColor': '#18181b', 'background': '#09090b', 'mainBkg': '#0c0c14', 'edgeLabelBackground': '#18181b'}}}%%
graph TD
    A["Agent: Work Complete"] --> B(["Has Commits?"])
    B -->|No| C["Skip Push Gate"]
    B -->|Yes| D(["Pushed to Remote?"])
    D -->|Yes| E["Allow TaskUpdate(completed)"]
    D -->|No| F["BLOCK: Must Push First"]
    F --> G["Agent: git push"]
    G --> D
    C --> E

    style A fill:#0c0c14,stroke:#ea580c,stroke-width:3px,color:#fcd9b6
    style B fill:#18181b,stroke:#fb923c,stroke-width:3px,color:#fff7ed
    style D fill:#18181b,stroke:#fb923c,stroke-width:3px,color:#fff7ed
    style E fill:#09090b,stroke:#16a34a,stroke-width:3px,color:#dcfce7
    style F fill:#09090b,stroke:#ef4444,stroke-width:3px,color:#fecaca
    style C fill:#0c0c14,stroke:#ea580c,stroke-width:3px,color:#fcd9b6
    style G fill:#0c0c14,stroke:#ea580c,stroke-width:3px,color:#fcd9b6
```

**Agent Requirements:**

1. Before `TaskUpdate(status="completed")`, verify all changes committed and pushed
2. Use `git status` and `git log origin/branch..HEAD` to check
3. Hook validation (`ralph.py`) blocks completion if push required

**Exception:** Read-only agents (reviewers, analyzers) that make no commits bypass this gate.

### Layer 7: VERIFY+FIX Phase

After implementation agents complete, VERIFY+FIX agents run before review:

```
PLAN → IMPLEMENT → VERIFY+FIX → REVIEW → COMPLETE
```

- Run build checks, type checks, lint
- Use Serena for symbol integrity verification
- Auto-fix simple issues (imports, types, formatting)
- Escalate complex issues via AskUserQuestion
- Do NOT leave TODO comments — fix or escalate
- Config: `agents/verify-fix.md`

## Hook Registration Table

All hooks registered in `settings.json`:

| Hook Event | Matcher | Handler | Timeout | Purpose |
|-----------|---------|---------|---------|---------|
| Setup | - | `token-guard.py check` | 60s | Validate Claude token before session |
| Setup | - | `setup.py validate-symlinks` | 30s | Verify symlink integrity |
| Stop | - | `ralph.py stop` | 30s | Cleanup Ralph state |
| Stop | - | `claudeChangeStop.js` | 5s | Save session state |
| SessionStart | startup\|resume | `utils.py model-capture` | 5s | Capture model ID for session |
| SessionStart | - | `ralph.py session-start` | 10s | Initialize Ralph session |
| PreCompact | - | `ralph.py pre-compact` | 10s | Save Ralph state before compaction |
| PreToolUse | Read | `auto-allow.py` | 5s | Auto-approve safe Read operations |
| PreToolUse | Bash | `security-gate.py pre-bash` | 5s | Security validation for Bash commands |
| PreToolUse | Bash | `git.py pre-commit-checks` | 5s | Git safety checks before commits |
| PreToolUse | MultiEdit\|Edit\|Write | `auto-allow.py` | 5s | Auto-approve safe edits |
| PreToolUse | MultiEdit\|Edit\|Write | `claudeChangePreToolUse.js` | 5s | Track file changes |
| PreToolUse | Task | `ralph.py hook-pretool` | 10s | Ralph task orchestration prep |
| PostToolUse | Bash | `git.py command-history` | 5s | Track git command history |
| PostToolUse | Edit\|Write | `git.py change-tracker` | 5s | Log file changes for commits |
| PostToolUse | Edit\|Write | `guards.py guardian` | 5s | Validate edit safety |
| PostToolUse | Edit\|Write | `guards.py plan-write-check` | 5s | Enforce plan change markers |
| PostToolUse | Edit\|Write | `guards.py insights-reminder` | 5s | Remind to update insights |
| PostToolUse | ExitPlanMode | `guards.py ralph-enforcer` | 10s | Validate Ralph protocol on plan exit |
| PostToolUse | Task | `ralph.py agent-tracker` | 10s | Track agent progress |
| PostToolUse | Skill | `guards.py skill-validator` | 5s | Validate skill invocation |
| PostToolUse | Skill | `post-review.py hook` | 30s | Post-review processing |
| UserPromptSubmit | ^/(?!start) | `guards.py skill-interceptor` | 5s | Parse skill commands |
| UserPromptSubmit | ^/start | `guards.py skill-parser` | 5s | Parse /start command args |
| UserPromptSubmit | - | `guards.py plan-comments` | 5s | Detect USER comments in plans |
| UserPromptSubmit | - | `guards.py auto-ralph` | 5s | Auto-trigger Ralph for complex tasks |
| SubagentStart | - | `ralph.py hook-subagent-start` | 10s | Initialize subagent context |
| SubagentStop | - | `ralph.py hook-subagent-stop` | 10s | Cleanup subagent state |
| Notification | permission_prompt | `utils.py notify` | 10s | Desktop notifications |

**Note:** All hooks with Phase 1 are critical path. SubagentStart/Stop hooks run for team agents.

## Agent Frontmatter Fields

Agent config files (`agents/*.md`) support these frontmatter fields:

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Agent identifier (required) |
| `specialty` | string | Domain specialty for auto-assignment |
| `disallowedTools` | list | Tools this agent cannot use (reviewers: `[Write, Edit, MultiEdit]`) |
| `description` | string | When to invoke this agent |

**Auto-assignment:** `match_agent_to_task()` in ralph.py scores tasks against `AGENT_SPECIALTIES` keyword lists to assign the best-fit agent config.

## Performance Tracking

Ralph tracks per-agent metrics via `PerformanceTracker`:

| Metric | Description |
|--------|-------------|
| `cost_usd` | API cost per agent |
| `num_turns` | API round-trips per agent |
| `duration_seconds` | Wall-clock time per agent |
| `avg_cost_per_agent` | Mean cost across completed agents |

Progress file: `.claude/ralph/progress.json` (includes `performance` summary)

### Budget Guard

Use `--budget` flag to cap total spending:

```bash
ralph.py loop 10 3 --budget 5.00 "Implement feature"
```

When cumulative cost exceeds the budget, remaining agents are skipped with `BUDGET` status.

## Serena Semantic Code Tools

Serena provides LSP-powered semantic code analysis. **Prefer Serena tools over text-based alternatives** for code understanding and manipulation.

### When to Use Serena

| Task                           | Serena Tool                               | Instead of          |
| ------------------------------ | ----------------------------------------- | ------------------- |
| Find function/class by name    | `mcp__serena__find_symbol`              | `Grep`            |
| Get file structure overview    | `mcp__serena__get_symbols_overview`     | `Read` full file  |
| Find all callers of a function | `mcp__serena__find_referencing_symbols` | `Grep` for name   |
| Rename symbol across codebase  | `mcp__serena__rename_symbol`            | Multi-file `Edit` |
| Replace function body          | `mcp__serena__replace_symbol_body`      | `Edit` tool       |
| Insert code after symbol       | `mcp__serena__insert_after_symbol`      | `Edit` tool       |
| Search with code context       | `mcp__serena__search_for_pattern`       | `Grep`            |

### Serena Workflow

1. **Before reading files**: Use `get_symbols_overview` to understand structure
2. **Finding code**: Use `find_symbol` with `name_path_pattern`
3. **Impact analysis**: Use `find_referencing_symbols` before modifying
4. **Editing symbols**: Use `replace_symbol_body` (preserves formatting)
5. **Cross-file renames**: Use `rename_symbol` (atomic, LSP-powered)

### Serena Memory

| Tool                           | Purpose                                   |
| ------------------------------ | ----------------------------------------- |
| `mcp__serena__write_memory`  | Save architectural decisions, symbol maps |
| `mcp__serena__read_memory`   | Recall project context                    |
| `mcp__serena__list_memories` | See available memory files                |
| `mcp__serena__edit_memory`   | Update existing memory                    |

### Serena Think Tools

| Tool                                               | When to Use                 |
| -------------------------------------------------- | --------------------------- |
| `mcp__serena__think_about_collected_information` | After gathering context     |
| `mcp__serena__think_about_task_adherence`        | Before making changes       |
| `mcp__serena__think_about_whether_you_are_done`  | Before reporting completion |

## Agent Teams (In-Process)

Experimental feature enabling parallel Claude Code instances within a session.

### Configuration

Enabled via `settings.json`:
- `"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"` in env block

In-process mode only. Split-pane mode requires tmux (not available natively on Windows).

### Keyboard Shortcuts

| Shortcut | Action |
| -------- | ------ |
| `Shift+Tab` | Delegate mode (lead coordinates, no code) |
| `Shift+Up/Down` | Select teammate to message |
| `Ctrl+T` | Toggle task list |

### Cleanup Workflow

Manual cleanup required after team sessions:

1. Shut down each teammate: "Ask the {name} teammate to shut down"
2. Lead calls `TeamDelete()` to remove `~/.claude/teams/{name}/` and `~/.claude/tasks/{name}/`

### When to Use

| Scenario | Tool |
| -------- | ---- |
| Parallel research, multi-perspective reviews | Agent Teams |
| Implementation loops, VERIFY+FIX, push-gated | Ralph (`/start`) |
| Competing hypotheses, architecture exploration | Agent Teams |
| Sequential task execution with review | Ralph (`/start`) |

### Ralph Compatibility

- Teammates are full Claude Code instances (load CLAUDE.md, hooks, skills)
- Ralph hooks fire per-teammate (ralph.py, guards.py all execute)
- Task() subagents work inside teammates
- "No nested teams" = teammates can't spawn their OWN teams
- Token cost: each teammate = full instance

### Limitations

- No session resumption after team ends
- One team per session
- No nested teams (teammates can't create sub-teams)
- Lead agent is fixed (can't change lead)

### Idle Notification Handling

**Note:** Message types (`idle_notification`, `task_completed`) are auto-delivered by the system. They are NOT hookable events — do not add them to settings.json hooks.

For high-agent-count scenarios (Ralph), filter with:
- **Message filter**: Skip messages where `type == "idle_notification"`
- **Prompt suppression**: Include "Do NOT send idle notifications" in agent prompts

## Auto Memory

Claude Code automatically persists learnings across conversations.

### How It Works

- **Directory:** `~/.claude/projects/{project}/memory/MEMORY.md`
- **System prompt injection:** First 200 lines of `MEMORY.md` are included in every system prompt
- **Topic files:** Create separate files (e.g., `debugging.md`, `patterns.md`) and link from MEMORY.md
- **Auto-updates:** Claude writes insights as it works — no manual config needed

### Best Practices

- Keep `MEMORY.md` concise (under 200 lines) — overflow goes to linked topic files
- Organize by topic, not chronologically
- Record: problem constraints, strategies that worked/failed, lessons learned
- Update or remove memories that become wrong or outdated

### vs Serena Memories

| Feature | Auto Memory | Serena Memory |
| ------- | ----------- | ------------- |
| Storage | `~/.claude/projects/*/memory/` | Serena's internal memory store |
| Scope | Per-project, auto-loaded | Per-project, manual read |
| Access | System prompt (always visible) | `mcp__serena__read_memory` |
| Write | `Edit`/`Write` tools | `mcp__serena__write_memory` |
| Use case | Quick-reference patterns | Detailed architectural notes |

Both systems are complementary — use Auto Memory for high-frequency patterns, Serena for deep architectural context.
