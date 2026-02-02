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
# REPO SEARCH PATHS - All locations to scan for git repos
# ============================================================================
# Can be overridden via CLAUDE_REPO_PATHS env var (colon-separated)
if [ -n "$CLAUDE_REPO_PATHS" ]; then
  IFS=':' read -ra REPO_SEARCH_PATHS <<< "$CLAUDE_REPO_PATHS"
else
  REPO_SEARCH_PATHS=(
    "$HOME/Desktop"
    "$HOME/.claude"
    "$HOME/code"
    "$HOME/repos"
    "$HOME/projects"
    "/usr/share/claude"
    # Also check common non-root user paths
    "/home/dennis/Desktop"
    "/home/dennis/code"
    "/home/dennis/repos"
    "/home/dennis/projects"
  )
fi

# Get local token timestamp (when credentials file was last modified)
get_local_token_mtime() {
  stat -c %Y "$CREDS_FILE" 2>/dev/null || echo "0"
}

# Get repo secret timestamp (returns epoch seconds, 0 if not found)
get_repo_secret_mtime() {
  local repo="$1"
  local updated_at
  updated_at=$(gh secret list --repo "$repo" 2>/dev/null | grep CLAUDE_CODE_OAUTH_TOKEN | awk '{print $2}')
  if [ -n "$updated_at" ]; then
    date -d "$updated_at" +%s 2>/dev/null || echo "0"
  else
    echo "0"
  fi
}

