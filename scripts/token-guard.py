#!/usr/bin/env python3
"""
Layer 4: Pre-operation token validation
Run before Claude operations to ensure valid token.

Usage:
    token-guard.py check     # Check token validity, refresh if needed
    token-guard.py status    # Show token status (no refresh)
    token-guard.py --quiet   # Silent mode for hooks

Exit codes:
    0 = Token valid (or refreshed successfully)
    1 = Token invalid and refresh failed
    2 = No credentials file
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Configuration
_DEFAULT_CLAUDE_HOME = r"C:\Users\Dennis\.claude" if sys.platform == "win32" else str(Path.home() / ".claude")
CLAUDE_HOME = os.environ.get("CLAUDE_HOME", _DEFAULT_CLAUDE_HOME)
CREDS_FILE = Path.home() / ".claude" / ".credentials.json"
_REFRESH_EXT = "refresh-claude-token.py"  # Cross-platform Python script
REFRESH_SCRIPT = Path(CLAUDE_HOME) / "scripts" / _REFRESH_EXT
BUFFER_SECONDS = 600  # Refresh 10 min before expiry


def get_token_status():
    """Return (valid, expires_in_seconds, has_refresh_token)"""
    if not CREDS_FILE.exists():
        return False, 0, False

    try:
        with open(CREDS_FILE) as f:
            creds = json.load(f)

        oauth = creds.get("claudeAiOauth", {})
        expires_at = oauth.get("expiresAt", 0)
        refresh_token = oauth.get("refreshToken")

        now_ms = int(time.time() * 1000)
        expires_in_sec = (expires_at - now_ms) // 1000

        has_refresh = bool(refresh_token and refresh_token != "null")
        valid = expires_in_sec > BUFFER_SECONDS

        return valid, expires_in_sec, has_refresh
    except (json.JSONDecodeError, KeyError):
        return False, 0, False


def refresh_token(force=False):
    """Attempt to refresh the token. Returns True on success."""
    if not REFRESH_SCRIPT.exists():
        # Fallback to direct call
        _fallback_name = "claude-github.py"  # Cross-platform Python script
        script = Path(CLAUDE_HOME) / "scripts" / _fallback_name
        if script.exists():
            args = [sys.executable, str(script), "refresh"]
        else:
            return False
    else:
        args = [sys.executable, str(REFRESH_SCRIPT)]

    if force:
        args.append("--force")

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=60
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def format_time(seconds):
    """Format seconds into human readable string."""
    if seconds < 0:
        return "EXPIRED"
    hours = seconds // 3600
    mins = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def main():
    quiet = "--quiet" in sys.argv or "-q" in sys.argv
    command = "check"

    for arg in sys.argv[1:]:
        if arg in ("help", "--help", "-h"):
            print(__doc__.strip())
            sys.exit(0)
        if arg in ("check", "status"):
            command = arg
            break

    if not CREDS_FILE.exists():
        if not quiet:
            print("[x] No credentials file - run 'claude auth login'")
        sys.exit(2)

    valid, expires_in, has_refresh = get_token_status()

    if command == "status":
        if valid:
            print(f"[+] Token valid for {format_time(expires_in)}")
        elif expires_in > 0:
            print(f"[!] Token expires in {format_time(expires_in)}")
        else:
            print("[x] Token EXPIRED")

        if has_refresh:
            print("[+] Refresh token present")
        else:
            print("[x] No refresh token")

        sys.exit(0 if valid else 1)

    # Check command
    if valid:
        if not quiet:
            print(f"[+] Token valid ({format_time(expires_in)})")
        sys.exit(0)

    # Token needs refresh
    if not has_refresh:
        if not quiet:
            print("[x] Token expired and no refresh token - run 'claude auth login'")
        sys.exit(1)

    if not quiet:
        print(f"[!] Token {'expired' if expires_in <= 0 else 'expiring soon'} - refreshing...")

    if refresh_token():
        # Verify refresh worked
        valid, expires_in, _ = get_token_status()
        if valid:
            if not quiet:
                print(f"[+] Token refreshed ({format_time(expires_in)})")
            sys.exit(0)

    if not quiet:
        print("[x] Token refresh failed - run 'claude auth login'")
    sys.exit(1)


if __name__ == "__main__":
    main()
