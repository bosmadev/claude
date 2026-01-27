#!/bin/bash
# Install Claude token refresh systemd units
# Run with sudo for system-level installation
# Run without sudo for user-level installation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="${SCRIPT_DIR}/../systemd"

# Colors
RED=$'\033[31m'
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RESET=$'\033[0m'

echo "Claude Token Refresh Timer Installer"
echo "====================================="
echo ""

# Detect installation mode
if [ "$(id -u)" -eq 0 ]; then
    MODE="system"
    UNIT_DIR="/etc/systemd/system"
    SYSTEMCTL="systemctl"
    echo "Installing as: ${GREEN}system service${RESET}"
else
    MODE="user"
    UNIT_DIR="${HOME}/.config/systemd/user"
    SYSTEMCTL="systemctl --user"
    echo "Installing as: ${GREEN}user service${RESET}"
fi

echo ""

# Create unit directory if needed
mkdir -p "$UNIT_DIR"

# Stop existing timers
echo "Stopping existing timers..."
$SYSTEMCTL stop claude-token-refresh.timer 2>/dev/null || true
$SYSTEMCTL stop claude-token-resume.service 2>/dev/null || true

# Copy unit files
echo "Installing unit files..."

# Timer
cp "${SYSTEMD_DIR}/claude-token-refresh.timer" "${UNIT_DIR}/"
echo "  ${GREEN}✓${RESET} claude-token-refresh.timer"

# Service (with user-specific HOME for system mode)
if [ "$MODE" = "system" ]; then
    # For system mode, need to specify HOME and user
    REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo $USER)}"
    REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

    sed "s|^# For system-level.*|User=${REAL_USER}|; \
         s|^# For system-level.*|Environment=\"HOME=${REAL_HOME}\"|" \
        "${SYSTEMD_DIR}/claude-token-refresh.service" > "${UNIT_DIR}/claude-token-refresh.service"

    # Actually, let's do it properly
    cat > "${UNIT_DIR}/claude-token-refresh.service" << EOF
[Unit]
Description=Refresh Claude OAuth Token
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/share/claude/scripts/refresh-claude-token.sh
Environment="CLAUDE_HOME=/usr/share/claude"
Environment="HOME=${REAL_HOME}"
User=${REAL_USER}
StandardOutput=journal
StandardError=journal
RestartSec=60
EOF
else
    cp "${SYSTEMD_DIR}/claude-token-refresh.service" "${UNIT_DIR}/"
fi
echo "  ${GREEN}✓${RESET} claude-token-refresh.service"

# Resume service
if [ "$MODE" = "system" ]; then
    REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo $USER)}"
    REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

    cat > "${UNIT_DIR}/claude-token-resume.service" << EOF
[Unit]
Description=Refresh Claude OAuth Token on Resume from Sleep
After=suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target

[Service]
Type=oneshot
ExecStartPre=/bin/sleep 5
ExecStart=/usr/share/claude/scripts/refresh-claude-token.sh
Environment="CLAUDE_HOME=/usr/share/claude"
Environment="HOME=${REAL_HOME}"
User=${REAL_USER}
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target
EOF
else
    cp "${SYSTEMD_DIR}/claude-token-resume.service" "${UNIT_DIR}/"
fi
echo "  ${GREEN}✓${RESET} claude-token-resume.service"

# Reload systemd
echo ""
echo "Reloading systemd..."
$SYSTEMCTL daemon-reload

# Enable and start
echo "Enabling services..."
$SYSTEMCTL enable claude-token-refresh.timer
$SYSTEMCTL enable claude-token-resume.service 2>/dev/null || true

echo "Starting timer..."
$SYSTEMCTL start claude-token-refresh.timer

# Verify
echo ""
echo "Verifying installation..."

if $SYSTEMCTL is-active claude-token-refresh.timer >/dev/null 2>&1; then
    echo "  ${GREEN}✓${RESET} Timer is active"
    NEXT=$($SYSTEMCTL show claude-token-refresh.timer --property=NextElapseUSecRealtime --value 2>/dev/null | head -1)
    if [ -n "$NEXT" ] && [ "$NEXT" != "n/a" ]; then
        NEXT_SEC=$((NEXT / 1000000))
        NEXT_DATE=$(date -d "@$NEXT_SEC" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "soon")
        echo "  Next trigger: $NEXT_DATE"
    fi
else
    echo "  ${RED}✗${RESET} Timer failed to start"
    echo "  Check logs: journalctl -u claude-token-refresh.timer"
fi

if $SYSTEMCTL is-enabled claude-token-resume.service >/dev/null 2>&1; then
    echo "  ${GREEN}✓${RESET} Resume hook enabled"
else
    echo "  ${YELLOW}⚠${RESET} Resume hook not enabled (may need manual enable)"
fi

echo ""
echo "Installation complete!"
echo ""
echo "Useful commands:"
echo "  $SYSTEMCTL status claude-token-refresh.timer  # Check timer status"
echo "  $SYSTEMCTL list-timers --all                  # List all timers"
echo "  journalctl -u claude-token-refresh.service    # View logs"
echo "  $SYSTEMCTL start claude-token-refresh.service # Manual refresh"
