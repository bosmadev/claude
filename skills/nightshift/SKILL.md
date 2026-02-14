---
name: nightshift
description: "Autonomous maintenance skill for nighttime development cycles -- spawns scout agents in night-dev worktrees to research, implement features, and submit PRs to dev branches."
argument-hint: "init <repo> | start <repo> [task] [--agents N] [--budget $X] | stop | status | help"
user-invocable: true
context: fork
---

# Nightshift Skill

**FIRST ACTION:** When this skill is invoked, immediately output: `**SKILL_STARTED:** nightshift`

This signal MUST be emitted before any parsing, logic, or analysis begins.

## Overview

Nightshift enables **continuous autonomous development** during off-hours. It spawns scout agents in dedicated night-dev worktrees that **work indefinitely** until explicitly stopped.

**Continuous Operation Model:**

Agents loop forever: **Research → Implement → Commit → Push → Research → ...**

- Agents NEVER stop automatically
- Agents NEVER create PRs themselves
- Agents WORK SILENTLY with no status reports (like /x agents)
- Only `/nightshift stop` triggers shutdown + PR creation

**What Agents Do:**

- Research online for improvements (WebSearch/WebFetch)
- Implement features based on findings
- Run lint-fix, refactoring, dependency updates
- Commit and push changes (using /commit skill)
- Immediately start researching next improvement
- **Continue indefinitely** until shutdown_request received

**Branch Model:**

```
main <-(PR)- *-dev <-(PR)- *-night-dev
     reset after     reset after
     merge to main   merge to *-dev
```

**Worktree Structure:**

```
D:/source/{repo}/                  # Bare repo
D:/source/{repo}/main/             # main branch worktree
D:/source/{repo}/{repo}-dev/       # *-dev branch worktree
D:/source/{repo}/{repo}-night-dev/ # *-night-dev branch worktree (created by nightshift)
```

**Supported Repos:** pulsona, gswarm (initial set)

---

## Argument Parsing

From `$ARGUMENTS`, parse subcommands:

| Subcommand | Format | Description |
|------------|--------|-------------|
| `init <repo>` | `/nightshift init pulsona` | Create night-dev branch + worktree if not exists |
| `start <repo> [task]` | `/nightshift start pulsona lint-fix --agents 3` | Spawn agents in night-dev worktree |
| `stop` | `/nightshift stop` | Send shutdown to all active nightshift agents |
| `status` | `/nightshift status` | Show active agents and progress |
| `help` | `/nightshift help` | Show usage |

### Start Subcommand Options

