#!/bin/bash
# Setup script for CLAUDE_CODE_TMPDIR
# Run with: sudo bash /usr/share/claude/scripts/setup-tmpdir.sh

set -e

TMPDIR_PATH="/mnt/claude-tmp"
TMPDIR_SIZE="512m"

echo "Setting up CLAUDE_CODE_TMPDIR at $TMPDIR_PATH..."

# Create mount point
mkdir -p "$TMPDIR_PATH"

# Mount tmpfs
if ! mountpoint -q "$TMPDIR_PATH"; then
    mount -t tmpfs -o size=$TMPDIR_SIZE,mode=1777 tmpfs "$TMPDIR_PATH"
    echo "Mounted tmpfs at $TMPDIR_PATH"
else
    echo "Already mounted at $TMPDIR_PATH"
fi

# Add to fstab if not present
if ! grep -q "claude-tmp" /etc/fstab; then
    echo "tmpfs $TMPDIR_PATH tmpfs size=$TMPDIR_SIZE,mode=1777 0 0" >> /etc/fstab
    echo "Added to /etc/fstab for persistence"
else
    echo "Already in /etc/fstab"
fi

echo ""
echo "Setup complete. CLAUDE_CODE_TMPDIR is configured in settings.json"
echo "Restart Claude Code to use the new tmpdir."
