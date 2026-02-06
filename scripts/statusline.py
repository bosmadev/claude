#!/usr/bin/env python3
"""Claude Code Statusline Script (Python port of statusline.sh).

Format: Opus 4.5 Engineer 25% | 32%/59m | $0.00 | 0%/10% | main@abc123 »1«3 [+0|~2|?5]
Reads JSON input from stdin (Claude Code statusLine protocol).

Optimized for speed:
- Parallel git commands via ThreadPoolExecutor
- Single git status --porcelain for staged/modified/untracked
- Stale-while-revalidate for usage API
- Last-output cache fallback for post-/clear persistence
"""

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Timeout guard — kill process if stdin hangs (Windows-safe)
# ---------------------------------------------------------------------------
def _timeout_cleanup():
    """Clean shutdown on timeout - allows proper cleanup."""
    try:
        sys.exit(0)
    except SystemExit:
        os._exit(0)

_kill_timer = threading.Timer(5, _timeout_cleanup)
_kill_timer.daemon = True
_kill_timer.start()

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Nord-inspired color palette (Variation A)
# ---------------------------------------------------------------------------
SALMON        = "\033[38;5;173m"        # Model name (Opus 4.5)
AURORA_GREEN  = "\033[38;5;108m"        # Cost, context %, ahead, staged
AURORA_YELLOW = "\033[38;5;222m"        # Modified, warnings
AURORA_RED    = "\033[38;5;131m"        # Behind, untracked, high usage
GREY          = "\033[38;5;245m"        # Style name, commit hash, zero counts
DARK_GREY     = "\033[38;5;240m"        # Separators, parentheses
SNOW_WHITE    = "\033[38;5;253m"        # Branch name (softer white)
RESET         = "\033[0m"
BRIGHT_WHITE  = "\033[1;37m"            # Ralph completed counts
CYAN          = "\033[36m"              # Ralph progress elements
YELLOW        = "\033[33m"              # Struggle alert

# Build intelligence colors (for statusline build status)
BUILD_OK      = "\033[38;5;108m"        # Green - normal operation
BUILD_WARN    = "\033[38;5;222m"        # Yellow/Amber - minor issues
BUILD_ERROR   = "\033[38;5;131m"        # Red - build failures
BUILD_CRITICAL= "\033[38;5;196m"        # Bright red - multiple struggles


CACHE_DIR = Path.home() / ".claude"

