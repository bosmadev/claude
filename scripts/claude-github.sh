#!/bin/bash
# Unified Claude GitHub Token Management
# Usage: claude-github.sh <command> [options]
#
# Commands:
#   init              Initialize current repo with Claude workflow
#   refresh           Refresh local OAuth token
#   sync [--all]      Push token to GitHub secrets (current repo or all)
#   status            Show token status across repos

set -e

# Configuration
CLAUDE_HOME="${CLAUDE_HOME:-/usr/share/claude}"
CREDS_FILE="${HOME}/.claude/.credentials.json"
LOG_FILE="${HOME}/.claude/debug/token-refresh.log"
BUFFER_SECONDS=600  # Refresh 10 min before expiry

# Colors
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
GREY=$'\033[38;5;245m'
RESET=$'\033[0m'

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ============================================================================
# STATUS - Show token status across repos
# ============================================================================
cmd_status() {
  echo "Claude GitHub Token Status"
  echo "=========================="
  echo ""

  # Check credentials file
  if [ ! -f "$CREDS_FILE" ]; then
    echo "${RED}✗ No credentials file at $CREDS_FILE${RESET}"
    echo "  Run: claude auth login"
    exit 1
  fi

  # Extract token info
  EXPIRES_AT=$(jq -r '.claudeAiOauth.expiresAt // 0' "$CREDS_FILE" 2>/dev/null)
  REFRESH_TOKEN=$(jq -r '.claudeAiOauth.refreshToken // empty' "$CREDS_FILE" 2>/dev/null)

  # Calculate expiry
  NOW_MS=$(($(date +%s) * 1000))
  TIME_UNTIL_EXPIRY_SEC=$(( (EXPIRES_AT - NOW_MS) / 1000 ))

  echo "Local Token:"
  if [ "$TIME_UNTIL_EXPIRY_SEC" -lt 0 ]; then
    echo "  ${RED}✗ Access token EXPIRED${RESET}"
  elif [ "$TIME_UNTIL_EXPIRY_SEC" -lt 600 ]; then
    echo "  ${YELLOW}⚠ Access token expires in ${TIME_UNTIL_EXPIRY_SEC}s${RESET}"
  else
    HOURS=$((TIME_UNTIL_EXPIRY_SEC / 3600))
    MINS=$(( (TIME_UNTIL_EXPIRY_SEC % 3600) / 60 ))
    echo "  ${GREEN}✓ Access token valid for ${HOURS}h ${MINS}m${RESET}"
  fi

  if [ -n "$REFRESH_TOKEN" ] && [ "$REFRESH_TOKEN" != "null" ]; then
    echo "  ${GREEN}✓ Refresh token present${RESET}"
  else
    echo "  ${RED}✗ No refresh token${RESET}"
  fi

  # Check systemd timer
  echo ""
  echo "Auto-refresh Timer:"
  if systemctl --user is-active claude-token-refresh.timer >/dev/null 2>&1; then
    NEXT=$(systemctl --user show claude-token-refresh.timer --property=NextElapseUSecRealtime --value 2>/dev/null | head -1)
    if [ -n "$NEXT" ] && [ "$NEXT" != "n/a" ]; then
      # Convert microseconds to readable format
      NEXT_SEC=$((NEXT / 1000000))
      NEXT_DATE=$(date -d "@$NEXT_SEC" '+%H:%M:%S' 2>/dev/null || echo "soon")
      echo "  ${GREEN}✓ Active - next refresh at $NEXT_DATE${RESET}"
    else
      echo "  ${GREEN}✓ Active${RESET}"
    fi
  else
    echo "  ${YELLOW}⚠ Not active${RESET}"
    echo "  Start with: systemctl --user start claude-token-refresh.timer"
  fi

  # Scan repos with CLAUDE_CODE_OAUTH_TOKEN
  echo ""
  echo "GitHub Repositories with Claude Token:"

  REPOS=$(find ~/Desktop ~/.claude ~/code 2>/dev/null -maxdepth 3 -name ".git" -type d | while read gitdir; do
    REPO_PATH=$(dirname "$gitdir")
    cd "$REPO_PATH" 2>/dev/null || continue
    REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "")
    [ -n "$REPO" ] && echo "$REPO"
  done | sort -u)

  if [ -z "$REPOS" ]; then
    echo "  ${GREY}No repos found${RESET}"
  else
    for REPO in $REPOS; do
      # Check if secret exists (will fail silently if no access)
      if gh secret list --repo "$REPO" 2>/dev/null | grep -q CLAUDE_CODE_OAUTH_TOKEN; then
        echo "  ${GREEN}✓ $REPO${RESET}"
      else
        echo "  ${GREY}○ $REPO${RESET} (no token or no access)"
      fi
    done
  fi
}

