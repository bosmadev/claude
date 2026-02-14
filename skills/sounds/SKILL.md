---
name: sounds
description: Enable or disable audio feedback for Claude Code events (tool calls, commits, errors)
when_to_use: When the user wants to toggle audio notifications on/off for the current session
argument-hint: "on | off | status"
context: main
---

# /sounds — Audio Feedback Toggle

Control audio feedback for Claude Code events in the current session.

**EXECUTE IMMEDIATELY (NO PLANNING):**

When the user runs `/sounds [on|off|status]`, immediately execute:

```bash
cd ~/.claude/skills/sounds && python sounds.py {arg}
```

Where `{arg}` is the user's argument (on, off, or status). Default to "status" if no argument provided.

**STOP after execution. Do NOT continue with any other tasks.**

## Commands

| Command | Effect |
|---------|--------|
| `/sounds on` | Enable audio feedback (creates `~/.claude/sounds-enabled` marker) |
| `/sounds off` | Disable audio feedback (removes marker file) |
| `/sounds status` | Show current audio state |

## Behavior

- **Per-session toggle**: Each session can independently enable/disable sounds
- **Subagent exclusion**: Audio never plays for subagents (Task/fork contexts)
- **Persistence**: Setting persists across tool calls but not across sessions (intentional)

## Supported Events

| Event | Trigger | Sound |
|-------|---------|-------|
| Session Start | SessionStart hook | 800Hz, 200ms |
| Tool Success | PostToolUse (non-error) | 1000Hz, 100ms |
| Tool Failure | PostToolUse (error) | 400Hz, 300ms |
| Notification | Permission prompts | 600Hz, 150ms (×2) |
| Git Commit | `git commit` command | 1200Hz, 150ms |
| Session Stop | Stop hook | 500Hz, 400ms |

## Implementation

Uses Python's built-in `winsound` module (Windows only, zero dependencies).

## Examples

```bash
# Enable audio for this session
/sounds on

# Check current status
/sounds status

# Disable audio
/sounds off
```