# Style display mapping (Element 7)
STYLE_DISPLAY = {"Engineer": "⚙", "Default": "·"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_ralph_progress(cwd: str) -> dict | None:
    """Read Ralph progress.json, return dict or None if missing/stale/invalid.

    Returns None if:
    - File doesn't exist
    - File is empty or has parse error
    - updated_at is older than 5 minutes
    """
    try:
        progress_path = Path(cwd) / ".claude" / "ralph" / "progress.json"
        if not progress_path.exists():
            return None

        content = progress_path.read_text(encoding="utf-8").strip()
        if not content:
            return None

        data = json.loads(content)

        # TODO-P2: Validate data structure before use (check impl/review/total keys exist) - Review agent review-1

        # Check staleness (>5 minutes old)
        updated_at = data.get("updated_at", "")
        if updated_at:
            try:
                updated_dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                now = datetime.now(updated_dt.tzinfo if updated_dt.tzinfo else None)
                age_seconds = (now - updated_dt).total_seconds()
                if age_seconds > 300:  # 5 minutes
                    return None
            except (ValueError, TypeError):
                # Invalid timestamp format - treat as stale
                return None

        return data
    except (OSError, json.JSONDecodeError, KeyError):
        return None

def _read_team_config(session_id: str) -> dict | None:
    """Read active team config from ~/.claude/teams/*/config.json.

    Returns team data with member count if:
    - CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 env var is set
    - A team config exists where leadSessionId matches current session_id

    Returns None if no active team or Agent Teams not enabled.
    """
    # Check if Agent Teams feature is enabled
    if os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS") != "1":
        return None

    # TODO-P3: Add validation for session_id format before glob search - Review agent review-1

    try:
        teams_dir = CACHE_DIR / "teams"
        if not teams_dir.exists():
            return None

        # Search all team configs for matching leadSessionId
        for team_config_path in teams_dir.glob("*/config.json"):
            try:
                config = json.loads(team_config_path.read_text(encoding="utf-8"))
                if config.get("leadSessionId") == session_id:
                    # Found matching team
                    members = config.get("members", [])
                    # TODO-P2: Validate members is a list before calling len() - Review agent review-1
                    return {
                        "team_name": config.get("name", ""),
                        "member_count": len(members),
                        "members": members
                    }
            except (OSError, json.JSONDecodeError, KeyError):
                continue

        return None
    except (OSError, PermissionError):
        return None

def read_build_intelligence(cwd: str) -> str:
    """
    Read build intelligence data and return formatted statusline segment.

    Returns empty string if:
    - File doesn't exist
    - File is empty or has parse error
    - No struggling agents detected

    Returns color-coded status:
    - Green (BUILD_OK): All agents healthy
    - Yellow (BUILD_WARN): 1 agent struggling
    - Red (BUILD_ERROR): 2-3 agents struggling
    - Bright Red (BUILD_CRITICAL): 4+ agents struggling
    """
    # TODO-P2: Add staleness check (compare with _read_ralph_progress 5min TTL) - Review agent review-1
    try:
        intel_path = Path(cwd) / ".claude" / "ralph" / "build-intelligence.json"
        if not intel_path.exists():
            return ""

        content = intel_path.read_text(encoding="utf-8").strip()
        if not content:
            return ""

        data = json.loads(content)

        # Extract struggle summary
        summary = data.get("summary", {})
        # TODO-P2: Validate summary is dict before calling .get() - Review agent review-1
        struggling = summary.get("total_struggling", 0)
        total = summary.get("total_agents", 0)

        # No agents or no struggling - show nothing
        if total == 0 or struggling == 0:
            return ""

        # Choose color based on struggle count
        if struggling == 1:
            color = BUILD_WARN
        elif struggling <= 3:
            color = BUILD_ERROR
        else:
            color = BUILD_CRITICAL

        # Format: "🔥2" for 2 struggling agents
        return f" {color}🔥{struggling}{RESET}"

    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        # Gracefully handle any read/parse errors
        return ""

def git_run(cwd: str, *args: str) -> str:
    """Run a git command and return stripped stdout, or '' on failure."""
    try:
        r = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=3,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except subprocess.TimeoutExpired:
        # Git command timed out - likely hung on network operation
        return ""
    except FileNotFoundError:
        # Git not in PATH - expected in non-git environments
        return ""
    except (OSError, PermissionError):
        # Other OS-level errors (permission denied, etc.)
        return ""


def git_batch(cwd: str) -> dict:
    """Run all git commands in parallel, return results dict."""
    commands = {
        "git_dir":     ("rev-parse", "--git-dir"),
        "branch":      ("branch", "--show-current"),
        "remote_url":  ("config", "--get", "remote.origin.url"),
        "commit_hash": ("rev-parse", "--short", "HEAD"),
        "status":      ("status", "--porcelain"),
    }

    results = {}

    def _run(key, args):
        return key, git_run(cwd, *args)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_run, k, v): k for k, v in commands.items()}
        for f in as_completed(futures):
            try:
                key, val = f.result()
                results[key] = val
            except Exception:
                results[futures[f]] = ""

    # Only fetch ahead/behind if we have a branch and are in a git repo
    if results.get("git_dir") and results.get("branch"):
        branch = results["branch"]
        # Try upstream, then origin/branch
        upstream = git_run(cwd, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
        if upstream:
            counts_raw = git_run(cwd, "rev-list", "--left-right", "--count", f"origin/{branch}...HEAD")
            results["ahead_behind"] = counts_raw
        else:
            results["ahead_behind"] = ""
    else:
        results["ahead_behind"] = ""

    return results


def parse_porcelain_status(status_output: str) -> tuple:
    """Parse git status --porcelain output into (staged, modified, untracked) counts."""
    staged = 0
    modified = 0
    untracked = 0

    if not status_output:
        return staged, modified, untracked

    for line in status_output.splitlines():
        if len(line) < 2:
            continue
        x, y = line[0], line[1]

        if x == "?" and y == "?":
            untracked += 1
        else:
            # X column: staged changes (not space, not ?)
            if x not in (" ", "?", "!"):
                staged += 1
            # Y column: unstaged changes (not space, not ?)
            if y not in (" ", "?", "!"):
                modified += 1

    return staged, modified, untracked


def read_usage_cache(cache_path: Path) -> dict:
    """Read cached usage values, return dict with all fields."""
    result = {
        "all_weekly": "?",
        "sonnet_weekly": "?",
        "five_hour_pct": "?",
        "five_hour_resets_at": "",
    }
    if cache_path.exists() and cache_path.stat().st_size > 0:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            # TODO-P2: Add bounds check for utilization values (clamp 0-100 or warn on >100) - Review agent review-1
            # All-models weekly
            val = data.get("seven_day", {}).get("utilization", 0)
            result["all_weekly"] = str(int(float(val)))
            # Sonnet-only weekly
            val_s = data.get("seven_day_sonnet", {}).get("utilization", 0)
            result["sonnet_weekly"] = str(int(float(val_s)))
            # 5-hour session
            val_5h = data.get("five_hour", {}).get("utilization", 0)
            result["five_hour_pct"] = str(int(float(val_5h)))
            # Reset time
            result["five_hour_resets_at"] = data.get("five_hour", {}).get("resets_at", "")
        except json.JSONDecodeError:
            # Cache file corrupted - delete so next cycle triggers refresh
            try:
                cache_path.unlink(missing_ok=True)
            except OSError:
                pass
        except (OSError, PermissionError) as exc:
            # I/O error reading cache - log to stderr
            import sys
            print(f"[!] Cannot read usage cache: {exc}", file=sys.stderr)
        except (ValueError, TypeError, KeyError) as exc:
            # Data format error - cache structure changed
            import sys
            print(f"[!] Invalid usage cache format: {exc}", file=sys.stderr)
    return result


def minutes_until_reset(resets_at: str) -> str:
    """Calculate minutes from now until ISO timestamp reset. Returns e.g. '59'."""
    if not resets_at:
        return "?"
    try:
        reset_dt = datetime.fromisoformat(resets_at.replace("Z", "+00:00"))
        now = datetime.now(reset_dt.tzinfo)
        diff = (reset_dt - now).total_seconds()
        mins = max(0, int(diff / 60))
        return str(mins)
    except (ValueError, TypeError, AttributeError):
        return "?"


def refresh_usage_cache_bg(cache_path: Path) -> None:
    """Refresh usage cache in background thread (fire-and-forget)."""
    def _refresh():
        import urllib.request

        creds_path = Path.home() / ".claude" / ".credentials.json"
        token = ""
        try:
            creds = json.loads(creds_path.read_text(encoding="utf-8"))
            token = creds.get("claudeAiOauth", {}).get("accessToken", "")
        except (OSError, json.JSONDecodeError):
            return

        # Validate token format before using in header
        if not token or token == "null" or not isinstance(token, str) or len(token) < 20:
            return

        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                },
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                body = resp.read().decode("utf-8")
            # Atomic write: write to temp file then rename to prevent
            # empty cache from timeout-kill interrupting mid-write
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = cache_path.with_suffix(".tmp")
            tmp_path.write_text(body, encoding="utf-8")
            tmp_path.replace(cache_path)
        except Exception as exc:
            print(f"[!] Usage cache refresh failed: {exc}", file=sys.stderr)

    t = threading.Thread(target=_refresh, daemon=True)
    t.start()


