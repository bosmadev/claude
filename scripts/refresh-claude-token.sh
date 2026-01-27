#!/bin/bash
# Layer 1: Wrapper script for systemd timer
# Calls claude-github.sh refresh with proper environment
# Used by: systemd timer, resume hook, login hook

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${HOME}/.claude/debug"
LOG_FILE="${LOG_DIR}/token-refresh.log"

# Ensure log directory exists
mkdir -p "$LOG_DIR" 2>/dev/null || true

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [refresh-token] $1" >> "$LOG_FILE"
}

# Check network connectivity
check_network() {
    # Try multiple endpoints for reliability
    for host in "console.anthropic.com" "api.anthropic.com" "1.1.1.1"; do
        if ping -c 1 -W 2 "$host" >/dev/null 2>&1; then
            return 0
        fi
    done
    return 1
}

# Main logic
main() {
    log "Starting token refresh check..."

    # Wait for network if not available (useful after resume)
    RETRY_COUNT=0
    MAX_RETRIES=6
    RETRY_DELAY=10

    while ! check_network; do
        RETRY_COUNT=$((RETRY_COUNT + 1))
        if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
            log "Network unavailable after ${MAX_RETRIES} retries - deferring refresh"
            exit 0  # Exit cleanly, timer will retry later
        fi
        log "Waiting for network... (attempt $RETRY_COUNT/$MAX_RETRIES)"
        sleep $RETRY_DELAY
    done

    # Call the main refresh script
    if [ -x "${SCRIPT_DIR}/claude-github.sh" ]; then
        "${SCRIPT_DIR}/claude-github.sh" refresh "$@" >> "$LOG_FILE" 2>&1
        EXIT_CODE=$?

        if [ $EXIT_CODE -eq 0 ]; then
            log "Token refresh completed successfully"
        else
            log "Token refresh failed with exit code $EXIT_CODE"
        fi

        exit $EXIT_CODE
    else
        log "ERROR: claude-github.sh not found at ${SCRIPT_DIR}"
        exit 1
    fi
}

main "$@"
