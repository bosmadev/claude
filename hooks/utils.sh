#!/bin/bash
# Desktop Utilities Hook - Focus and notification handlers
#
# This script consolidates desktop utility hooks into a single file
# with mode dispatch based on command-line argument.
#
# Usage:
#   utils.sh focus [cwd]   # Focus appropriate window
#   utils.sh notify        # Show notification with sound

set -euo pipefail

# Trap signals to kill child processes when hook times out
trap 'kill $(jobs -p) 2>/dev/null; exit 0' SIGTERM SIGINT SIGHUP

MODE="${1:-}"
shift || true

# =============================================================================
# Focus Window Functions
# =============================================================================

focus_window() {
  local pattern="$1"
  local window_id

  # Try wmctrl first
  if command -v wmctrl &>/dev/null; then
    window_id=$(wmctrl -l | grep -i "$pattern" | head -1 | awk '{print $1}')
    if [ -n "$window_id" ]; then
      wmctrl -i -a "$window_id"
      return 0
    fi
  fi

  # Fallback to xdotool
  if command -v xdotool &>/dev/null; then
    window_id=$(xdotool search --name "$pattern" 2>/dev/null | head -1)
    if [ -n "$window_id" ]; then
      xdotool windowactivate "$window_id"
      return 0
    fi
  fi

  return 1
}

focus_code_insiders() {
  local target_cwd="$1"

  # Try wmctrl first
  if command -v wmctrl &>/dev/null; then
    if focus_window "Visual Studio Code - Insiders"; then
      return 0
    fi
  fi

  # Fallback to xdotool
  if command -v xdotool &>/dev/null; then
    local window_ids=$(xdotool search --class "code-insiders" 2>/dev/null)
    if [ -n "$window_ids" ]; then
      xdotool windowactivate $(echo "$window_ids" | head -1) 2>/dev/null
      return 0
    fi
  fi

  return 1
}

do_focus() {
  local CWD="${1:-$HOME}"

  # Priority: code-insiders > Kate > claude windows > Dolphin
  if focus_code_insiders "$CWD"; then
    exit 0
  fi

  if focus_window "Kate"; then
    exit 0
  fi

  if focus_window "claude"; then
    exit 0
  fi

  if focus_window "Dolphin"; then
    exit 0
  fi

  # No window found - launch fallback
  if command -v kate &>/dev/null; then
    kate "$CWD" &
  elif command -v code-insiders &>/dev/null; then
    cd "$CWD" && code-insiders . &
  else
    konsole --workdir "$CWD" &
  fi
}

# =============================================================================
# Notification Functions
# =============================================================================

do_notify() {
  # Read JSON from stdin (5s timeout to prevent hanging)
  local INPUT
  INPUT=$(timeout 5 cat || echo '{}')

  # Parse JSON fields
  local NOTIFICATION_TYPE
  local MESSAGE
  local CWD
  local SESSION_ID

  NOTIFICATION_TYPE=$(echo "$INPUT" | jq -r '.notification_type // "unknown"')
  MESSAGE=$(echo "$INPUT" | jq -r '.message // "Claude needs your attention"')
  CWD=$(echo "$INPUT" | jq -r '.cwd // "$HOME"')
  SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""')

  # Store CWD for focus handler
  echo "$CWD" > "/tmp/claude-notify-cwd-$$"

  # Set notification parameters based on type
  local TITLE ICON URGENCY
  case "$NOTIFICATION_TYPE" in
    permission_prompt)
      TITLE="Claude Needs Permission"
      ICON="dialog-password"
      URGENCY="critical"
      ;;
    idle_prompt)
      TITLE="Claude Waiting for Input"
      ICON="dialog-question"
      URGENCY="normal"
      ;;
    elicitation_dialog)
      TITLE="Claude Needs Input"
      ICON="dialog-information"
      URGENCY="normal"
      ;;
    *)
      TITLE="Claude Code"
      ICON="dialog-information"
      URGENCY="normal"
      ;;
  esac

  # Play notification sound (background, don't block)
  paplay /usr/share/sounds/freedesktop/stereo/message-new-instant.oga 2>/dev/null &

  # Send notification (fire and forget - no --wait to prevent blocking)
  notify-send \
    --urgency="$URGENCY" \
    --icon="$ICON" \
    --app-name="Claude Code" \
    "$TITLE" \
    "$MESSAGE" 2>/dev/null &

  # Don't wait for action - notification is informational only
  local ACTION=""

  # Handle action click
  if [ "$ACTION" = "focus" ]; then
    do_focus "$CWD" &
  fi

  # Clean up temp file
  rm -f "/tmp/claude-notify-cwd-$$"

  # Return success to Claude (Notification hooks use simple schema)
  echo '{"continue":true,"suppressOutput":true}'
}

# =============================================================================
# Main Entry Point
# =============================================================================

case "$MODE" in
  focus)
    do_focus "${1:-$HOME}"
    ;;
  notify)
    do_notify
    ;;
  *)
    echo "Usage: utils.sh [focus|notify] [args...]" >&2
    exit 1
    ;;
esac
