#!/bin/bash
# Claude Code Statusline Script (Merged)
# Format: Opus (⚡11) Engineer | 25%/59% | main@abc123 »1«3 [+0|~2|?5]
# Reads JSON input from stdin (Claude Code statusLine protocol)

set -euo pipefail

# Nord-inspired color palette (Variation A)
SALMON=$'\033[38;5;173m'        # Model name (Opus)
AURORA_GREEN=$'\033[38;5;108m'  # Hooks all active, ahead («), staged (+), context %
AURORA_YELLOW=$'\033[38;5;222m' # Hooks partial, modified (~)
AURORA_RED=$'\033[38;5;131m'    # Behind (»), untracked (?)
GREY=$'\033[38;5;245m'          # Style name, commit hash, zero counts
DARK_GREY=$'\033[38;5;240m'     # Separators (|), parentheses
SNOW_WHITE=$'\033[38;5;253m'    # Branch name (softer white)
RESET=$'\033[0m'

# Discover active settings.json location (priority order)
# 1. Current working directory (project-level)
# 2. /usr/share/claude (system-level)
# 3. ~/.claude (user-level fallback)
find_settings_dir() {
  local cwd="${1:-.}"
  if [ -f "$cwd/settings.json" ]; then
    echo "$cwd"
  elif [ -f "/usr/share/claude/settings.json" ]; then
    echo "/usr/share/claude"
  elif [ -f "$HOME/.claude/settings.json" ]; then
    echo "$HOME/.claude"
  else
    echo "$HOME/.claude"  # Default fallback
  fi
}

SETTINGS_DIR=$(find_settings_dir "$(pwd)")
SETTINGS_FILE="$SETTINGS_DIR/settings.json"
HOOKS_CONFIG="$SETTINGS_DIR/.expected-hooks"

# Expected number of hooks - read from config or count from settings
if [ -f "$HOOKS_CONFIG" ]; then
  EXPECTED_HOOKS=$(cat "$HOOKS_CONFIG" 2>/dev/null | tr -d '[:space:]')
else
  # Auto-detect: count current hooks as baseline
  EXPECTED_HOOKS=$(jq '[.hooks // {} | .. | objects | select(.type == "command")] | length' "$SETTINGS_FILE" 2>/dev/null || echo "0")
  echo "$EXPECTED_HOOKS" > "$HOOKS_CONFIG" 2>/dev/null || true
fi
[ -z "$EXPECTED_HOOKS" ] && EXPECTED_HOOKS=0

# Read JSON input from stdin
input=$(cat)

# Extract values from JSON input
CWD=$(echo "$input" | jq -r '.cwd // "."')
MODEL=$(echo "$input" | jq -r '.model.display_name // "Claude"' | cut -d' ' -f1)
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
# Capitalize first letter of style name
STYLE_RAW=$(echo "$input" | jq -r '.output_style.name // "default"')
STYLE="$(echo "${STYLE_RAW:0:1}" | tr '[:lower:]' '[:upper:]')${STYLE_RAW:1}"

# Color for context percentage (green<50, yellow<80, red>=80)
if [ "$PCT" -lt 50 ]; then
  CTX_COLOR="${AURORA_GREEN}"
elif [ "$PCT" -lt 80 ]; then
  CTX_COLOR="${AURORA_YELLOW}"
else
  CTX_COLOR="${AURORA_RED}"
fi

# Weekly usage via OAuth API (cached 5 min)
CACHE="$HOME/.claude/.usage-cache"
WEEKLY="?"
if [ ! -f "$CACHE" ] || [ $(( $(date +%s) - $(stat -c %Y "$CACHE" 2>/dev/null || echo 0) )) -gt 300 ]; then
  TOKEN=$(cat ~/.claude/.credentials.json 2>/dev/null | jq -r '.claudeAiOauth.accessToken' 2>/dev/null || echo "")
  if [ -n "$TOKEN" ] && [ "$TOKEN" != "null" ]; then
    curl -s "https://api.anthropic.com/api/oauth/usage" \
      -H "Authorization: Bearer $TOKEN" \
      -H "anthropic-beta: oauth-2025-04-20" 2>/dev/null > "$CACHE" || true
  fi
fi
if [ -f "$CACHE" ]; then
  WEEKLY=$(jq -r '.seven_day.utilization // 0' "$CACHE" 2>/dev/null | cut -d. -f1 || echo "?")
fi
[ -z "$WEEKLY" ] && WEEKLY="?"

# Color for 7d usage (green<80, yellow<90, red>=90)
if [ "$WEEKLY" = "?" ]; then
  WEEKLY_COLOR="${GREY}"
elif [ "$WEEKLY" -lt 80 ]; then
  WEEKLY_COLOR="${AURORA_GREEN}"
elif [ "$WEEKLY" -lt 90 ]; then
  WEEKLY_COLOR="${AURORA_YELLOW}"
else
  WEEKLY_COLOR="${AURORA_RED}"
fi

