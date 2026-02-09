---
name: token
description: Manage Claude OAuth tokens and GitHub secrets
argument-hint: "[status] | refresh [--force] | sync [all] | help"
user-invocable: true
context: fork
model: haiku
---
# Token Management Skill

When invoked, immediately output: **SKILL_STARTED:** token

Manage Claude OAuth tokens and GitHub secrets.

## Commands

| Command | Description |
|---------|-------------|
| `/token` or `/token status` | Show token expiry and repo status |
| `/token refresh` | Refresh if expiring soon |
| `/token refresh --force` | Force refresh regardless of expiry |
| `/token sync` | Push token to current repo's GitHub secrets |
| `/token sync all` | Push token to all detected repos |
| `/token help` | Show usage |

## Detailed Workflow

### Step 1: Check Token Status

Run `/token status` to see:
- Current token expiry time
- Time remaining until expiration
- Which repositories have the token synced

**Example output:**
```
Token Status:
├─ Expires: 2026-02-05 14:30:00 UTC
├─ Remaining: 1 hour 25 minutes
└─ Status: Valid

Repositories with token:
✅ my-app (synced 2 hours ago)
❌ other-repo (not synced)

Next auto-refresh: 2026-02-05 14:00:00 UTC (via Task Scheduler)
```

### Step 2: Refresh Token (if expiring)

Run `/token refresh` to:
1. Check if token expires within 10 minutes
2. If yes: Request new access token using refresh token
3. Update local config with new token
4. Report new expiry time

**When to use:**
- Token expiring soon (< 10 minutes)
- After laptop wake from sleep (token may be stale)
- Before long Claude Code sessions

**Force refresh:**
Use `/token refresh --force` to refresh regardless of expiry (useful for testing or manual sync).

### Step 3: Sync Token to GitHub

Run `/token sync` to:
1. Get current repository name from git
2. Fetch token from Claude Code config
3. Use `gh secret set` to upload to GitHub
4. Verify secret was set successfully

Run `/token sync all` to sync to all detected repositories (scans for git repos in common locations).

**Prerequisites:**
- `gh` CLI installed and authenticated
- Write access to repository settings

## Background

- **OAuth access tokens** expire in ~2 hours
- **Refresh tokens** last ~1 year
- **Task Scheduler** auto-refreshes every 30 minutes (4-layer defense)
- **GitHub Actions** need fresh tokens in secrets to authenticate

See CLAUDE.md "Token Refresh (4-Layer Defense)" for full architecture.

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| **Script not found** | `claude-github.py` missing from `~/.claude/scripts/` | Reinstall Claude Code or check installation |
| **Token refresh fails** | Invalid refresh token or network error | Re-authenticate: `claude auth login` |
| **GitHub API error** | Rate limit, permissions, or network | Check `gh auth status`, verify repo access |
| **No repository found** | Not in a git repo when running `/token sync` | Navigate to git repository or use `/token sync all` |
| **Secret set fails** | No write permission to repo | Check GitHub repo permissions, verify you're an admin/maintainer |
| **Python not found** | Python not in PATH | Install Python 3.14+ or check PATH configuration |

## Implementation

```bash
# Run the unified token management script
python C:/Users/Dennis/.claude/scripts/claude-github.py <command>
```
