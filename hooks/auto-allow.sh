#!/bin/bash
# Auto-allow hook for Read/Edit/Write operations
# Workaround for Claude Code permission bug (GitHub #6850)
printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow"}}'