# ============================================================================
# REFRESH - Refresh local OAuth token
# ============================================================================
cmd_refresh() {
  log "Starting token refresh..."

  if [ ! -f "$CREDS_FILE" ]; then
    log "No credentials file at $CREDS_FILE - run 'claude auth login'"
    exit 1
  fi

  EXPIRES_AT=$(jq -r '.claudeAiOauth.expiresAt // 0' "$CREDS_FILE" 2>/dev/null)
  REFRESH_TOKEN=$(jq -r '.claudeAiOauth.refreshToken // empty' "$CREDS_FILE" 2>/dev/null)

  if [ -z "$REFRESH_TOKEN" ] || [ "$REFRESH_TOKEN" = "null" ]; then
    log "No refresh token found - run 'claude auth login'"
    exit 1
  fi

  NOW_MS=$(($(date +%s) * 1000))
  TIME_UNTIL_EXPIRY_SEC=$(( (EXPIRES_AT - NOW_MS) / 1000 ))

  # Check if refresh needed (unless --force)
  if [ "$1" != "--force" ] && [ "$TIME_UNTIL_EXPIRY_SEC" -gt "$BUFFER_SECONDS" ]; then
    log "Token still valid for ${TIME_UNTIL_EXPIRY_SEC}s - use --force to refresh anyway"
    exit 0
  fi

  log "Refreshing token..."

  RESPONSE=$(curl -s -X POST "https://console.anthropic.com/v1/oauth/token" \
    -H "Content-Type: application/json" \
    -d "{\"grant_type\": \"refresh_token\", \"refresh_token\": \"$REFRESH_TOKEN\"}" \
    2>&1)

  if echo "$RESPONSE" | jq -e '.access_token' > /dev/null 2>&1; then
    NEW_ACCESS=$(echo "$RESPONSE" | jq -r '.access_token')
    NEW_REFRESH=$(echo "$RESPONSE" | jq -r '.refresh_token // empty')
    NEW_EXPIRES=$(echo "$RESPONSE" | jq -r '.expires_at // .expires_in')

    if [ ${#NEW_EXPIRES} -lt 13 ]; then
      NEW_EXPIRES=$((NOW_MS + (NEW_EXPIRES * 1000)))
    fi

    TEMP_FILE=$(mktemp)
    jq ".claudeAiOauth.accessToken = \"$NEW_ACCESS\" | \
        .claudeAiOauth.expiresAt = $NEW_EXPIRES" "$CREDS_FILE" > "$TEMP_FILE"

    if [ -n "$NEW_REFRESH" ] && [ "$NEW_REFRESH" != "null" ]; then
      jq ".claudeAiOauth.refreshToken = \"$NEW_REFRESH\"" "$TEMP_FILE" > "${TEMP_FILE}.2"
      mv "${TEMP_FILE}.2" "$TEMP_FILE"
    fi

    mv "$TEMP_FILE" "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"

    HOURS=$(( (NEW_EXPIRES - NOW_MS) / 1000 / 3600 ))
    log "${GREEN}✓ Token refreshed - valid for ~${HOURS}h${RESET}"
  else
    ERROR_MSG=$(echo "$RESPONSE" | jq -r '.error // .message // "Unknown error"' 2>/dev/null || echo "$RESPONSE")
    log "${RED}✗ Refresh failed: $ERROR_MSG${RESET}"
    exit 1
  fi
}

# ============================================================================
# SYNC - Push token to GitHub secrets
# ============================================================================
cmd_sync() {
  if [ ! -f "$CREDS_FILE" ]; then
    echo "${RED}✗ No credentials file - run 'claude auth login'${RESET}"
    exit 1
  fi

  TOKEN=$(jq -r '.claudeAiOauth.accessToken' "$CREDS_FILE" 2>/dev/null)

  if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    echo "${RED}✗ No access token in credentials${RESET}"
    exit 1
  fi

  if [ "$1" = "--all" ]; then
    echo "Syncing token to all repositories..."

    REPOS=$(find ~/Desktop ~/.claude ~/code 2>/dev/null -maxdepth 3 -name ".git" -type d | while read gitdir; do
      REPO_PATH=$(dirname "$gitdir")
      cd "$REPO_PATH" 2>/dev/null || continue
      REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "")
      [ -n "$REPO" ] && echo "$REPO"
    done | sort -u)

    for REPO in $REPOS; do
      if gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo "$REPO" --body "$TOKEN" 2>/dev/null; then
        echo "${GREEN}✓ $REPO${RESET}"
      else
        echo "${YELLOW}⚠ $REPO (failed or no access)${RESET}"
      fi
    done
  else
    # Current repo only
    REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)

    if [ -z "$REPO" ]; then
      echo "${RED}✗ Not in a GitHub repo - run from repo directory or use --all${RESET}"
      exit 1
    fi

    if gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo "$REPO" --body "$TOKEN" 2>/dev/null; then
      echo "${GREEN}✓ Token synced to $REPO${RESET}"
    else
      echo "${RED}✗ Failed to sync token to $REPO${RESET}"
      exit 1
    fi
  fi
}