| Flag | Default | Description |
|------|---------|-------------|
| `--agents N` | 3 | Number of parallel agents |
| `--budget $X` | $5.00 | Maximum total spending (triggers BUDGET_EXCEEDED, doesn't stop agents) |
| `--model opus\|sonnet\|gemini` | sonnet | Agent model: opus (expensive), sonnet (default), gemini (via GSwarm, future) |

**Examples:**

```bash
/nightshift init pulsona
/nightshift start pulsona "research Next.js 15 features + implement"
/nightshift start gswarm lint-fix --agents 5 --budget $10.00
/nightshift status
/nightshift stop
```

---

## Implementation Protocol

### Init Flow

When `init <repo>` invoked:

1. Call `scripts/nightshift.py init <repo>`
2. Script checks if `{repo}-night-dev` branch exists
3. If not: create from `{repo}-dev` and set up worktree
4. Output: `✓ {repo}-night-dev initialized at D:/source/{repo}/{repo}-night-dev/`

### Start Flow

When `start <repo> [task]` invoked:

1. Validate repo has been initialized (`init` check)
2. Call `scripts/nightshift.py start <repo> [task] --agents N --budget $X --model MODEL`
3. Script spawns N agents with Task() in night-dev worktree directory
4. Each agent receives this continuous operation prompt:

```
You are a nightshift scout agent. Work CONTINUOUSLY until you receive a shutdown_request.

Your loop:
1. Research improvements (WebSearch/WebFetch for best practices, framework updates)
2. Implement changes in the night-dev worktree
3. Use /commit to commit and push changes (branch-aware, auto Build ID)
4. IMMEDIATELY start researching the next improvement
5. REPEAT FOREVER until shutdown_request

CRITICAL RULES (like /x agents):
- NEVER stop to create PRs (team-lead creates PR when you're shut down)
- NEVER report progress or status ("posted X commits", "continuing...")
- WORK SILENTLY with no status updates
- NEVER wait or pause between commits
- After pushing a commit, IMMEDIATELY start next research cycle
- Only stop when you receive shutdown_request message

Task focus: {task_description}
Budget: ${budget_per_agent:.2f} (soft limit, triggers warning but don't stop)
Model: {model}
Worktree: {worktree_path}
```

5. Agents work continuously until `/nightshift stop` is invoked
6. Monitor progress via `nightshift.py status`

### Stop Flow

When `stop` invoked:

1. Call `scripts/nightshift.py stop`
2. Script sends `SendMessage(type="shutdown_request")` to all tracked agents
3. Wait for shutdown confirmations
4. **After all agents stopped:** Auto-create PR from `{repo}-night-dev` to `{repo}-dev`
   - Use `/openpr` skill (branch-aware, Build ID)
   - PR body includes: summary of all commits made during session, agent count, total spend
5. Output:
   ```
   ✓ All nightshift agents stopped
   ✓ PR created: https://github.com/user/{repo}/pull/{pr_number}

   Session summary:
   - 3 agents ran for 8.5 hours
   - 47 commits pushed
   - $12.34 total spend
   ```

### Status Flow

When `status` invoked:

1. Call `scripts/nightshift.py status`
2. Output: Active agents, their tasks, progress metrics (cost, turns, duration)

---

## Agent Capabilities

Nightshift agents are **continuous scouts** operating like /x agents:

| Capability | Description |
|------------|-------------|
| Continuous operation | Loop forever: research → implement → commit → research → ... |
| Online research | Use WebSearch/WebFetch for best practices, framework updates |
| Feature implementation | Code new features based on research findings |
| Maintenance | Lint-fix, refactor, dependency updates |
| Proper git workflow | Use /commit skill (branch-aware, Build ID injection, auto-push) |
| Silent operation | No status reports, no progress updates (WORK SILENTLY like /x) |
| Graceful shutdown | Respond to shutdown_request with SendMessage(type="shutdown_response") |

**Example continuous agent behavior:**

```
[Cycle 1] Research Next.js 15 App Router → Implement parallel routes → Commit → Push
[Cycle 2] Research Turbopack → Migrate webpack config → Commit → Push
[Cycle 3] Research Server Actions → Add form handlers → Commit → Push
[Cycle 4] Lint-fix components → Commit → Push
[Cycle 5] Research Metadata API → Update SEO tags → Commit → Push
... (continues until shutdown_request)
```

Agents NEVER stop to create PRs. Team-lead creates PR via `/openpr` when `/nightshift stop` is invoked.

---

## Continuous Operation Protocol

Nightshift agents follow the **same protocol as /x agents** for continuous, autonomous work:

### NO IDLE STATES

- Agents MUST be actively working 100% of the time
- If idle >10 seconds, agent is failing protocol
- After completing a commit: IMMEDIATELY start next research cycle
- No waiting, no reporting delays

### WORK SILENTLY

- NEVER report progress ("posted X commits", "continuing to milestone Y")
- NEVER send status updates to team-lead
- Work in complete silence until shutdown_request received
- Let commits speak for themselves

### Continuous Loop

```
1. Research improvements (WebSearch/WebFetch)
2. Implement changes
3. Commit with /commit (auto-push)
4. GOTO 1 (no pause, no reporting)
```

### When to Stop

- ONLY stop when you receive shutdown_request message (JSON with `type: "shutdown_request"`)
- Respond with SendMessage(type="shutdown_response", request_id={from message}, approve=true)
- Budget warnings trigger alerts but DON'T stop agents
- Empty research results → broaden search terms → retry IMMEDIATELY

### Failure Modes to AVOID

| Anti-Pattern | Why It's Wrong | Correct Behavior |
|--------------|----------------|------------------|
| "I've committed 5 changes, continuing..." | Creates idle state | Just commit and move to next research |
| Stopping after N commits | Violates continuous protocol | Work until shutdown_request |
| Waiting for team-lead approval | Not autonomous | Research → implement → commit → repeat |
| Creating PRs | Agents don't create PRs | Only commit/push, team-lead creates PR on stop |

---

## Safety Layers

Nightshift agents inherit all 7 Ralph safety layers:

1. **Skill** - SKILL.md state machine
2. **Hook** - Protocol validation
3. **Context** - Always-visible rules
4. **Push Gate** - MUST push before completion
5. **Exit** - Validates completion signals
6. **VERIFY+FIX** - Build/type/lint checks
7. **Review** - Post-implementation audit (optional)

**Budget Guard:** `--budget $X` triggers warning when exceeded but agents KEEP WORKING (continuous operation priority).

**Continuous Operation:** Agents inherit /x WORK SILENTLY protocol - no idle states, no status reports, just continuous loop.

**Bypass-Permissions Profile:** Agents run with `NIGHTSHIFT_AGENT=1` and `NIGHTSHIFT_WORKTREE=<path>` env vars. This enables broad dev tooling (pip, npm, git, python, build tools) while protecting `main`/`*-dev` branches, other repos, Docker containers, and system files. See `guards.py bypass-permissions-guard` for allowlist details.

---

## Automation Integration

### GitHub Actions: Night-Dev Reset

Extends `.github/workflows/reset-dev.yml` to reset `*-night-dev` branches after PR merge to `*-dev`:

```yaml
jobs:
  reset-night-dev:
    if: >-
      github.event.pull_request.merged == true &&
      endsWith(github.event.pull_request.head.ref, '-night-dev')
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0
      - name: Reset night-dev branch to dev
        run: |
          BRANCH="${{ github.event.pull_request.head.ref }}"
          BASE_BRANCH="${{ github.event.pull_request.base.ref }}"
          echo "Resetting $BRANCH to match $BASE_BRANCH..."
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git fetch origin "$BRANCH"
          git checkout "$BRANCH"
          git reset --hard "origin/$BASE_BRANCH"
          git push --force origin "$BRANCH"
          echo "✓ $BRANCH reset to $BASE_BRANCH"
```

---

## Configuration

No manual config needed. Uses bare repo paths from environment:

| Repo | Bare Repo | Night-Dev Worktree |
|------|-----------|-------------------|
| pulsona | D:/source/pulsona/ | D:/source/pulsona/pulsona-night-dev/ |
| gswarm | D:/source/gswarm/ | D:/source/gswarm/gswarm-night-dev/ |

**State tracking:** `~/.claude/nightshift/state.json` (active agents, budgets, timestamps)

---

## Output Format

```bash
# Init
$ /nightshift init pulsona
Checking D:/source/pulsona/ for night-dev branch...
✓ pulsona-night-dev branch created from pulsona-dev
✓ Worktree set up at D:/source/pulsona/pulsona-night-dev/
Ready for nightshift agents.

# Start (continuous mode)
$ /nightshift start pulsona "research Next.js 15" --agents 3 --budget $5.00
Spawning 3 nightshift agents in D:/source/pulsona/pulsona-night-dev/
Budget: $5.00 (soft limit)
Model: sonnet
Task focus: research Next.js 15

⚠️  Agents will run CONTINUOUSLY until /nightshift stop

Agent 1: nightshift-scout-1 [PENDING - continuous mode]
Agent 2: nightshift-scout-2 [PENDING - continuous mode]
Agent 3: nightshift-scout-3 [PENDING - continuous mode]

✓ 3 agents spawned in continuous mode.
   Use '/nightshift status' to monitor.
   Use '/nightshift stop' to shutdown and create PR.

# Status
$ /nightshift status
Active nightshift agents:

pulsona-night-dev (3 agents, $2.45/$5.00 budget):
  - nightshift-scout-1: research Next.js 15 [ACTIVE]
  - nightshift-scout-2: research Next.js 15 [ACTIVE]
  - nightshift-scout-3: research Next.js 15 [ACTIVE]

# Stop (triggers PR creation)
$ /nightshift stop
Sending shutdown requests to 3 agents...

✓ nightshift-scout-1 stopped
✓ nightshift-scout-2 stopped
✓ nightshift-scout-3 stopped

✓ All 3 agents stopped.

Creating PRs from night-dev to dev branches...

📝 pulsona: Creating PR from pulsona-night-dev → pulsona-dev
   Session: 3 agents, 8.5h duration, $5.00 budget
   ⚠️  Use /openpr to create the actual PR (auto-detection of commits + Build ID)

✓ Stop sequence complete.
   Next: Run /openpr in each night-dev worktree to create PRs
```

---

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `Repo not initialized` | Missing night-dev branch | Run `/nightshift init <repo>` first |
| `Worktree already exists` | Branch exists but worktree doesn't | Script auto-fixes by adding worktree |
| `Unknown repo` | Repo not in supported list | Add to `nightshift.py SUPPORTED_REPOS` |
| `Budget exceeded` | Total cost > `--budget` | Remaining agents get BUDGET status |
| `No active agents` | Calling stop/status with no running agents | Informational message, no error |

---

## When to Use

| Scenario | Command |
|----------|---------|
| Set up night-dev branch first time | `/nightshift init pulsona` |
| Start continuous development cycle | `/nightshift start pulsona "task focus"` |
| Check progress during cycle | `/nightshift status` |
| Stop all agents + create PR | `/nightshift stop` |
| Large-scale continuous maintenance | `/nightshift start gswarm --agents 10 --budget $20.00 --model opus` |
| Budget-conscious continuous mode | `/nightshift start pulsona --model sonnet --budget $3.00` |

**Best Practice:**

1. Run `/nightshift start` before leaving for the day
2. Agents work continuously overnight (research → implement → commit → repeat)
3. In the morning: `/nightshift status` to check progress
4. When satisfied: `/nightshift stop` to shutdown agents and create PR
5. Review PR and merge to dev branch

**Continuous Operation Example:**

```bash
# Friday 6pm - start agents
/nightshift start pulsona "Next.js 15 features" --agents 3

# Saturday 10am - check status (agents still running)
/nightshift status  # Shows: 47 commits, $8.45 spent, 16h runtime

# Saturday 10:30am - decide to stop
/nightshift stop    # Shutdown + create PR with all 47 commits
```

---

## Insights

- **Decision:** Continuous operation like /x agents — loop forever until explicit stop (not N commits then PR)
- **Trade-off:** Budget becomes soft limit (warning only) to enable continuous operation. Agents prioritize uptime over cost caps.
- **Pattern:** WORK SILENTLY protocol from /x — no status reports, no progress updates, just commit history speaks
- **Watch:** First 2-3 runs should be monitored to validate continuous loop doesn't get stuck in research phase
- **Model routing:** Fork mode (Sonnet) for skill orchestration, agents spawn as Opus/Sonnet/Gemini based on `--model` flag
