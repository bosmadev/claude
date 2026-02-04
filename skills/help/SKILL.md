---
name: help
description: Context-aware Claude Code advisor. Provides guidance based on current project state, recent activity, and available tools. Use when stuck or need workflow suggestions.
argument-hint: "[query]"
user-invocable: true
context: fork
---
# Claude Help Skill

**When invoked, immediately output:** `**SKILL_STARTED:** help`

Context-aware advisor that analyzes current project state and provides actionable guidance.

## Usage

```
/help                    - Get next action suggestion based on context
/help [query]            - Ask a specific question with project context
/help what's next        - Suggest next steps based on recent activity
/help stuck              - Diagnose common issues and suggest fixes
/help workflow           - Explain available skills and when to use them
/help ralph              - Ralph-specific help and status
```

## Context Analysis (Automatic)

When invoked, gather context from these sources:

### 1. Project State Detection

```python
# Check for active contexts
contexts = {
    "ralph_active": Path(".claude/ralph/state.json").exists(),
    "plan_pending": any(Path("plans/").glob("*.md")),
    "uncommitted": run("git status --porcelain"),
    "pending_commit": Path(".claude/pending-commit.md").exists(),
    "pending_pr": Path(".claude/pending-pr.md").exists(),
    "build_errors": run("pnpm validate 2>&1 | head -20"),
    "recent_files": run("git diff --name-only HEAD~3"),
}
```

### 2. Recent Activity

Read from `.claude/` directory:
- `command-history.log` - Recent bash commands
- `commit.md` - Pending changes
- `ralph/progress.json` - Agent status

### 3. Available Tools

Check MCP server availability:
- `serena` - Semantic code analysis
- `context7` - Documentation lookup
- `playwriter` - Browser automation
- `claude-in-chrome` - DevTools access

## Response Format

### Contextual Suggestions

Based on detected state, provide targeted advice:

| State | Suggestion |
|-------|------------|
| Ralph active, stuck agent | Check `.claude/ralph/progress.json`, consider `/start resume` |
| Uncommitted changes | Run `/commit` to stage changes |
| Pending commit exists | Review with `/commit show`, then `/commit confirm` |
| Build errors | Show errors, suggest fixes |
| No recent activity | Suggest starting point based on project type |
| Plan pending approval | Remind to review plan, use ExitPlanMode |

### Workflow Recommendations

```markdown
## Suggested Next Action

Based on your current context:
- [Primary action]
- [Alternative if blocked]

## Available Commands

| Command | When to Use |
|---------|-------------|
| `/start` | Complex multi-step implementation |
| `/commit` | Ready to commit changes |
| `/review` | Need code quality assessment |
| `/quality` | Check linting and type errors |
```

## Query Handling

### Natural Language Recognition

| Query Pattern | Action |
|---------------|--------|
| "what's next" / "next steps" | Analyze context, suggest action |
| "stuck" / "help" / "blocked" | Diagnose issues, show debug steps |
| "workflow" / "commands" | List available skills with examples |
| "ralph" / "agents" | Show Ralph status and commands |
| "errors" / "fix" | Run build checks, show errors |
| Specific question | Answer with project context |

### Examples

**User:** `/help what's next`

```markdown
## Current Context

- **Ralph Session:** Active (3 agents running)
- **Uncommitted Changes:** 5 files modified
- **Build Status:** Clean

## Suggested Next Action

Your Ralph agents are still working. Monitor with:
```
python C:/Users/Dennis/.claude/scripts/ralph.py status
```

When complete, run `/commit` to stage the changes.
```

**User:** `/help stuck`

```markdown
## Diagnostic Results

1. **Build Check:** 2 TypeScript errors in `src/api/routes.ts`
2. **Ralph Status:** Agent #2 failed (see `.claude/ralph/progress.json`)
3. **Last Command:** `pnpm validate` (exit code 1)

## Suggested Fixes

1. Fix TypeScript errors:
   - Line 45: Type 'string' is not assignable to type 'number'
   - Line 89: Property 'id' does not exist on type 'Response'

2. Resume Ralph if needed:
   ```bash
   /start resume
   ```
```

## Integration with Other Skills

This skill provides guidance but doesn't execute actions. Direct users to:

| Need | Redirect To |
|------|-------------|
| Start implementation | `/start [task]` |
| Commit changes | `/commit` |
| Review code | `/review` |
| Check quality | `/quality` |
| Manage screenshots | `/screen` |
| Token management | `/token status` |

## Serena Integration

Use Serena for code-aware responses:

```
# Find relevant context
mcp__serena__list_memories() - Check for project conventions
mcp__serena__get_symbols_overview(relative_path) - Understand file structure
mcp__serena__search_for_pattern(pattern) - Find related code
```

## Ralph Status Check

When query relates to Ralph:

```python
def get_ralph_status():
    state_file = Path(".claude/ralph/state.json")
    if not state_file.exists():
        return "No active Ralph session"

    state = json.loads(state_file.read_text())
    return {
        "phase": state.get("lifecycle_phase"),
        "agents": len(state.get("agents", [])),
        "completed": sum(1 for a in state.get("agents", []) if a.get("completed")),
        "budget": state.get("budget_usd"),
        "cost": state.get("total_cost_usd"),
    }
```

## Error Recovery Suggestions

| Error Type | Suggestion |
|------------|------------|
| Token expired | Run `/token refresh --force` |
| MCP server down | Check `~/.claude/settings.json` for server config |
| Hook failure | Check hook logs in `~/.claude/debug/` |
| Agent stuck | Check `.claude/ralph/progress.json`, consider `ralph.py resume` |
| Build failure | Run `/quality` for detailed diagnostics |

## Response Verbosity

Match response length to query:

- Simple query ("what's next") → 3-5 lines
- Diagnostic ("stuck") → Full analysis with steps
- Workflow question → Command table + examples
- Specific technical → Detailed answer with code