# Git info with OSC 8 clickable link, commit hash, ahead/behind chevrons, and status counts
GIT=""
if git -C "$CWD" rev-parse --git-dir >/dev/null 2>&1; then
  BRANCH=$(git -C "$CWD" branch --show-current 2>/dev/null || echo "")
  REMOTE=$(git -C "$CWD" config --get remote.origin.url 2>/dev/null | sed 's/git@github.com:/https:\/\/github.com\//' | sed 's/\.git$//' || echo "")

  # Short commit hash (grey)
  COMMIT_HASH=$(git -C "$CWD" rev-parse --short HEAD 2>/dev/null || echo "")

  # Ahead/behind with chevrons (» behind red, « ahead green, zeros grey)
  AHEAD_BEHIND=""
  if git -C "$CWD" rev-parse @{upstream} >/dev/null 2>&1; then
    COUNTS=$(git -C "$CWD" rev-list --left-right --count @{upstream}...HEAD 2>/dev/null || echo "0 0")
    BEHIND=$(echo "$COUNTS" | awk '{print $1}')
    AHEAD=$(echo "$COUNTS" | awk '{print $2}')

    # Behind (» red) - zeros in grey
    if [ "$BEHIND" = "0" ]; then
      AHEAD_BEHIND="${GREY}»${BEHIND}${RESET}"
    else
      AHEAD_BEHIND="${AURORA_RED}»${BEHIND}${RESET}"
    fi

    # Ahead (« green) - zeros in grey
    if [ "$AHEAD" = "0" ]; then
      AHEAD_BEHIND="${AHEAD_BEHIND}${GREY}«${AHEAD}${RESET}"
    else
      AHEAD_BEHIND="${AHEAD_BEHIND}${AURORA_GREEN}«${AHEAD}${RESET}"
    fi
  fi

  # Git status counts: +staged ~modified ?untracked (zeros in grey)
  STAGED=$(git -C "$CWD" diff --cached --numstat 2>/dev/null | wc -l | tr -d ' ')
  MODIFIED=$(git -C "$CWD" diff --numstat 2>/dev/null | wc -l | tr -d ' ')
  UNTRACKED=$(git -C "$CWD" ls-files --others --exclude-standard 2>/dev/null | wc -l | tr -d ' ')

  # Staged color (green or grey for zero)
  if [ "$STAGED" = "0" ]; then
    STAGED_FMT="${GREY}+${STAGED}${RESET}"
  else
    STAGED_FMT="${AURORA_GREEN}+${STAGED}${RESET}"
  fi

  # Modified color (yellow or grey for zero)
  if [ "$MODIFIED" = "0" ]; then
    MODIFIED_FMT="${GREY}~${MODIFIED}${RESET}"
  else
    MODIFIED_FMT="${AURORA_YELLOW}~${MODIFIED}${RESET}"
  fi

  # Untracked color (red or grey for zero)
  if [ "$UNTRACKED" = "0" ]; then
    UNTRACKED_FMT="${GREY}?${UNTRACKED}${RESET}"
  else
    UNTRACKED_FMT="${AURORA_RED}?${UNTRACKED}${RESET}"
  fi

  GITSTATUS="[${STAGED_FMT}${DARK_GREY}|${RESET}${MODIFIED_FMT}${DARK_GREY}|${RESET}${UNTRACKED_FMT}]"

  if [ -n "$BRANCH" ]; then
    # Build git section: branch@hash »B«A [+S|~M|?U]
    HASH_FMT=""
    [ -n "$COMMIT_HASH" ] && HASH_FMT="${GREY}@${COMMIT_HASH}${RESET}"

    if [ -n "$REMOTE" ]; then
      # OSC 8 hyperlink (supported in iTerm2, VS Code, Kitty, etc.)
      GIT="${SNOW_WHITE}\033]8;;${REMOTE}/tree/${BRANCH}\033\\${BRANCH}\033]8;;\033\\${RESET}${HASH_FMT}"
    else
      GIT="${SNOW_WHITE}${BRANCH}${RESET}${HASH_FMT}"
    fi

    # Add ahead/behind if available
    [ -n "$AHEAD_BEHIND" ] && GIT="${GIT} ${AHEAD_BEHIND}"

    # Add git status
    GIT="${GIT} ${GITSTATUS}"
  fi
fi

# Hook count from settings.json (count actual command objects)
HOOKS=$(jq '[.hooks // {} | .. | objects | select(.type == "command")] | length' "$SETTINGS_FILE" 2>/dev/null || echo "0")
[ -z "$HOOKS" ] && HOOKS="0"

# Hook color: green=all active, yellow=some missing, red=none
if [ "$HOOKS" -eq "$EXPECTED_HOOKS" ]; then
  HOOK_COLOR="${AURORA_GREEN}"
elif [ "$HOOKS" -gt 0 ]; then
  HOOK_COLOR="${AURORA_YELLOW}"
else
  HOOK_COLOR="${AURORA_RED}"
fi

# Output with grey pipe separators
# Example: Opus (⚡11) Engineer | 25%/59% | main@abc123 »1«3 [+0|~2|?5]
printf "${SALMON}%s${RESET} ${DARK_GREY}(${RESET}${HOOK_COLOR}⚡%s${RESET}${DARK_GREY})${RESET} ${GREY}%s${RESET} ${DARK_GREY}|${RESET} ${CTX_COLOR}%s%%${RESET}${DARK_GREY}/${RESET}${WEEKLY_COLOR}%s%%${RESET} ${DARK_GREY}|${RESET} %b" "$MODEL" "$HOOKS" "$STYLE" "$PCT" "$WEEKLY" "$GIT"