# ============================================================================
# INIT - Initialize repo with Claude workflow
# ============================================================================
cmd_init() {
  TEMPLATE_DIR="${CLAUDE_HOME}"

  if [ ! -d ".git" ] && [ ! -f ".git" ]; then
    echo "${RED}✗ Not a git repository - run from repo root${RESET}"
    exit 1
  fi

  echo "Initializing Claude GitHub integration..."

  mkdir -p .github/workflows .github/ISSUE_TEMPLATE

  if [ -d "$TEMPLATE_DIR/.github" ]; then
    cp -r "$TEMPLATE_DIR/.github/"* .github/ 2>/dev/null || true
    echo "${GREEN}✓ Template files copied${RESET}"
  else
    echo "Creating minimal workflow..."
    cat > .github/workflows/claude.yml << 'WORKFLOW'
name: Claude Code Review
on:
  pull_request:
  issue_comment:
    types: [created]

jobs:
  claude:
    if: contains(github.event.comment.body, '@claude') || github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
WORKFLOW
    echo "${GREEN}✓ Workflow created${RESET}"
  fi

  # Sync token to this repo
  cmd_sync

  echo ""
  echo "Next steps:"
  echo "  1. git add .github && git commit -m 'Add Claude GitHub integration'"
  echo "  2. git push"
  echo "  3. Test with: @claude please review this PR"
}

# ============================================================================
# HELP
# ============================================================================
cmd_help() {
  echo "Claude GitHub Token Management"
  echo ""
  echo "Usage: claude-github.sh <command> [options]"
  echo ""
  echo "Commands:"
  echo "  status              Show token status and repo list"
  echo "  refresh [--force]   Refresh local OAuth token"
  echo "  sync [--all]        Push token to GitHub secrets"
  echo "  init                Initialize repo with Claude workflow"
  echo ""
  echo "Examples:"
  echo "  claude-github.sh status           # Check token expiry"
  echo "  claude-github.sh refresh          # Refresh if needed"
  echo "  claude-github.sh refresh --force  # Force refresh"
  echo "  claude-github.sh sync             # Sync to current repo"
  echo "  claude-github.sh sync --all       # Sync to all repos"
  echo "  claude-github.sh init             # Setup Claude in current repo"
}

# ============================================================================
# MAIN
# ============================================================================
case "${1:-help}" in
  status)  cmd_status ;;
  refresh) cmd_refresh "$2" ;;
  sync)    cmd_sync "$2" ;;
  init)    cmd_init ;;
  help|--help|-h) cmd_help ;;
  *)
    echo "${RED}Unknown command: $1${RESET}"
    cmd_help
    exit 1
    ;;
esac