def fetch_usage_data(cache_path: Path) -> dict:
    """Return usage data using stale-while-revalidate pattern.

    Always returns immediately from cache. Triggers background refresh
    if cache is older than 5 minutes.
    """
    now = int(time.time())
    cached = read_usage_cache(cache_path)

    # Check if cache needs refresh (>5 min old or missing)
    needs_refresh = True
    if cache_path.exists() and cache_path.stat().st_size > 0:
        try:
            mtime = int(os.path.getmtime(cache_path))
            needs_refresh = (now - mtime) > 300
        except OSError:
            pass

    if needs_refresh:
        refresh_usage_cache_bg(cache_path)

    return cached


def save_last_output(output: str) -> None:
    """Cache the last rendered statusline for fallback after /clear."""
    try:
        cache_file = CACHE_DIR / ".statusline-last"
        cache_file.write_text(output, encoding="utf-8")
    except OSError as exc:
        # Log write failures for debugging
        import sys
        print(f"[!] Cannot save statusline cache: {exc}", file=sys.stderr)


def load_last_output() -> str:
    """Load the last cached statusline output."""
    try:
        cache_file = CACHE_DIR / ".statusline-last"
        if cache_file.exists():
            return cache_file.read_text(encoding="utf-8")
    except OSError:
        pass
    return ""