# Find all repos across search paths
find_all_repos() {
  for search_path in "${REPO_SEARCH_PATHS[@]}"; do
    [ -d "$search_path" ] || continue
    find "$search_path" -maxdepth 3 -name ".git" -type d 2>/dev/null | while read -r gitdir; do
      REPO_PATH=$(dirname "$gitdir")
      cd "$REPO_PATH" 2>/dev/null || continue
      REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "")
      [ -n "$REPO" ] && echo "$REPO"
    done
  done | sort -u
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
  LOCAL_MTIME=$(get_local_token_mtime)

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

  # Check systemd timer (both user and system level)
  echo ""
  echo "Auto-refresh Timer:"
  if systemctl --user is-active claude-token-refresh.timer >/dev/null 2>&1; then
    NEXT=$(systemctl --user show claude-token-refresh.timer --property=NextElapseUSecRealtime --value 2>/dev/null | head -1)
    if [ -n "$NEXT" ] && [ "$NEXT" != "n/a" ]; then
      NEXT_SEC=$((NEXT / 1000000))
      NEXT_DATE=$(date -d "@$NEXT_SEC" '+%H:%M:%S' 2>/dev/null || echo "soon")
      echo "  ${GREEN}✓ Active (user) - next refresh at $NEXT_DATE${RESET}"
    else
      echo "  ${GREEN}✓ Active (user)${RESET}"
    fi
  elif systemctl is-active claude-token-refresh.timer >/dev/null 2>&1; then
    echo "  ${GREEN}✓ Active (system)${RESET}"
  else
    echo "  ${YELLOW}⚠ Not active${RESET}"
    echo "  Start with: systemctl --user start claude-token-refresh.timer"
  fi

  # Scan repos with CLAUDE_CODE_OAUTH_TOKEN
  echo ""
  echo "GitHub Repositories:"
  echo "  ${GREY}(scanning: ${REPO_SEARCH_PATHS[*]})${RESET}"
  echo ""

  REPOS=$(find_all_repos)

  if [ -z "$REPOS" ]; then
    echo "  ${GREY}No repos found${RESET}"
  else
    for REPO in $REPOS; do
      SECRET_MTIME=$(get_repo_secret_mtime "$REPO")
      if [ "$SECRET_MTIME" -gt 0 ]; then
        if [ "$SECRET_MTIME" -lt "$LOCAL_MTIME" ]; then
          AGO=$(( ($(date +%s) - SECRET_MTIME) / 3600 ))
          echo "  ${YELLOW}⚠ $REPO${RESET} (stale - ${AGO}h old, needs sync)"
        else
          echo "  ${GREEN}✓ $REPO${RESET} (up-to-date)"
        fi
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
# SYNC - Push token to GitHub secrets (with stale detection)
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

  LOCAL_MTIME=$(get_local_token_mtime)
  FORCE_SYNC=false
  SYNC_ALL=false

  # Parse arguments
  for arg in "$@"; do
    case "$arg" in
      --all) SYNC_ALL=true ;;
      --force) FORCE_SYNC=true ;;
    esac
  done

  if [ "$SYNC_ALL" = true ]; then
    echo "Syncing token to all repositories..."
    echo "  ${GREY}(scanning: ${REPO_SEARCH_PATHS[*]})${RESET}"
    echo ""

    REPOS=$(find_all_repos)
    SYNCED=0
    SKIPPED=0
    FAILED=0

    for REPO in $REPOS; do
      SECRET_MTIME=$(get_repo_secret_mtime "$REPO")

      # Skip if already up-to-date (unless --force)
      if [ "$FORCE_SYNC" = false ] && [ "$SECRET_MTIME" -ge "$LOCAL_MTIME" ] && [ "$SECRET_MTIME" -gt 0 ]; then
        echo "${GREY}  ○ $REPO (up-to-date, skipped)${RESET}"
        SKIPPED=$((SKIPPED + 1))
        continue
      fi

      if gh secret set CLAUDE_CODE_OAUTH_TOKEN --repo "$REPO" --body "$TOKEN" 2>/dev/null; then
        if [ "$SECRET_MTIME" -eq 0 ]; then
          echo "${GREEN}  ✓ $REPO (new)${RESET}"
        else
          echo "${GREEN}  ✓ $REPO (updated)${RESET}"
        fi
        SYNCED=$((SYNCED + 1))
      else
        echo "${YELLOW}  ⚠ $REPO (failed or no access)${RESET}"
        FAILED=$((FAILED + 1))
      fi
    done

    echo ""
    echo "Summary: ${GREEN}${SYNCED} synced${RESET}, ${GREY}${SKIPPED} skipped${RESET}, ${YELLOW}${FAILED} failed${RESET}"
  else
    # Current repo only
    REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)

    if [ -z "$REPO" ]; then
      echo "${RED}✗ Not in a GitHub repo - run from repo directory or use --all${RESET}"
      exit 1
    fi

    SECRET_MTIME=$(get_repo_secret_mtime "$REPO")

    # Check if sync needed (unless --force)
    if [ "$FORCE_SYNC" = false ] && [ "$SECRET_MTIME" -ge "$LOCAL_MTIME" ] && [ "$SECRET_MTIME" -gt 0 ]; then
      echo "${GREY}○ $REPO already up-to-date (use --force to sync anyway)${RESET}"
      exit 0
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
  echo "  status                    Show token status and repo list"
  echo "  refresh [--force]         Refresh local OAuth token"
  echo "  sync [--all] [--force]    Push token to GitHub secrets"
  echo "  init                      Initialize repo with Claude workflow"
  echo ""
  echo "Options:"
  echo "  --all       Sync to all repos (searches ~/Desktop, ~/code, /usr/share/claude, etc.)"
  echo "  --force     Sync even if repo secret is already up-to-date"
  echo ""
  echo "Examples:"
  echo "  claude-github.sh status             # Check token expiry + stale repos"
  echo "  claude-github.sh refresh            # Refresh if expiring soon"
  echo "  claude-github.sh refresh --force    # Force refresh now"
  echo "  claude-github.sh sync               # Sync to current repo (if stale)"
  echo "  claude-github.sh sync --force       # Force sync to current repo"
  echo "  claude-github.sh sync --all         # Sync to all stale repos"
  echo "  claude-github.sh sync --all --force # Force sync to all repos"
  echo "  claude-github.sh init               # Setup Claude in current repo"
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
