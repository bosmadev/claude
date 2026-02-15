#!/usr/bin/env python3
"""Unified Claude GitHub Token Management.

Usage: claude-github.py <command> [options]

Commands:
    init              Initialize current repo with Claude workflow
    refresh           Refresh local OAuth token
    sync [--all]      Push token to GitHub secrets (current repo or all)
    status            Show token status across repos
    help              Show usage
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# sys.path needed when invoked as hook/standalone
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import compat utilities
from scripts.compat import get_claude_home, IS_WINDOWS

# Configuration
CLAUDE_HOME = get_claude_home()
CREDS_FILE = Path.home() / ".claude" / ".credentials.json"
LOG_FILE = Path.home() / ".claude" / "debug" / "token-refresh.log"
BUFFER_SECONDS = 600  # Refresh 10 min before expiry

# Timestamp threshold: values below this are epoch seconds, above are milliseconds
TIMESTAMP_MS_THRESHOLD = 10**12  # ~2286 in seconds, ~Sept 2001 in milliseconds

# Colors (ANSI - works on Windows Terminal and most modern terminals)
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
GREY = "\033[38;5;245m"
RESET = "\033[0m"

# Repo search paths - platform dependent
if IS_WINDOWS:
    _default_search_paths = [
        Path.home() / "Desktop",
        Path.home() / ".claude",
        Path.home() / "code",
        Path.home() / "repos",
        Path.home() / "projects",
        Path(os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude"))),
    ]
else:
    _default_search_paths = [
        Path.home() / "Desktop",
        Path.home() / ".claude",
        Path.home() / "code",
        Path.home() / "repos",
        Path.home() / "projects",
        Path("/usr/share/claude"),
        Path("/home/dennis/Desktop"),
        Path("/home/dennis/code"),
        Path("/home/dennis/repos"),
        Path("/home/dennis/projects"),
    ]


def get_repo_search_paths() -> list[Path]:
    """Get repo search paths from env or defaults."""
    env_paths = os.environ.get("CLAUDE_REPO_PATHS", "")
    if env_paths:
        separator = ";" if IS_WINDOWS else ":"
        return [Path(p) for p in env_paths.split(separator) if p]
    return _default_search_paths


def ensure_log_dir() -> None:
    """Ensure log directory exists."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def _sanitize_message(message: str) -> str:
    """Sanitize log messages to prevent credential leakage."""
    import re
    # Redact common token patterns
    sanitized = re.sub(r'(access[_-]?token["\s:=]+)([a-zA-Z0-9_\-\.]{20,})', r'\1[REDACTED]', message, flags=re.IGNORECASE)
    sanitized = re.sub(r'(refresh[_-]?token["\s:=]+)([a-zA-Z0-9_\-\.]{20,})', r'\1[REDACTED]', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(bearer\s+)([a-zA-Z0-9_\-\.]{20,})', r'\1[REDACTED]', sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r'(sk-ant-[a-zA-Z0-9_\-]{20,})', r'[REDACTED_API_KEY]', sanitized)
    return sanitized

def log(message: str) -> None:
    """Log a message with timestamp to both stdout and log file with automatic rotation."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sanitized = _sanitize_message(message)
    line = f"[{timestamp}] {sanitized}"
    print(line)
    try:
        # Rotate log if it exceeds 10MB
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 10 * 1024 * 1024:
            backup_path = LOG_FILE.with_suffix(".log.old")
            if backup_path.exists():
                backup_path.unlink()
            LOG_FILE.rename(backup_path)

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def read_credentials() -> dict | None:
    """Read and parse the credentials JSON file with schema validation."""
    if not CREDS_FILE.is_file():
        return None
    try:
        with open(CREDS_FILE, "r", encoding="utf-8") as f:
            data = json.loads(f.read())

        # Schema validation - ensure required structure exists
        required_keys = ["claudeAiOauth"]
        oauth_keys = ["accessToken", "expiresAt", "refreshToken"]

        if not isinstance(data, dict):
            debug_log("Invalid credentials: not a dict")
            return None

        for key in required_keys:
            if key not in data:
                debug_log(f"Missing required key: {key}")
                return None

        oauth = data.get("claudeAiOauth", {})
        if not isinstance(oauth, dict):
            debug_log("Invalid claudeAiOauth: not a dict")
            return None

        for key in oauth_keys:
            if key not in oauth:
                debug_log(f"Missing oauth key: {key}")
                return None

        return data
    except (json.JSONDecodeError, OSError) as e:
        debug_log(f"Credentials read error: {e}")
        return None


def write_credentials(data: dict, max_retries: int = 3) -> None:
    """Write credentials to file with appropriate permissions and retry logic."""
    import time

    for attempt in range(max_retries):
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".json",
                dir=str(CREDS_FILE.parent),
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(json.dumps(data, indent=2))
                tmp_path = Path(tmp.name)

            shutil.move(str(tmp_path), str(CREDS_FILE))
            return  # Success

        except (OSError, PermissionError) as e:
            if attempt < max_retries - 1:
                # Exponential backoff: 0.1s, 0.2s, 0.4s
                delay = 0.1 * (2 ** attempt)
                debug_log(f"Write failed (attempt {attempt + 1}), retrying in {delay}s: {e}")
                time.sleep(delay)
            else:
                debug_log(f"Write failed after {max_retries} attempts: {e}")
                raise

    if IS_WINDOWS:
        pass  # Windows file permissions handled by user account
    else:
        os.chmod(str(CREDS_FILE), 0o600)


def get_local_token_mtime() -> float:
    """Get local token file modification time as epoch seconds."""
    try:
        return os.path.getmtime(str(CREDS_FILE))
    except OSError:
        return 0.0


def get_repo_secret_mtime(repo: str) -> float:
    """Get repo secret updated_at as epoch seconds, 0 if not found."""
    try:
        result = subprocess.run(
            ["gh", "secret", "list", "--repo", repo, "--json", "name,updated_at"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            if result.stderr:
                debug_log(f"Failed to get secret for {repo}: {result.stderr.strip()}")
            return 0.0

        secrets = json.loads(result.stdout)
        for secret in secrets:
            if secret.get("name") == "CLAUDE_CODE_OAUTH_TOKEN":
                updated_at_str = secret.get("updated_at", "")
                if updated_at_str:
                    try:
                        dt = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                        return dt.timestamp()
                    except (ValueError, TypeError):
                        return 0.0
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as exc:
        debug_log(f"Error accessing secret for {repo}: {exc}")
    return 0.0


def find_all_repos() -> list[str]:
    """Find all GitHub repos across search paths."""
    repos = set()
    search_paths = get_repo_search_paths()

    for search_path in search_paths:
        if not search_path.is_dir():
            continue

        # Use os.walk with maxdepth instead of unbounded glob
        try:
            for root, dirs, files in os.walk(search_path):
                # Calculate depth
                try:
                    depth = len(Path(root).relative_to(search_path).parts)
                except ValueError:
                    continue

                # Enforce maxdepth 3
                if depth >= 3:
                    dirs.clear()  # Don't recurse deeper
                    continue

                # Check for .git directory
                if ".git" in dirs:
                    repo_path = Path(root)
                    try:
                        result = subprocess.run(
                            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                            capture_output=True,
                            text=True,
                            cwd=str(repo_path),
                            timeout=15,
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            repos.add(result.stdout.strip())
                    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                        pass
                    except PermissionError:
                        debug_log(f"Permission denied accessing {repo_path}")
                        continue
        except PermissionError:
            # Skip directories we can't access
            debug_log(f"Permission denied scanning {search_path}")
            continue
        except OSError as exc:
            debug_log(f"Error scanning {search_path}: {exc}")
            continue

    return sorted(repos)


# ============================================================================
# STATUS - Show token status across repos
# ============================================================================
def cmd_status() -> None:
    """Show token status and repo list."""
    print("Claude GitHub Token Status")
    print("==========================")
    print()

    # Check credentials file
    if not CREDS_FILE.is_file():
        print(f"{RED}x No credentials file at {CREDS_FILE}{RESET}")
        print("  Run: claude auth login")
        sys.exit(1)

    creds = read_credentials()
    if not creds:
        print(f"{RED}x Cannot parse credentials file{RESET}")
        sys.exit(1)

    # Extract token info
    oauth = creds.get("claudeAiOauth", {})
    expires_at = oauth.get("expiresAt", 0)
    refresh_token = oauth.get("refreshToken", "")

    # Calculate expiry
    now_ms = int(time.time() * 1000)
    time_until_expiry_sec = (expires_at - now_ms) // 1000
    local_mtime = get_local_token_mtime()

    print("Local Token:")
    if time_until_expiry_sec < 0:
        print(f"  {RED}x Access token EXPIRED{RESET}")
    elif time_until_expiry_sec < 600:
        print(f"  {YELLOW}! Access token expires in {time_until_expiry_sec}s{RESET}")
    else:
        hours = time_until_expiry_sec // 3600
        mins = (time_until_expiry_sec % 3600) // 60
        print(f"  {GREEN}+ Access token valid for {hours}h {mins}m{RESET}")

    if refresh_token and refresh_token != "null":
        print(f"  {GREEN}+ Refresh token present{RESET}")
    else:
        print(f"  {RED}x No refresh token{RESET}")

    # Check timer status (platform-dependent)
    print()
    print("Auto-refresh Timer:")

    if IS_WINDOWS:
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", "ClaudeTokenRefresh"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                print(f"  {GREEN}+ Active (Task Scheduler){RESET}")
            else:
                print(f"  {YELLOW}! Not active{RESET}")
                print(f"  Install with: python {CLAUDE_HOME / 'scripts' / 'install-token-timer.py'}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            print(f"  {YELLOW}! Cannot check Task Scheduler{RESET}")
    else:
        # Check systemd timer (user and system level)
        timer_found = False

        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-active", "claude-token-refresh.timer"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                timer_found = True
                # Try to get next elapse time
                next_result = subprocess.run(
                    [
                        "systemctl", "--user", "show",
                        "claude-token-refresh.timer",
                        "--property=NextElapseUSecRealtime",
                        "--value",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                next_val = next_result.stdout.strip().split("\n")[0] if next_result.returncode == 0 else ""
                if next_val and next_val != "n/a":
                    try:
                        next_sec = int(next_val) // 1000000
                        next_date = datetime.fromtimestamp(next_sec).strftime("%H:%M:%S")
                        print(f"  {GREEN}+ Active (user) - next refresh at {next_date}{RESET}")
                    except (ValueError, OSError):
                        print(f"  {GREEN}+ Active (user){RESET}")
                else:
                    print(f"  {GREEN}+ Active (user){RESET}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        if not timer_found:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", "claude-token-refresh.timer"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    timer_found = True
                    print(f"  {GREEN}+ Active (system){RESET}")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        if not timer_found:
            print(f"  {YELLOW}! Not active{RESET}")
            print("  Start with: systemctl --user start claude-token-refresh.timer")

    # Scan repos
    print()
    print("GitHub Repositories:")
    search_paths = get_repo_search_paths()
    paths_str = " ".join(str(p) for p in search_paths)
    print(f"  {GREY}(scanning: {paths_str}){RESET}")
    print()

    repos = find_all_repos()

    if not repos:
        print(f"  {GREY}No repos found{RESET}")
    else:
        now_epoch = time.time()
        for repo in repos:
            secret_mtime = get_repo_secret_mtime(repo)
            if secret_mtime > 0:
                if secret_mtime < local_mtime:
                    ago_hours = int((now_epoch - secret_mtime) / 3600)
                    print(f"  {YELLOW}! {repo}{RESET} (stale - {ago_hours}h old, needs sync)")
                else:
                    print(f"  {GREEN}+ {repo}{RESET} (up-to-date)")
            else:
                print(f"  {GREY}o {repo}{RESET} (no token or no access)")


# ============================================================================
# REFRESH - Refresh local OAuth token
# ============================================================================
def cmd_refresh(force: bool = False, max_retries: int = 3) -> None:
    """Refresh local OAuth token with retry logic and SSL verification."""
    import ssl
    import time as time_mod

    # Create SSL context for certificate verification
    ssl_context = ssl.create_default_context()

    log("Starting token refresh...")

    if not CREDS_FILE.is_file():
        log(f"No credentials file at {CREDS_FILE} - run 'claude auth login'")
        sys.exit(1)

    creds = read_credentials()
    if not creds:
        log("Cannot parse credentials file")
        sys.exit(1)

    oauth = creds.get("claudeAiOauth", {})
    expires_at = oauth.get("expiresAt", 0)
    refresh_token = oauth.get("refreshToken", "")

    if not refresh_token or refresh_token == "null":
        log("No refresh token found - run 'claude auth login'")
        sys.exit(1)

    now_ms = int(time.time() * 1000)
    time_until_expiry_sec = (expires_at - now_ms) // 1000

    # Check if refresh needed (unless --force)
    if not force and time_until_expiry_sec > BUFFER_SECONDS:
        log(f"Token still valid for {time_until_expiry_sec}s - use --force to refresh anyway")
        sys.exit(0)

    log("Refreshing token...")

    # POST to Anthropic OAuth endpoint
    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://console.anthropic.com/v1/oauth/token",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    # Retry logic with exponential backoff
    last_error = None
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
            break  # Success
        except urllib.error.HTTPError as e:
            # Auth errors (401/403) should not retry
            if e.code in (401, 403):
                try:
                    error_body = json.loads(e.read().decode("utf-8"))
                    # Sanitize logs - don't include tokens
                    error_msg = error_body.get("error", error_body.get("message", "Auth error"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    error_msg = f"HTTP {e.code}"
                log(f"{RED}x Refresh failed: {error_msg}{RESET}")
                sys.exit(1)
            last_error = e
        except urllib.error.URLError as e:
            last_error = e

        # Retry with exponential backoff for transient errors
        if attempt < max_retries - 1:
            delay = 0.5 * (2 ** attempt)
            log(f"Request failed, retrying in {delay}s...")
            time_mod.sleep(delay)
    else:
        # All retries exhausted
        log(f"{RED}x Refresh failed after {max_retries} attempts: {last_error}{RESET}")
        sys.exit(1)

    if "access_token" not in response_data:
        error_msg = response_data.get("error", response_data.get("message", "Unknown error"))
        log(f"{RED}x Refresh failed: {error_msg}{RESET}")
        sys.exit(1)

    new_access = response_data["access_token"]
    new_refresh = response_data.get("refresh_token", "")

    # Validate token format
    if not new_access or not isinstance(new_access, str) or len(new_access) < 20:
        log(f"{RED}x Refresh failed: received invalid access token format{RESET}")
        sys.exit(1)

    # Determine expiry: separate handling for expires_in (duration) vs expires_at (absolute)
    if "expires_in" in response_data:
        # Duration in seconds from now
        expires_in_sec = response_data["expires_in"]
        new_expires = now_ms + int(expires_in_sec * 1000)
    elif "expires_at" in response_data:
        # Absolute timestamp - determine if seconds or milliseconds
        expires_at_val = response_data["expires_at"]
        if isinstance(expires_at_val, (int, float)) and expires_at_val < TIMESTAMP_MS_THRESHOLD:
            # Epoch seconds (e.g. 1738300000) -> convert to ms
            new_expires = int(expires_at_val * 1000)
        else:
            # Already in milliseconds
            new_expires = int(expires_at_val)
    else:
        # Fallback: no expiry info, assume 2 hours
        new_expires = now_ms + 2 * 3600 * 1000
        log(f"{YELLOW}! No expiry info in response, assuming 2h{RESET}")

    # Update credentials
    creds["claudeAiOauth"]["accessToken"] = new_access
    creds["claudeAiOauth"]["expiresAt"] = new_expires

    if new_refresh and new_refresh != "null":
        creds["claudeAiOauth"]["refreshToken"] = new_refresh

    write_credentials(creds)

    hours = (new_expires - now_ms) // 1000 // 3600
    log(f"{GREEN}+ Token refreshed - valid for ~{hours}h{RESET}")


# ============================================================================
# SYNC - Push token to GitHub secrets (with stale detection)
# ============================================================================
def cmd_sync(sync_all: bool = False, force: bool = False) -> None:
    """Push token to GitHub secrets with gh CLI verification."""
    import shutil

    # Verify gh CLI is from expected location
    gh_path = shutil.which("gh")
    if not gh_path:
        print(f"{RED}x GitHub CLI (gh) not found in PATH{RESET}")
        sys.exit(1)

    # Log gh location for audit trail
    debug_log(f"Using gh CLI at: {gh_path}")

    if not CREDS_FILE.is_file():
        print(f"{RED}x No credentials file - run 'claude auth login'{RESET}")
        sys.exit(1)

    creds = read_credentials()
    if not creds:
        print(f"{RED}x Cannot parse credentials file{RESET}")
        sys.exit(1)

    token = creds.get("claudeAiOauth", {}).get("accessToken", "")

    if not token or token == "null":
        print(f"{RED}x No access token in credentials{RESET}")
        sys.exit(1)

    local_mtime = get_local_token_mtime()

    if sync_all:
        print("Syncing token to all repositories...")
        search_paths = get_repo_search_paths()
        paths_str = " ".join(str(p) for p in search_paths)
        print(f"  {GREY}(scanning: {paths_str}){RESET}")
        print()

        repos = find_all_repos()
        synced = 0
        skipped = 0
        failed = 0

        for repo in repos:
            secret_mtime = get_repo_secret_mtime(repo)

            # Skip if already up-to-date (unless --force)
            if not force and secret_mtime >= local_mtime and secret_mtime > 0:
                print(f"{GREY}  o {repo} (up-to-date, skipped){RESET}")
                skipped += 1
                continue

            try:
                result = subprocess.run(
                    ["gh", "secret", "set", "CLAUDE_CODE_OAUTH_TOKEN", "--repo", repo],
                    input=token,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    if secret_mtime == 0:
                        print(f"{GREEN}  + {repo} (new){RESET}")
                    else:
                        print(f"{GREEN}  + {repo} (updated){RESET}")
                    synced += 1
                else:
                    print(f"{YELLOW}  ! {repo} (failed or no access){RESET}")
                    failed += 1
            except (subprocess.TimeoutExpired, FileNotFoundError):
                print(f"{YELLOW}  ! {repo} (failed or no access){RESET}")
                failed += 1

            # Rate limiting: 200ms delay between API calls to avoid secondary rate limits
            if repo != repos[-1]:  # Skip delay after last repo
                time.sleep(0.2)

        print()
        print(f"Summary: {GREEN}{synced} synced{RESET}, {GREY}{skipped} skipped{RESET}, {YELLOW}{failed} failed{RESET}")

    else:
        # Current repo only
        try:
            result = subprocess.run(
                ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            repo = result.stdout.strip() if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError):
            repo = ""

        if not repo:
            print(f"{RED}x Not in a GitHub repo - run from repo directory or use --all{RESET}")
            sys.exit(1)

        secret_mtime = get_repo_secret_mtime(repo)

        # Check if sync needed (unless --force)
        if not force and secret_mtime >= local_mtime and secret_mtime > 0:
            print(f"{GREY}o {repo} already up-to-date (use --force to sync anyway){RESET}")
            sys.exit(0)

        try:
            result = subprocess.run(
                ["gh", "secret", "set", "CLAUDE_CODE_OAUTH_TOKEN", "--repo", repo],
                input=token,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                print(f"{GREEN}+ Token synced to {repo}{RESET}")
            else:
                print(f"{RED}x Failed to sync token to {repo}{RESET}")
                sys.exit(1)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print(f"{RED}x Failed to sync token to {repo}{RESET}")
            sys.exit(1)


# ============================================================================
# INIT - Initialize repo with Claude workflow
# ============================================================================
def cmd_init() -> None:
    """Initialize repo with Claude workflow."""
    cwd = Path.cwd()

    if not (cwd / ".git").exists():
        print(f"{RED}x Not a git repository - run from repo root{RESET}")
        sys.exit(1)

    print("Initializing Claude GitHub integration...")

    # Create directories
    (cwd / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (cwd / ".github" / "ISSUE_TEMPLATE").mkdir(parents=True, exist_ok=True)

    template_dir = CLAUDE_HOME / ".github"

    if template_dir.is_dir():
        # Copy template files
        shutil.copytree(str(template_dir), str(cwd / ".github"), dirs_exist_ok=True)
        print(f"{GREEN}+ Template files copied{RESET}")
    else:
        # Create minimal workflow
        print("Creating minimal workflow...")
        workflow_content = """\
name: Claude Code Review
on:
  pull_request:
  issue_comment:
    types: [created]

jobs:
  claude:
    if: contains(github.event.comment.body, '@claude') || github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: anthropics/claude-code-action@v1
        with:
          anthropic_api_key: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
"""
        workflow_path = cwd / ".github" / "workflows" / "claude.yml"
        with open(workflow_path, "w", encoding="utf-8") as f:
            f.write(workflow_content)
        print(f"{GREEN}+ Workflow created{RESET}")

    # Sync token to this repo
    cmd_sync()

    print()
    print("Next steps:")
    print("  1. git add .github && git commit -m 'Add Claude GitHub integration'")
    print("  2. git push")
    print("  3. Test with: @claude please review this PR")


# ============================================================================
# HELP
# ============================================================================
def cmd_help() -> None:
    """Show usage information."""
    print("Claude GitHub Token Management")
    print()
    print("Usage: claude-github.py <command> [options]")
    print()
    print("Commands:")
    print("  status                    Show token status and repo list")
    print("  refresh [--force]         Refresh local OAuth token")
    print("  sync [--all] [--force]    Push token to GitHub secrets")
    print("  init                      Initialize repo with Claude workflow")
    print()
    print("Options:")
    if IS_WINDOWS:
        print("  --all       Sync to all repos (searches ~/Desktop, ~/code, ~/.claude, etc.)")
    else:
        print("  --all       Sync to all repos (searches ~/Desktop, ~/code, /usr/share/claude, etc.)")
    print("  --force     Sync even if repo secret is already up-to-date")
    print()
    print("Examples:")
    print("  claude-github.py status             # Check token expiry + stale repos")
    print("  claude-github.py refresh            # Refresh if expiring soon")
    print("  claude-github.py refresh --force    # Force refresh now")
    print("  claude-github.py sync               # Sync to current repo (if stale)")
    print("  claude-github.py sync --force       # Force sync to current repo")
    print("  claude-github.py sync --all         # Sync to all stale repos")
    print("  claude-github.py sync --all --force # Force sync to all repos")
    print("  claude-github.py init               # Setup Claude in current repo")


# ============================================================================
# MAIN
# ============================================================================
def main() -> None:
    """Main entry point."""
    ensure_log_dir()

    args = sys.argv[1:]
    command = args[0] if args else "help"

    if command == "status":
        cmd_status()
    elif command == "refresh":
        force = "--force" in args[1:]
        cmd_refresh(force=force)
    elif command == "sync":
        sync_all = "--all" in args[1:]
        force = "--force" in args[1:]
        cmd_sync(sync_all=sync_all, force=force)
    elif command == "init":
        cmd_init()
    elif command in ("help", "--help", "-h"):
        cmd_help()
    else:
        print(f"{RED}Unknown command: {command}{RESET}")
        cmd_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
