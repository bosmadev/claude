#!/bin/bash
# Layer 3: Login hook for token refresh
# Install to: /etc/profile.d/claude-token.sh (system-wide)
# Or add to: ~/.bashrc or ~/.zshrc (user-level)
#
# This script runs on every interactive login to ensure token is valid.
# It's intentionally fast - only checks, doesn't block login.

# Only run in interactive shells
[[ $- != *i* ]] && return

# Only run once per session (use a session marker)
TOKEN_CHECK_MARKER="/tmp/.claude-token-checked-$$"
if [ -f "$TOKEN_CHECK_MARKER" ]; then
    return
fi

# Mark this session as checked
touch "$TOKEN_CHECK_MARKER" 2>/dev/null || true

# Background check to not slow down login
(
    SCRIPT_DIR="/usr/share/claude/scripts"

    # Quick check using token-guard
    if [ -x "${SCRIPT_DIR}/token-guard.py" ]; then
        python3 "${SCRIPT_DIR}/token-guard.py" check --quiet 2>/dev/null
    elif [ -x "${SCRIPT_DIR}/refresh-claude-token.sh" ]; then
        "${SCRIPT_DIR}/refresh-claude-token.sh" 2>/dev/null
    fi
) &
disown 2>/dev/null || true