def color_threshold(value_str: str, green_below: int, yellow_below: int) -> str:
    """Return color based on threshold: green < yellow < red."""
    if value_str == "?":
        return GREY
    try:
        v = int(value_str)
    except ValueError:
        return GREY
    if v < green_below:
        return AURORA_GREEN
    elif v < yellow_below:
        return AURORA_YELLOW
    else:
        return AURORA_RED


# ---------------------------------------------------------------------------
# Test Mode Mock Scenarios
# TODO-TEMP: Remove test mode after Ralph native teams migration (plan item #0)
# Test mode exists to verify statusline display without running full /start.
# Once Ralph tracks native team agents, this can be deleted.
# ---------------------------------------------------------------------------

MOCK_SCENARIOS = {
    "team_agents": {
        "name": "Team Agents (Active /start flow)",
        "stdin": {
            "cwd": ".",
            "session_id": "5b47e9a3-ba2a-4a3a-b91c-49aa1768909d",  # Match current Ralph session
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "effort": "high",
            "context_window": {"used_percentage": 35.5, "context_window_size": 200000},
            "output_style": {"name": "Engineer"},
            "cost": {"total_cost_usd": 1.23},
        },
        "ralph_progress": {
            "total": 10,
            "impl": {"total": 10, "completed": 3, "failed": 0},
            "review": {"total": 5, "completed": 1, "failed": 0},
            "model_mix": {"opus": 2, "sonnet": 2},
            "struggling": 0,
            "updated_at": datetime.now().isoformat() + "Z",
        },
        # TODO-P3: Add build_intelligence mock data for complete scenario coverage - Review agent review-1
    },
    "ralph_struggling": {
        "name": "Ralph Progress with Struggle Alert",
        "stdin": {
            "cwd": ".",
            "model": {"id": "claude-sonnet-4-5", "display_name": "Sonnet 4.5"},
            "effort": "medium",
            "context_window": {"used_percentage": 62.0, "context_window_size": 200000},
            "output_style": {"name": "Engineer"},
            "cost": {"total_cost_usd": 0.45},
        },
        "ralph_progress": {
            "total": 8,
            "impl": {"total": 8, "completed": 5, "failed": 1},
            "review": {"total": 0, "completed": 0, "failed": 0},
            "model_mix": {"opus": 0, "sonnet": 6},
            "struggling": 1,
            "updated_at": datetime.now().isoformat() + "Z",
        },
    },
    "context_window_high": {
        "name": "High Context Window Usage (1M context)",
        "stdin": {
            "cwd": ".",
            "model": {"id": "claude-sonnet-4-5-1m", "display_name": "Sonnet[1M]"},
            "effort": "low",
            "context_window": {"used_percentage": 85.0, "context_window_size": 1000000},
            "output_style": {"name": "Default"},
            "cost": {"total_cost_usd": 0.89},
        },
        "ralph_progress": None,
    },
    "no_ralph": {
        "name": "No Ralph (Standard Session)",
        "stdin": {
            "cwd": ".",
            "model": {"id": "claude-opus-4-6", "display_name": "Opus 4.6"},
            "effort": "medium",
            "context_window": {"used_percentage": 15.0, "context_window_size": 200000},
            "output_style": {"name": "Engineer"},
            "cost": {"total_cost_usd": 0.12},
        },
        "ralph_progress": None,
    },
}


