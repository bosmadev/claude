#!/usr/bin/env python3
"""
Layer 1: Wrapper script for token refresh (cross-platform)
Calls claude-github.py refresh with proper environment.
Used by: scheduled task (Windows) / systemd timer (Linux), resume hook, login hook

Replaces: refresh-claude-token.sh
"""

import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from filelock import FileLock, Timeout as FileLockTimeout

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


def _sanitize_message(message: str) -> str:
    """Sanitize log messages to prevent credential leakage."""
    import re
    # Redact common token patterns
    sanitized = re.sub(r'(access[_-]?token["\s:=]+)([a-zA-Z0-9_\-\.]{20,})', r'\1[REDACTED]', message, flags=re.IGNORECASE)
    sanitized = re.sub(r'(refresh[_-]?token["\s:=]+)([a-zA-Z0-9_\-\.]{20,})', r'\1[REDACTED]', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(bearer\s+)([a-zA-Z0-9_\-\.]{20,})', r'\1[REDACTED]', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(sk-ant-[a-zA-Z0-9_\-]{20,})', r'[REDACTED_API_KEY]', sanitized)
    return sanitized

def log(message: str):
    """Append timestamped message to log file with file locking."""
    ensure_log_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sanitized = _sanitize_message(message)
    line = f"[{timestamp}] [refresh-token] {sanitized}\n"

    lock_file = LOG_DIR / ".refresh-log.lock"
    try:
        # Use file lock to prevent interleaved writes from concurrent processes
        with FileLock(str(lock_file), timeout=2):
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
    except (OSError, FileLockTimeout):
        # If lock fails or file write fails, silently continue
        pass


def check_network() -> bool:
    """Check network connectivity using platform-appropriate method with SSL verification."""
    import ssl

    # Create SSL context for certificate verification
    ssl_context = ssl.create_default_context()

    if sys.platform == "win32":
        # Windows: socket connect with SSL verification
        for host in HOSTS:
            try:
                sock = socket.create_connection((host, 443), timeout=2)
                # Wrap socket with SSL for certificate verification
                with ssl_context.wrap_socket(sock, server_hostname=host) as ssl_sock:
                    pass  # Connection successful with verified cert
                return True
            except (OSError, socket.timeout, ssl.SSLError):
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

    # Get timeout from environment or use default
    timeout = int(os.environ.get("CLAUDE_SYNC_TIMEOUT", "300"))

    try:
        log("Syncing token to GitHub repos...")
        result = subprocess.run(
            [sys.executable, str(claude_github_py), "sync", "--all"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode == 0:
            log("GitHub sync completed successfully")
            if result.stdout:
                log(result.stdout.strip())
            return True
        else:
            # Parse stderr for actionable error messages
            stderr = result.stderr.strip()
            if "gh: command not found" in stderr or "gh.exe" in stderr:
                log("GitHub sync failed: gh CLI not found in PATH")
            elif "permission denied" in stderr.lower():
                log(f"GitHub sync failed: permission error - {stderr}")
            elif "network" in stderr.lower() or "connection" in stderr.lower():
                log(f"GitHub sync failed: network error - {stderr}")
            else:
                log(f"GitHub sync failed (exit {result.returncode}): {stderr}")
            return False
    except subprocess.TimeoutExpired:
        log(f"GitHub sync timed out after {timeout}s - likely network issue")
        return False
    except FileNotFoundError:
        log("Sync ERROR: Python executable not found")
        return False


def main():
    extra_args = sys.argv[1:]

    # Use lock to prevent concurrent executions
    lock_file = Path.home() / ".claude" / ".refresh.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        with FileLock(str(lock_file), timeout=1):
            log("Starting token refresh check...")
            _run_refresh(extra_args)
    except FileLockTimeout:
        log("Another refresh is already running - skipping")
        sys.exit(0)

def _run_refresh(extra_args: list):
    """Internal function to run the refresh logic (called within lock)."""
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
