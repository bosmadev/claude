#!/usr/bin/env python3
"""
Layer 1: Wrapper script for token refresh (cross-platform)
Calls claude-github.py refresh with proper environment.
Used by: scheduled task (Windows) / systemd timer (Linux), resume hook, login hook

Replaces: refresh-claude-token.sh
"""

import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_DIR = Path.home() / ".claude" / "debug"
LOG_FILE = LOG_DIR / "token-refresh.log"

MAX_RETRIES = 6
RETRY_DELAY = 10

HOSTS = ["console.anthropic.com", "api.anthropic.com", "1.1.1.1"]


def ensure_log_dir():
    """Create log directory if it doesn't exist."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def log(message: str):
    """Append timestamped message to log file."""
    ensure_log_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [refresh-token] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def check_network() -> bool:
    """Check network connectivity using platform-appropriate method."""
    if sys.platform == "win32":
        # Windows: socket connect is more reliable than ping
        for host in HOSTS:
            try:
                socket.create_connection((host, 443), timeout=2)
                return True
            except (OSError, socket.timeout):
                continue
    else:
        # Linux: use ping
        for host in HOSTS:
            try:
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", "2", host],
                    capture_output=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                continue
    return False


def find_refresh_command() -> list[str] | None:
    """Find the appropriate refresh command to run."""
    claude_github_py = SCRIPT_DIR / "claude-github.py"
    if claude_github_py.exists():
        return [sys.executable, str(claude_github_py), "refresh"]
    return None


def run_sync() -> bool:
    """Sync token to all GitHub repos after refresh."""
    claude_github_py = SCRIPT_DIR / "claude-github.py"
    if not claude_github_py.exists():
        log("Sync skipped: claude-github.py not found")
        return False

    try:
        log("Syncing token to GitHub repos...")
        with open(LOG_FILE, "a", encoding="utf-8") as log_f:
            result = subprocess.run(
                [sys.executable, str(claude_github_py), "sync", "--all"],
                stdout=log_f,
                stderr=subprocess.STDOUT,
                timeout=300,  # 5 min timeout for sync (scans multiple repos)
            )
        if result.returncode == 0:
            log("GitHub sync completed successfully")
            return True
        else:
            log(f"GitHub sync failed with exit code {result.returncode}")
            return False
    except subprocess.TimeoutExpired:
        log("GitHub sync timed out after 300s")
        return False
    except FileNotFoundError as e:
        log(f"Sync ERROR: {e}")
        return False


def main():
    extra_args = sys.argv[1:]
    log("Starting token refresh check...")

    # Wait for network if not available (useful after resume from sleep)
    retry_count = 0
    while not check_network():
        retry_count += 1
        if retry_count >= MAX_RETRIES:
            log(f"Network unavailable after {MAX_RETRIES} retries - deferring refresh")
            sys.exit(0)  # Exit cleanly, scheduler will retry later
        log(f"Waiting for network... (attempt {retry_count}/{MAX_RETRIES})")
        time.sleep(RETRY_DELAY)

    # Find and call the main refresh script
    cmd = find_refresh_command()
    if cmd is None:
        log(f"ERROR: No refresh script found in {SCRIPT_DIR}")
        sys.exit(1)

    # Don't pass --sync to the refresh command; we handle it after
    refresh_args = [a for a in extra_args if a != "--sync"]
    cmd.extend(refresh_args)

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as log_f:
            result = subprocess.run(
                cmd,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                timeout=120,
            )
        exit_code = result.returncode

        if exit_code == 0:
            log("Token refresh completed successfully")
            # Auto-sync to GitHub if --sync flag present
            if "--sync" in extra_args:
                run_sync()
        else:
            log(f"Token refresh failed with exit code {exit_code}")

        sys.exit(exit_code)
    except subprocess.TimeoutExpired:
        log("Token refresh timed out after 120s")
        sys.exit(1)
    except FileNotFoundError as e:
        log(f"ERROR: Command not found: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