def run_test_mode() -> None:
    """Run statusline in test mode, cycling through mock scenarios."""
    print("\n=== Statusline Test Mode ===\n", file=sys.stderr)

    for scenario_key, scenario in MOCK_SCENARIOS.items():
        print(f"\n--- Scenario: {scenario['name']} ---", file=sys.stderr)

        # Prepare mock ralph progress file if needed
        # NOTE: Write to cwd-based path, not CACHE_DIR (matches _read_ralph_progress logic)
        cwd_for_test = scenario["stdin"].get("cwd", ".")
        if scenario.get("ralph_progress"):
            progress_path = Path(cwd_for_test) / ".claude" / "ralph" / "progress.json"
            progress_path.parent.mkdir(parents=True, exist_ok=True)
            progress_path.write_text(json.dumps(scenario["ralph_progress"], indent=2), encoding="utf-8")
        else:
            # Clear ralph progress
            progress_path = Path(cwd_for_test) / ".claude" / "ralph" / "progress.json"
            if progress_path.exists():
                progress_path.unlink()

        # Mock stdin by writing to temp file and reading it
        mock_stdin = json.dumps(scenario["stdin"])

        # Save original stdin
        original_stdin = sys.stdin

        try:
            # Replace stdin with mock data
            from io import StringIO
            sys.stdin = StringIO(mock_stdin)

            # Run main logic
            main()

            print("", file=sys.stderr)  # Newline after output

        finally:
            # Restore original stdin
            sys.stdin = original_stdin

        time.sleep(0.5)  # Brief pause between scenarios

    print("\n=== Test Mode Complete ===\n", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # ------------------------------------------------------------------
    # Read JSON input from stdin
    # ------------------------------------------------------------------
    raw_input = sys.stdin.read()
    try:
        inp = json.loads(raw_input)
    except json.JSONDecodeError:
        inp = {}

    # Validate JSON structure
    if not isinstance(inp, dict):
        inp = {}

    cwd     = inp.get("cwd", ".")

    # Model display: prefer .model-info (written by SessionStart hook) for "Opus 4.5" style
    model = "Claude"
    model_info_path = CACHE_DIR / ".model-info"
    try:
        if model_info_path.exists():
            mi = json.loads(model_info_path.read_text(encoding="utf-8"))
            model = mi.get("display", "Claude") or "Claude"
    except (json.JSONDecodeError, OSError):
        pass

    # Fallback: parse from statusline input if .model-info not available
    if model == "Claude":
        model_val = inp.get("model", "Claude")
        if isinstance(model_val, dict):
            model = (model_val.get("display_name", "Claude") or "Claude").split()[0]
        else:
            model = str(model_val).split()[0] if model_val else "Claude"

    # ------------------------------------------------------------------
    # Effort indicator (Opus 4.6 only: low/medium/high)
    # ------------------------------------------------------------------
    effort_raw = ""
    # Try multiple possible field locations in stdin JSON
    if isinstance(inp.get("effort"), str):
        effort_raw = inp["effort"]
    elif isinstance(inp.get("output_config"), dict):
        effort_raw = inp["output_config"].get("effort", "")
    elif isinstance(inp.get("reasoning_effort"), str):
        effort_raw = inp["reasoning_effort"]
    # Fallback: check environment variable
    if not effort_raw:
        effort_raw = os.environ.get("CLAUDE_CODE_EFFORT_LEVEL", "")

    EFFORT_CFG = {
        "low":    {"sym": "\u2193", "color": AURORA_GREEN},    # ↓ Green
        "medium": {"sym": "\u2192", "color": GREY},             # → Grey
        "high":   {"sym": "\u2191", "color": AURORA_YELLOW},    # ↑ Yellow
    }
    cfg = EFFORT_CFG.get(effort_raw.lower().strip()) if effort_raw else None
    effort_display = f" {cfg['color']}{cfg['sym']}{RESET}" if cfg else ""

    ctx_val = inp.get("context_window", {})
    pct     = int(float(ctx_val.get("used_percentage", 0) if isinstance(ctx_val, dict) else 0))
    style_val = inp.get("output_style", {})
    style_raw = (style_val.get("name", "default") if isinstance(style_val, dict) else str(style_val)) or "default"
    style_capitalized = style_raw[0].upper() + style_raw[1:]  # capitalize first letter
    style = STYLE_DISPLAY.get(style_capitalized, style_capitalized[0:3])  # Element 7: gear icon

    # Context % color
    ctx_color = color_threshold(str(pct), 50, 80)

    # Context window suffix: show /1M when sonnet[1m] is active
    model_raw_str = inp.get("model", "")
    if isinstance(model_raw_str, dict):
        model_raw_str = model_raw_str.get("name", "") or model_raw_str.get("id", "")
    context_suffix = "/1M" if "[1m]" in str(model_raw_str).lower() else ""

    # ------------------------------------------------------------------
    # Usage data (stale-while-revalidate, never blocks)
    # ------------------------------------------------------------------
    cache_path = CACHE_DIR / ".usage-cache"
    usage = fetch_usage_data(cache_path)

    all_weekly = usage["all_weekly"]
    sonnet_weekly = usage["sonnet_weekly"]
    five_hour = usage["five_hour_pct"]
    minutes_reset = minutes_until_reset(usage["five_hour_resets_at"])

    # Color thresholds
    weekly_color = color_threshold(all_weekly, 80, 90)
    sonnet_color = color_threshold(sonnet_weekly, 80, 90)
    five_hour_color = color_threshold(five_hour, 70, 90)

    # ------------------------------------------------------------------
    # Session cost (Element 5)
    # ------------------------------------------------------------------
    session_cost = inp.get("cost", {}).get("total_cost_usd", 0)
    cost_fmt = f"{session_cost:.2f}"

    # ------------------------------------------------------------------
    # Git info (parallel batch)
    # ------------------------------------------------------------------
    git_section = ""

    git_data = git_batch(cwd)

    if git_data.get("git_dir"):
        branch      = git_data.get("branch", "")
        remote_url  = git_data.get("remote_url", "")
        commit_hash = git_data.get("commit_hash", "")

        # Normalise remote URL to HTTPS for hyperlinks
        # TODO-P3: Expand regex to support gitlab.com, bitbucket.org, etc. - Review agent review-1
        if remote_url:
            remote_url = re.sub(r"^git@github\.com:", "https://github.com/", remote_url)
            remote_url = re.sub(r"\.git$", "", remote_url)

        # Ahead/behind with chevrons
        ahead_behind = ""
        counts_raw = git_data.get("ahead_behind", "")
        if counts_raw:
            parts = counts_raw.split()
            behind = parts[0] if len(parts) > 0 else "0"
            ahead  = parts[1] if len(parts) > 1 else "0"

            # Behind (>> red) - zeros grey
            if behind == "0":
                ahead_behind = f"{GREY}\u00bb{behind}{RESET}"
            else:
                ahead_behind = f"{AURORA_RED}\u00bb{behind}{RESET}"

            # Ahead (<< green) - zeros grey
            if ahead == "0":
                ahead_behind += f"{GREY}\u00ab{ahead}{RESET}"
            else:
                ahead_behind += f"{AURORA_GREEN}\u00ab{ahead}{RESET}"

        # Git status counts from single porcelain call
        staged, modified, untracked = parse_porcelain_status(git_data.get("status", ""))

        # Staged color
        if staged == 0:
            staged_fmt = f"{GREY}+{staged}{RESET}"
        else:
            staged_fmt = f"{AURORA_GREEN}+{staged}{RESET}"

        # Modified color
        if modified == 0:
            modified_fmt = f"{GREY}~{modified}{RESET}"
        else:
            modified_fmt = f"{AURORA_YELLOW}~{modified}{RESET}"

        # Untracked color
        if untracked == 0:
            untracked_fmt = f"{GREY}?{untracked}{RESET}"
        else:
            untracked_fmt = f"{AURORA_RED}?{untracked}{RESET}"

        git_status = (
            f"[{staged_fmt}{DARK_GREY}|{RESET}"
            f"{modified_fmt}{DARK_GREY}|{RESET}"
            f"{untracked_fmt}]"
        )

        if branch:
            hash_fmt = f"{GREY}@{commit_hash}{RESET}" if commit_hash else ""

            if remote_url:
                # OSC 8 hyperlink
                # TODO-P2: Validate branch name doesn't contain special chars before URL interpolation (security) - Review agent review-1
                git_section = (
                    f"{SNOW_WHITE}"
                    f"\033]8;;{remote_url}/tree/{branch}\033\\{branch}\033]8;;\033\\"
                    f"{RESET}{hash_fmt}"
                )
            else:
                git_section = f"{SNOW_WHITE}{branch}{RESET}{hash_fmt}"

            if ahead_behind:
                git_section += f" {ahead_behind}"

            git_section += f" {git_status}"

    # ------------------------------------------------------------------
    # Ralph progress section (Elements 1-4)
    # ------------------------------------------------------------------
    ralph_section = ""
    ralph_progress = _read_ralph_progress(cwd)

    # Team agents display (native Agent Teams)
    session_id = inp.get("session_id", "")
    team_data = _read_team_config(session_id) if session_id else None
    team_indicator = ""

    if team_data and team_data.get("member_count", 0) > 0:
        count = team_data["member_count"]
        # TODO-P3: Add cap on team_indicator display (e.g., 99+ for >99 agents) - Review agent review-1
        # Show team member count: 👥4 for 4 agents
        team_indicator = f" {CYAN}👥{count}{RESET}"

    if ralph_progress and ralph_progress.get("total", 0) > 0:
        impl = ralph_progress.get("impl", {})
        review = ralph_progress.get("review", {})

        # TODO-P2: Validate impl/review are dicts before calling .get() - Review agent review-1

        # Build phase display (Element 1)
        parts = []
        if impl.get("total", 0) > 0:
            completed = impl.get("completed", 0) + impl.get("failed", 0)
            # TODO-P3: Add overflow protection for completed > total (clamp to total) - Review agent review-1
            parts.append(f"{BRIGHT_WHITE}{completed}{RESET}{CYAN}/{impl['total']}{RESET}")
        if review.get("total", 0) > 0:
            completed = review.get("completed", 0) + review.get("failed", 0)
            parts.append(f"{BRIGHT_WHITE}{completed}{RESET}{CYAN}/{review['total']}{RESET}")

        agent_block = f"{CYAN}{'·'.join(parts)}{RESET}"

        # Model mix suffix (Element 3)
        mix = ralph_progress.get("model_mix", {})
        opus_count = mix.get("opus", 0)
        sonnet_count = mix.get("sonnet", 0)

        if opus_count > 0 and sonnet_count > 0:  # Mixed models
            model_mix = f"{CYAN}:{opus_count}O{sonnet_count}S{RESET}"
        else:
            model_mix = ""  # All same model - hide

        # Struggle alert (Element 2)
        struggle = ralph_progress.get("struggling", 0)
        struggle_indicator = f"{YELLOW}⚠️{RESET}" if struggle > 0 else ""

        # Build intelligence indicator (read from build-intelligence.json)
        build_intel = read_build_intelligence(cwd)

        # Combine Ralph section (with leading separator only; trailing separator added conditionally)
        ralph_section = f" {DARK_GREY}|{RESET} {agent_block}{model_mix}{struggle_indicator}{build_intel}{team_indicator}"
    elif team_indicator:
        # Show team indicator even without Ralph progress
        ralph_section = f" {DARK_GREY}|{RESET}{team_indicator}"

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    # Separator logic:
    # - Ralph includes leading |, needs trailing | only if git follows
    # - No Ralph: needs | before git
    if ralph_section and git_section:
        git_display = f" {DARK_GREY}|{RESET} {git_section}"
    elif ralph_section:
        git_display = ""  # Ralph visible but no git - no trailing separator
    elif git_section:
        git_display = f" {DARK_GREY}|{RESET} {git_section}"  # No Ralph - add separator before git
    else:
        git_display = ""  # Neither Ralph nor git

    line = (
        f"{SALMON}{model}{RESET}{effort_display} "
        f"{GREY}{style}{RESET} "
        f"{ctx_color}{pct}%{context_suffix}{RESET} "
        f"{DARK_GREY}|{RESET} "
        f"{five_hour_color}{five_hour}%{RESET}"
        f"{DARK_GREY}/{RESET}"
        f"{GREY}{minutes_reset}m{RESET} "
        f"{DARK_GREY}|{RESET} "
        f"{AURORA_GREEN}${cost_fmt}{RESET} "
        f"{DARK_GREY}|{RESET} "
        f"{GREY}s:{RESET}{sonnet_color}{sonnet_weekly}%{RESET}"  # Element 6: s: prefix
        f"{DARK_GREY}/{RESET}"
        f"{GREY}w:{RESET}{weekly_color}{all_weekly}%{RESET}"  # Element 6: w: prefix
        f"{ralph_section}"  # Element 4: Ralph section with leading | (trailing | in git_display)
        f"{git_display}"
    )

    # Cache output for fallback after /clear
    save_last_output(line)

    sys.stdout.buffer.write(line.encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Claude Code Statusline")
    parser.add_argument("--test", action="store_true", help="Run test mode with mock scenarios")
    args = parser.parse_args()

    if args.test:
        run_test_mode()
    else:
        main()
