# Claude Code Configuration

![Ralph Team - 10 parallel agents with custom statusline](claude-readme.png)

Production [Claude Code](https://docs.anthropic.com/en/docs/claude-code) configuration with multi-agent orchestration, autonomous development workflows, and defense-in-depth safety layers.

## Features

| Category | Count | Highlights |
|----------|-------|------------|
| Skills | 21 | `/start`, `/review`, `/commit`, `/openpr`, `/x`, `/nightshift`, `/docx`, `/docker`, `/ask`, `/test`, `/sounds` |
| Agents | 42 | Specialist (Opus), reviewer (Sonnet), ops (Sonnet), git coordinator (Haiku) |
| Hooks | 15 | Security gate, auto-allow, change tracking, Ralph orchestration, ACID state, sound effects |
| Scripts | 28 | Token management, Chrome MCP fix, statusline, session repair, PR aggregation |
| Safety | 7 layers | Push gate, VERIFY+FIX, security hooks, budget guard, ACID transactions |
| Model Routing | 3 layers | Global default, skill fork, per-agent override for cost optimization |

## Quick Start

```bash
# 1. Clone
git clone https://github.com/bosmadev/claude.git ~/.claude

# 2. Run Claude Code — auto-generates .claude.json on first launch
claude

# 3. Configure settings.json — replace %USERPROFILE% with your home directory
#    Edit ~/.claude/settings.json for hook paths and permissions

# 4. Install Python dependencies
uv pip install portalocker
```

> **Note:** `.claude.json.example` is a **reference template only** — Claude Code auto-generates `.claude.json` on first run. Do not copy the example file.

---

## Skills Reference

### /start - Ralph Autonomous Development

| Command | Description |
|---------|-------------|
| `/start` | 3 agents, 3 iterations, Opus, plan mode |
| `/start [task]` | 3 agents, 3 iterations with task |
| `/start [N]` | N agents, 3 iterations |
| `/start [N] [M]` | N agents, M iterations |
| `/start [N] [M] [task]` | N agents, M iterations with task |
| `/start sonnet [task]` | Sonnet plan, Opus impl |
| `/start sonnet all [task]` | Sonnet ALL phases (budget mode) |
| `/start [N] [M] sonnet [task]` | N agents, M iter, Sonnet plan, Opus impl |
| `/start [N] [M] noreview [task]` | Skip post-implementation review |
| `/start [N] [M] review` | Review-only mode (entire codebase) |
| `/start [N] [M] review [path]` | Review-only mode (specific path) |
| `/start [N] [M] review [rN] [rM] [task]` | Custom review: rN agents, rM iterations |
| `/start [N] [M] import <source>` | Import from PRD/YAML/GitHub |
| `/start help` | Show usage |

All implementation agents must push their work to remote before completion (Push Gate enforcement).

### /review - Multi-Aspect Code Review

| Command | Description |
|---------|-------------|
| `/review` | 10 agents, 3 iter, Sonnet 4.5, working tree |
| `/review [N] [M]` | N agents, M iterations, Sonnet 4.5 |
| `/review [N] [M] opus` | N agents, M iterations, Opus 4.5 |
| `/review [N] [M] haiku` | N agents, M iterations, Haiku |
| `/review working` | Working tree only (R1 scope) |
| `/review impact` | Working tree + impact radius (R2) |
| `/review branch` | Full branch diff since main (R3) |
| `/review pr [number]` | Review specific PR |
| `/review security` | Security-focused OWASP audit |
| `/review security --owasp` | Full OWASP Top 10 audit |
| `/review help` | Show usage |

### /commit - Git Commit Workflow

| Command | Description |
|---------|-------------|
| `/commit` | Generate pending-commit.md (scope: description) |
| `/commit confirm` | Execute pending commit + auto-cleanup |
| `/commit abort` | Cancel pending commit |
| `/commit show` | Show pending changes |
| `/commit clear` | Clear change log |
| `/commit help` | Show usage |

Uses single-file sections format with scope-prefix style. Organized by file path with bullet points of changes.

### /openpr - Create Pull Request

| Command | Description |
|---------|-------------|
| `/openpr` | Create PR to main |
| `/openpr [branch]` | Create PR to branch |
| `/openpr help` | Show usage |

Uses `scripts/aggregate-pr.py` for commit aggregation with build ID extraction. Does NOT automatically invoke `/review` — run review separately before PR creation.

### /init-repo - Initialize Repository for Claude Code

| Command | Description |
|---------|-------------|
| `/init-repo` | Interactive setup — prompts for each step |
| `/init-repo workflows` | Install GitHub workflows only |
| `/init-repo all` | Full setup (workflows + .gitignore) |
| `/init-repo help` | Show usage |

Installs `.github/workflows/claude.yml`, `.claude/` directory structure, and updated `.gitignore` with Claude patterns.

### /repotodo - Process TODO Comments by Priority

| Command | Description |
|---------|-------------|
| `/repotodo list` | List all TODOs by priority |
| `/repotodo P1 all` | Process all P1 (critical) TODOs |
| `/repotodo P1 all --verify` | Process all P1 TODOs + VERIFY+FIX agents |
| `/repotodo P1 [N]` | Process first N P1 TODOs |
| `/repotodo P2 all` | Process all P2 (high priority) TODOs |
| `/repotodo P2 all --verify` | Process all P2 + VERIFY+FIX agents |
| `/repotodo P3 all` | Process all P3 (medium priority) TODOs |
| `/repotodo P3 all --verify` | Process all P3 + VERIFY+FIX agents |
| `/repotodo low all` | Process all low priority (plain TODO:) |
| `/repotodo low all --verify` | Process all low + VERIFY+FIX agents |
| `/repotodo all` | Process ALL TODOs (P1 > P2 > P3 > low) |
| `/repotodo all --verify` | Process ALL + VERIFY+FIX agents |
| `/repotodo verify` | Check alignment: review findings vs source TODOs |
| `/repotodo verify --fix` | Verify + inject missing TODOs from findings |
| `/repotodo help` | Show usage |

TODO format: `TODO-P1:`, `TODO-P2:`, `TODO-P3:`, or plain `TODO:`

### /reviewplan - Process Plan USER Comments

| Command | Description |
|---------|-------------|
| `/reviewplan` | Process all USER comments in /plans/ |
| `/reviewplan [path]` | Process specific plan file |
| `/reviewplan help` | Show usage |

### /launch - Visual App Verification

| Command | Description |
|---------|-------------|
| `/launch` | Start server + visual verification |
| `/launch --only <browser>` | Single browser (chrome-mcp/playwriter/system) |
| `/launch help` | Show usage |

### /screen - Screenshot Management

| Command | Description |
|---------|-------------|
| `/screen` | Capture region screenshot |
| `/screen [N]` | Review last N screenshots |
| `/screen list` | List all with metadata |
| `/screen clean` | Delete screenshots older than 7 days |
| `/screen analyze [id]` | Analyze screenshot |
| `/screen delete [id]` | Delete screenshot |
| `/screen help` | Show usage |

### /youtube - Video Transcription

| Command | Description |
|---------|-------------|
| `/youtube <url>` | Transcribe video |
| `/youtube list` | List transcriptions |
| `/youtube delete <id>` | Delete transcription |
| `/youtube delete all` | Delete all |
| `/youtube help` | Show usage |

### /token - Claude GitHub Token Management

| Command | Description |
|---------|-------------|
| `/token` or `/token status` | Show token expiry and repo status |
| `/token refresh` | Refresh if expiring soon |
| `/token refresh --force` | Force refresh regardless of expiry |
| `/token sync` | Push token to current repo secrets |
| `/token sync all` | Push token to all detected repos |
| `/token help` | Show usage |

### /test - Unified Test Framework

| Command | Description |
|---------|-------------|
| `/test generate <file>` | Generate test file (auto-detect vitest/pytest) |
| `/test coverage` | Run coverage report |
| `/test mutate <file>` | Mutation testing preview |
| `/test all` | Run all test suites (vitest → pytest) |
| `/test help` | Show usage |

Auto-detects framework based on file extension: `.ts/.tsx` → vitest, `.py` → pytest.

### /rule - Behavior Rule Management

| Command | Description |
|---------|-------------|
| `/rule add` | Add behavior rule via interactive TUI |
| `/rule list` | List all rules from settings.json |
| `/rule remove` | Remove rule pattern from settings.json |
| `/rule help` | Show usage |

Manages Claude Code behavior rules via direct `settings.json` modifications. Translates natural language rules into `permissions.deny` or `permissions.ask` patterns.

### /chats - Session Management

| Command | Description |
|---------|-------------|
| `/chats` or `/chats list` | List recent sessions with metadata |
| `/chats clean` | Clean orphaned session artifacts |
| `/chats help` | Show usage |

### /docx - Document Processing

| Command | Description |
|---------|-------------|
| `/docx read <file>` | Extract text/markdown from DOCX/PDF/XLSX |
| `/docx write <file>` | Create DOCX from markdown content |
| `/docx convert <input> <output>` | Convert between formats (xlsx→csv, docx→txt, pdf→txt) |
| `/docx template <template> <data.json>` | Fill DOCX template with JSON data |
| `/docx help` | Show usage |

Read, write, convert, and template-fill Word, PDF, and Excel documents. Auto-detects format by extension. Requires `python-docx`, `openpyxl`, `pypdf` packages.

### /docker - Docker Automation

| Command | Description |
|---------|-------------|
| `/docker generate <type>` | Generate production Dockerfile (nextjs\|python\|go\|node\|rust\|java) |
| `/docker compose <services>` | Generate docker-compose.yml (postgres\|redis\|mongo\|nginx\|mysql) |
| `/docker optimize <dockerfile>` | Analyze and suggest optimizations (layer count, multi-stage, cache) |
| `/docker security <dockerfile>` | Security audit (root user, secrets, base image pinning) |
| `/docker help` | Show usage |

Generate Dockerfiles with multi-stage builds, minimal base images, and non-root users. Create compose stacks with health checks and persistent volumes.

### /ask - Multi-Model Query System

| Command | Description |
|---------|-------------|
| `/ask "question"` | Single model query (gemini-2.0-flash) |
| `/ask "question" --models gpt-4o` | Query specific model |
| `/ask "question" --mode consensus --models gemini-2.0-flash,gpt-4o` | Multi-model consensus |
| `/ask "question" --mode codereview --models gemini-2.0-flash,gpt-4o` | Multi-model code review |
| `/ask "question" --timeout 60` | Custom timeout (seconds) |
| `/ask "question" --format json` | JSON output (also: table, markdown) |
| `/ask help` | Show usage |

Query multiple AI models in parallel for comparison, consensus, or code review. Supports:
- **GSwarm/Gemini**: `gemini-2.0-flash`, `gemini-2.0-flash-thinking`, `gemini-1.5-pro` (via http://localhost:4000)
- **OpenAI**: `gpt-4o`, `gpt-4o-mini`, `o3-mini` (requires `OPENAI_API_KEY`)
- **Ollama**: `llama3.2`, `codellama`, `deepseek-coder` (via http://localhost:11434)

**Modes:**
- `chat` — Single model query (default)
- `consensus` — All models answer independently, side-by-side comparison
- `codereview` — Send code context to all models, aggregate findings

### /nightshift - Autonomous Maintenance

| Command | Description |
|---------|-------------|
| `/nightshift init <repo>` | Create night-dev branch + worktree |
| `/nightshift start <repo> [task]` | Spawn autonomous agents in night-dev worktree |
| `/nightshift start <repo> [task] --agents N` | N parallel agents (default: 3) |
| `/nightshift start <repo> [task] --budget $X` | Budget cap in USD (default: $5.00) |
| `/nightshift start <repo> [task] --model opus\|sonnet` | Agent model (default: sonnet) |
| `/nightshift stop` | Send shutdown to all active agents |
| `/nightshift status` | Show active agents and progress |
| `/nightshift help` | Show usage |

Nighttime development cycles with scout agents that research online, implement features, and submit PRs to dev branches. Supports pulsona and gswarm repos initially.

### /x - X/Twitter Outreach

| Command | Description |
|---------|-------------|
| `/x research {TOPIC}` | Explore X queries, rank by engagement |
| `/x research [N] [model] {TOPIC}` | N parallel agents for research |
| `/x post {TEXT with URL}` | Compose unique replies, post via X API |
| `/x post [N] [model] {TEXT}` | N parallel agents for posting |
| `/x compose` | Scrape news, compose original tweet, distribute via replies |
| `/x news` | Show current news feed stats |
| `/x history` | Show posting history |
| `/x history --days N` | Show history for last N days |
| `/x history --topic T` | Filter history by topic |
| `/x status` | Show daily/weekly counts + reach |
| `/x scrape` | Run scraper now, update feed.json |
| `/x feed` | Show current auto-generated feed (queries + news) |
| `/x scheduler install [N]` | Install auto-scraper (every N hours, default 6) |
| `/x scheduler status` | Show scheduler + feed freshness |
| `/x scheduler uninstall` | Remove auto-scraper |
| `/x auto [N] [model]` | Headless auto-run: scrape + research + post |
| `/x github` | GitHub-to-X pipeline: scan repos/issues, map users to X handles, generate queries |
| `/x github --search` | Same + search X API for each generated query |
| `/x help` | Show usage |

Automated X/Twitter outreach with four modes:

- **Post mode** — Find high-engagement targets on X, compose unique replies, post via X API (1-2 sec/post) with Chrome MCP fallback
- **Compose mode** — Scrape news from 15+ sources (Google News RSS, GitHub API, Messari crypto API, changelogs), compose an original tweet on your profile, then distribute by replying to related conversations with the original tweet URL
- **Research mode** — Explore X search queries and rank by engagement for future targeting
- **GitHub mode** — Scan GitHub trending repos, cost issues, and releases; map users to X handles via API; generate targeted search queries for posting

**Configuration:** Auto-generated from `skills/x/.env` (gitignored). Set `X_SHARE_URL`, `X_HANDLE`, `X_PROJECT_NAME`, `X_PROJECT_DESC`, plus X auth tokens. No manual `config.json` creation needed — auto-generates on first run.

**News sources:** Google News RSS (AI, coding, crypto), Google Cloud feeds, GitHub trending repos + cost-related issues + releases, Messari API (optional), markdown changelogs (Claude Code, Next.js, VS Code).

**Scraper scheduler:** `python skills/x/scripts/x.py scraper-install [HOURS]` installs a Windows Task Scheduler job to keep `feed.json` fresh (default: every 6 hours).

**Model routing:** Default Sonnet for ALL /x operations. Never use Opus — continuous posting loops burn weekly quota. `[N]` = parallel agents (default 1), `[model]` = `opus`/`sonnet`/`haiku`.

**Backend architecture:** X HTTP API is primary (1-2 sec/post). Chrome MCP is fallback for visual research, For You feed scanning, and auth expiry recovery.

**Quality guard:** `sanitize_reply_text()` runs before every post — strips non-ASCII encoding artifacts, blocks banned words/phrases, validates formatting (no ALL CAPS, no hashtag spam >2, no excessive punctuation).

**Security audit:** `x-post-check` hook logs all Chrome MCP clicks during `/x` sessions to `~/.claude/security/x-clicks.log`. Activated via `.claude/.x-session` flag file.

### /sounds - Audio Feedback

| Command | Description |
|---------|-------------|
| `/sounds on` | Enable audio feedback (creates marker file) |
| `/sounds off` | Disable audio feedback (removes marker) |
| `/sounds status` or `/sounds` | Show current audio state |

Control audio feedback for Claude Code events:
- **Session Start** — 800Hz, 200ms
- **Tool Success** — 1000Hz, 100ms
- **Tool Failure** — 400Hz, 300ms
- **Permission Prompts** — 600Hz, 150ms (×2)
- **Git Commit** — 1200Hz, 150ms
- **Session Stop** — 500Hz, 400ms

Per-session toggle (does not persist across sessions). Audio never plays for subagents.

### /help - Help & Documentation

Shows available skills and usage information.


---

## Common Workflows

### Full Development Cycle

```
/start 10 3 [task description]
  -> Plan mode: Claude writes implementation plan
  -> Add USER: comments in plan file for feedback
  -> /reviewplan (repeat until satisfied)
  -> Approve plan
  -> 10 agents implement in parallel
  -> /review (post-implementation review)
  -> /commit
  -> /commit confirm
  -> /openpr
```

### Quick Fix

```
/start 3 2 [fix description]
  -> Plan + implement with 3 agents
  -> /commit
  -> /commit confirm
```

### Budget Mode (Sonnet)

```
/start 5 3 sonnet all [task]
  -> All phases use Sonnet 4.5 (cheaper)
  -> /commit
  -> /openpr
```

### Code Review Only

```
/review working         # Review uncommitted changes
/repotodo P1 all        # Fix critical TODOs
/commit
```

### Session Cleanup

```
/chats list             # See all sessions
/chats clean            # Clean orphaned artifacts
```

### Token Maintenance

```
/token status           # Check token expiry
/token refresh          # Refresh if needed
/token sync all         # Push to all repo secrets
```

---

## Statusline Guide

The custom statusline displays real-time session information in your terminal. Here's what each element means:

```
O4.6 ↑ ⚙ 42%  | 15%/287m | $1.23 | 5%/12% | ∷10 3/10:8O2S | main@a1b2c3 +2~1?3
```

### Elements

| Element | Example | Meaning |
|---------|---------|---------|
| **Model** | `O4.6` | Active model — O=Opus, S=Sonnet, H=Haiku, followed by version |
| **Effort** | `↑` | Effort level — `↑` High, `→` Med, `↓` Low (Opus only) |
| **Style** | `⚙` | Output style — `⚙` Engineer, `·` Default |
| **Context** | `42%` | Context window usage — green (<50%), yellow (<80%), red (80%+) |
| **Extended** | `/1M` | Suffix shown when using 1M extended context window |
| **Session Timer** | `15%/287m` | 5-hour session: usage percentage / minutes until reset |
| **Cost** | `$1.23` | Running session cost in USD |
| **Usage** | `5%/12%` | Sonnet weekly % / All models weekly % of quota |
| **Ralph** | `∷10 3/10:8O2S` | Team indicator: agent count, completed/total, model mix |
| **Git** | `main@a1b2c3` | Branch name @ short commit hash (clickable hyperlink) |
| **Git Status** | `+2~1?3` | `+` staged, `~` modified, `?` untracked file counts |
| **Git Remote** | `>>1<<2` | `>>` commits behind remote, `<<` commits ahead |

### Color Coding

| Color | Hex | Used For |
|-------|-----|----------|
| Salmon | `#d0886a` | Model name |
| Aurora Green | `#87a987` | Context (low usage), session timer |
| Aurora Yellow | `#e6c87a` | Context (medium usage), warnings |
| Aurora Red | `#b06060` | Context (high usage), errors |
| Grey | `#8a7e72` | Separators, secondary info |
| Snow White | `#d8d0c8` | Branch name |
| Cyan | `#d4956a` | Agent accent color |

### Ralph Section Details

When a Ralph team is active, the statusline shows:

| Part | Example | Meaning |
|------|---------|---------|
| `∷N` | `∷10` | Team indicator with agent count |
| `completed/total` | `3/10` | Tasks completed out of total |
| Model mix | `8O2S` | 8 Opus + 2 Sonnet agents |
| Struggle | `!!` | Alert when agents report difficulties |
| Build | `B11` | Current build number from CHANGELOG |

---

## Chrome MCP Fix (Windows)

Claude Code on Windows has a Chrome MCP integration issue where the auto-generated `chrome-native-host.bat` uses `claude.exe` (Bun standalone) which crashes on stdin piping.

### Problem

- Claude Code generates `chrome-native-host.bat` using the Bun standalone binary
- Bun cannot handle stdin piping required by Chrome's Native Messaging protocol
- Windows named pipe paths with spaces in usernames cause connection failures

### Solution

`scripts/fix-chrome-native-host.py` performs a 3-part fix:

1. **BAT rewrite** — Rewrites `chrome-native-host.bat` to use `node.exe` + `cli.js` instead of the Bun binary
2. **Pipe patch** — Patches `cli.js` `getSocketPaths()` to use `os.userInfo().username` for correct Windows named pipe paths
3. **Bridge disable** — Sets `tengu_copper_bridge: false` in `.claude.json` to force socket/pipe connection instead of broken WSS bridge

### Usage

Auto-runs as a `SessionStart` hook. For manual execution:

```bash
python ~/.claude/scripts/fix-chrome-native-host.py
```

After patching, restart your Claude Code session for the MCP server to load the updated `cli.js`.

---

## Architecture Overview

### Directory Structure

```
~/.claude/
├── .github/                    # GitHub templates and workflows
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── ISSUE_TEMPLATE/
│   └── workflows/claude.yml
├── agents/                     # Agent configuration files (25 files)
├── hooks/                      # Claude Code hook handlers (14 files)
├── output-styles/              # Response formatting styles
├── scripts/                    # CLI utilities (30+ scripts)
├── skills/                     # Skill definitions (21 skills)
├── plans/                      # Plan files from /start sessions
├── CLAUDE.md                   # Model knowledge (behavioral patterns)
├── settings.json               # Hook registrations and permissions
└── README.md                   # This file
```

### Hook System

Hooks intercept Claude Code events at different lifecycle stages:

| Stage | Examples | Purpose |
|-------|----------|---------|
| Setup/Stop | Token validation, symlink check | Session initialization and cleanup |
| SessionStart | Model capture, Ralph session init | Per-session setup |
| PreToolUse | Security gate, auto-allow, git safety | Block dangerous operations |
| PostToolUse | Change tracking, plan markers, insights | Track and validate edits |
| UserPromptSubmit | Skill parsing, plan comments | Intercept user commands |
| SubagentStart/Stop | Ralph orchestration | Track agent lifecycle |

#### Hook Registration Table

| Hook Event | Matcher | Handler | Timeout | Purpose |
|-----------|---------|---------|---------|---------|
| Setup | - | `token-guard.py check` | 60s | Validate Claude token before session |
| Setup | - | `setup.py validate-symlinks` | 30s | Verify symlink integrity |
| Stop | - | `ralph.py stop` | 30s | Cleanup Ralph state |
| Stop | - | `claudeChangeStop.js` | 5s | Save session state |
| Stop | - | `sounds.py session-stop` | 5s | Play session stop sound (async) |
| SessionStart | startup\|resume | `utils.py model-capture` | 5s | Capture model ID for session |
| SessionStart | - | `ralph.py session-start` | 10s | Initialize Ralph session |
| SessionStart | - | `sounds.py session-start` | 5s | Play session start sound (async) |
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
| PostToolUse | computer | `guards.py x-post-check` | 5s | Security audit: log Chrome clicks during /x sessions |
| PostToolUse | - | `sounds.py post-tool` | 5s | Play tool success/failure sound (async) |
| UserPromptSubmit | ^/(?!start) | `guards.py skill-interceptor` | 5s | Parse skill commands |
| UserPromptSubmit | ^/start | `guards.py skill-parser` | 5s | Parse /start command args |
| UserPromptSubmit | - | `guards.py plan-comments` | 5s | Detect USER comments in plans |
| UserPromptSubmit | - | `guards.py auto-ralph` | 5s | Auto-trigger Ralph for complex tasks |
| SubagentStart | - | `ralph.py hook-subagent-start` | 10s | Initialize subagent context |
| SubagentStop | - | `ralph.py hook-subagent-stop` | 10s | Cleanup subagent state |
| Notification | permission_prompt | `utils.py notify` | 10s | Desktop notifications |
| Notification | permission_prompt | `sounds.py notification` | 5s | Play notification sound (async) |

### Agent Inventory

| Category | Count | Model | Examples |
|----------|-------|-------|----------|
| Specialist | 7 | Opus | Go, Next.js, Python, refactor, OWASP, verify-fix, coordinator |
| Reviewer | 13 | Sonnet | A11y, API, architecture, commit, database, docs, performance, security |
| Ops | 6 | Sonnet | Build error, E2E, DevOps, scraper, PR generator, plan verifier |
| Git | 1 | Haiku | Lightweight git coordinator |

### Ralph Autonomous Development

Ralph is the multi-agent orchestration system invoked via `/start`:

1. **Plan Phase** — Claude analyzes the task and writes an implementation plan
2. **User Review** — Add `USER:` comments in plan, run `/reviewplan` to iterate
3. **Implementation** — N agents work in parallel via native Agent Teams
4. **VERIFY+FIX** — Build/type/lint checks with auto-fix
5. **Review** — Sonnet agents review all changes (TODO-P1/P2/P3 comments)
6. **Git** — Dedicated git-coordinator commits and pushes

**State machine (enforced in SKILL.md):**

```
IMPL_ACTIVE → RETRY_CHECK → VERIFY_FIX → REVIEW → SHUTDOWN → DONE
```

Team lead follows rigid state transitions — no skipping phases. `noreview` flag skips VERIFY_FIX + REVIEW, goes RETRY_CHECK → SHUTDOWN directly.

#### Ralph Safety Layers

```
┌─────────────────────────────────────────────────────────────────┐
│                     DEFENSE IN DEPTH (7 LAYERS)                  │
├─────────────────────────────────────────────────────────────────┤
│ Layer 1: Skill   → SKILL.md state machine, spawns agents         │
│ Layer 2: Hook    → Validates protocol, injects reminders         │
│ Layer 3: Context → Always-visible protocol rules                 │
│ Layer 4: Push Gate → MUST push before completion allowed         │
│ Layer 5: Exit    → Validates completion signals                  │
│ Layer 6: VERIFY+FIX → Build/type/lint checks + auto-fix         │
│ Layer 7: Review  → Sonnet agents audit all changes               │
└─────────────────────────────────────────────────────────────────┘
```

**Push Gate (Layer 4):** Agents MUST push before `TaskUpdate(completed)`. Check: `git log origin/branch..HEAD`. Read-only agents bypass. Hook validation in `ralph.py` blocks completion if push required.

**VERIFY+FIX (Layer 6):** Auto-fix imports/types/lint after implementation. Escalate complex issues. Config: `agents/verify-fix.md`.

#### Work-Stealing Queue

Ralph agents use atomic task claiming with `FileLock` to prevent idle agents:

```python
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

Queue file: `{project}/.claude/task-queue-{plan-id}.json`

#### Performance Tracking

Ralph tracks per-agent metrics via `PerformanceTracker`:

| Metric | Description |
|--------|-------------|
| `cost_usd` | API cost per agent |
| `num_turns` | API round-trips per agent |
| `duration_seconds` | Wall-clock time per agent |
| `avg_cost_per_agent` | Mean cost across completed agents |

Progress file: `.claude/ralph/progress.json`. Budget guard: `ralph.py loop 10 3 --budget 5.00 "task"` — caps total spending, remaining agents get `BUDGET` status.

### Security Layers

| Layer | Component | What It Does |
|-------|-----------|-------------|
| 1 | `security-gate.py` | Validates Bash commands against allowlist |
| 2 | `sandbox-boundary.py` | Prevents writes outside project boundaries |
| 3 | `auto-allow.py` | Auto-approves safe Read/Edit operations |
| 4 | `guards.py` | Plan integrity, Ralph protocol enforcement |
| 5 | Push Gate | Agents must push before marking complete |
| 6 | VERIFY+FIX | Post-implementation build/type/lint checks |
| 7 | Budget Guard | Caps total spending per Ralph session |

---

## GitHub Actions

The `.github/workflows/claude.yml` workflow provides AI-assisted PR automation, code review, and security audits.

### Trigger Methods

| Trigger | How to Use |
|---------|-----------|
| `@claude review` comment | Comment on issue or PR |
| `@claude review` in PR review | Submit PR review with comment |
| Issue assigned to `claude[bot]` | Assign in GitHub UI |
| `claude` label | Add label to PR |
| PR opened | Automatic on every new PR |
| Manual dispatch | Actions tab UI |

### Manual Dispatch Actions

| Action | Purpose |
|--------|---------|
| Summarize changes in this PR | Generate structured PR summary |
| Review code quality | Style, patterns, bugs, test coverage |
| Security audit (OWASP) | OWASP Top 10 security check |
| Custom prompt | Your own question/task |

### Model Options

| Model | Use Case |
|-------|----------|
| `claude-sonnet-4-5-20250929` | Default — best speed/quality balance |
| `claude-sonnet-4-5-20250929[1m]` | 1M context for large PRs |
| `claude-opus-4-6` | Maximum reasoning and analysis |
| `claude-haiku-4-5-20251001` | Budget fallback, simple tasks |

### Required Secrets

| Secret | Required | How to Get |
|--------|----------|-----------|
| `CLAUDE_CODE_OAUTH_TOKEN` | Yes | `claude auth login` then `/token sync` |
| `GITHUB_TOKEN` | Auto | Provided automatically by GitHub |

### Token Sync

```bash
# Authenticate Claude CLI
claude auth login

# Sync token to repository
/token sync         # Current repo only
/token sync all     # All detected repos
```

### Workflow Permissions

```yaml
permissions:
  id-token: write       # OIDC authentication
  contents: write       # Read code, update files
  issues: write         # Comment on issues
  pull-requests: write  # Comment on PRs
  actions: read         # Read workflow status
```

### Cost Optimization

| Scenario | Recommended Model |
|----------|------------------|
| Dependency PRs | Haiku |
| Documentation | Sonnet |
| Large refactors (100+ files) | Sonnet[1m] |
| Architecture review | Opus (high effort) |
| Security audit | Opus (high effort) |
| Style checks | Haiku |

### Troubleshooting

```bash
# View workflow runs
gh run list --workflow=claude.yml

# View specific run logs
gh run view <run-id> --log

# Check token
gh secret list
```

If authentication errors occur: `claude auth login` then `/token sync`.

---

## CHANGELOG Automation

Automated changelog generation via GitHub Actions workflow (`claude.yml`):

### Workflow

1. **@claude prepare** — Bot creates PR with aggregated commit summary and Build ID
2. **Review** — Team reviews PR via GitHub UI
3. **Squash Merge** — GitHub Actions generates CHANGELOG entry with badge + checkboxes
4. **Auto Release** — Creates git tag `v{version}` and GitHub Release with CHANGELOG notes

### CHANGELOG Entry Format

```markdown
---

## [![v{version}](https://img.shields.io/badge/v{version}-{date}--{date}-333333.svg)](https://github.com/bosmadev/{repo}/pull/{pr}) | Build {id}

{summary}

- [x] {change_1}
- [x] {change_2}
```

### Key Points

- Working branches do NOT edit CHANGELOG directly — all updates via GitHub Actions post-merge
- `changelog.ts` requires `Build N` in commit subject to trigger (format: `Build 3: feat: description`)
- `/commit` on main auto-reads CHANGELOG.md → injects `Build N+1`
- Feature branches: Build ID from branch name via `/openpr` squash merge
- Version bumping: `scripts/aggregate-pr.py --bump` with semantic versioning
- Override: `skip-changelog` or `skip-release` labels on PR

---

## Token Management

Token refresh uses defense-in-depth with 4 layers to survive laptop shutdown/sleep:

| Layer | Mechanism | Trigger |
|-------|-----------|---------|
| 1 | Task Scheduler | Every 30 minutes, "Start when available" |
| 2 | Resume Trigger | Power resume event |
| 3 | Login Profile | PowerShell profile load |
| 4 | Pre-op Check | Validates before Claude operations |

**Token lifetimes:** Access token ~2 hours, Refresh token ~1 year.

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/claude-github.py` | Main token management (status/refresh/sync) |
| `scripts/refresh-claude-token.py` | Task Scheduler wrapper (handles network wait) |
| `scripts/token-guard.py` | Pre-operation validation (Layer 4) |
| `scripts/install-token-timer.py` | Install Task Scheduler entries |

### Troubleshooting

| Issue | Solution |
|-------|---------|
| Token expired | `python ~/.claude/scripts/claude-github.py refresh --force` |
| Timer not running | `schtasks /Query /TN "ClaudeTokenRefresh"` |
| Manual refresh | `claude auth login` |
| Debug logs | Check `~/.claude/debug/token-refresh.log` |

---

## MCP Servers

| Server | Type | Purpose |
|--------|------|---------|
| `playwriter` | stdio | Browser automation via Playwright — auth flows, sessions, visual testing |
| `context7` | stdio | Up-to-date documentation and code examples for any library |
| `claude-in-chrome` | stdio | Chrome DevTools integration — debug, inspect, console access |

Configured in `.claude.json` under `mcpServers`. See `.claude.json.example` for reference configuration.

---

## Agent Teams

Experimental feature enabling parallel Claude Code instances within a session.

**Configuration:** `"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"` in `settings.json` env block. In-process mode only (no tmux on Windows).

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Shift+Tab` | Delegate mode (lead coordinates, no code) |
| `Shift+Up/Down` | Select teammate to message |
| `Ctrl+T` | Toggle task list |

### When to Use

| Scenario | Tool |
|----------|------|
| Parallel research, multi-perspective reviews | Agent Teams |
| Implementation loops, VERIFY+FIX, push-gated | Ralph (`/start`) |
| Competing hypotheses, architecture exploration | Agent Teams |
| Sequential task execution with review | Ralph (`/start`) |

### Compatibility & Limitations

- Teammates are full Claude Code instances (load CLAUDE.md, hooks, skills)
- Ralph hooks fire per-teammate (ralph.py, guards.py all execute)
- Task() subagents work inside teammates
- No nested teams, no session resumption, one team per session, fixed lead
- Idle notifications (`idle_notification`, `task_completed`) are auto-delivered — NOT hookable events

### Cleanup

1. Shut down each teammate via `SendMessage(type="shutdown_request")`
2. Lead calls `TeamDelete()` to remove `~/.claude/teams/{name}/` and `~/.claude/tasks/{name}/`

---

## Complete Model Routing Matrix

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
| `/x` | Sonnet 4.5 | N/A | 200K | L2 | Fork, X/Twitter outreach |
| `/x` agents | Sonnet 4.5 | N/A | 200K | L3 | Never Opus (continuous loops burn quota) |
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

**Legend:** Effort: Low/Med/High (Opus only). Layer: L1 = Global default, L2 = Skill fork, L3 = Per-agent override, .md = Agent config. [1m] = Extended 1M context.

---

## Configuration Files

| File | Purpose | Notes |
|------|---------|-------|
| `.claude.json` | Claude Code runtime config | Auto-generated on first run. **Do not copy** `.claude.json.example` |
| `.claude.json.example` | Reference template | Shows structure with sanitized values |
| `settings.json` | Hook registrations, permissions, env vars | Edit paths for your system |
| `.gitignore` | Git exclusions | Ignores sessions, cache, temp files |
| `CODEOWNERS` | GitHub code ownership | Requires owner approval for PRs |

---

## For Claude Code

See [CLAUDE.md](./CLAUDE.md) for behavioral patterns and conventions. Reference tables (hook registration, model routing matrix, Ralph internals, Agent Teams, CHANGELOG) are in this README — CLAUDE.md contains compact summaries with links back here.
