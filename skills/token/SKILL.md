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

## Workflow

1. **Check status**: `/token status` - See token expiry and which repos have the token
2. **Refresh if needed**: `/token refresh` - Refreshes if expiring within 10 minutes
3. **Sync to repos**: `/token sync all` - Updates CLAUDE_CODE_OAUTH_TOKEN in all repos

## Background

- OAuth access tokens expire in ~2 hours
- Refresh tokens last ~1 year
- systemd timer auto-refreshes every 30 minutes
- GitHub Actions need fresh tokens in secrets

## Implementation

```bash
# Run the unified token management script
/usr/share/claude/scripts/claude-github.sh <command>
```
