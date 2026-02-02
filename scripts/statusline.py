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
_kill_timer = threading.Timer(5, lambda: os._exit(0))
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

CACHE_DIR = Path.home() / ".claude"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    except (subprocess.TimeoutExpired, FileNotFoundError):
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
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
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
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            pass
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

        if not token or token == "null":
            return

        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/api/oauth/usage",
                headers={
                    "Authorization": f"Bearer {token}",
                    "anthropic-beta": "oauth-2025-04-20",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8")
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(body, encoding="utf-8")
        except Exception:
            pass

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
    if cache_path.exists():
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
    except OSError:
        pass


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
    ctx_val = inp.get("context_window", {})
    pct     = int(float(ctx_val.get("used_percentage", 0) if isinstance(ctx_val, dict) else 0))
    style_val = inp.get("output_style", {})
    style_raw = (style_val.get("name", "default") if isinstance(style_val, dict) else str(style_val)) or "default"
    style   = style_raw[0].upper() + style_raw[1:]  # capitalize first letter

    # Context % color
    ctx_color = color_threshold(str(pct), 50, 80)

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
    # Daily cost (CET timezone, valid 24h across sessions)
    # ------------------------------------------------------------------
    try:
        cost_date = datetime.now(ZoneInfo("Europe/Berlin")).strftime("%Y-%m-%d")
    except Exception:
        cost_date = datetime.now().strftime("%Y-%m-%d")
    cost_dir = CACHE_DIR / "daily-cost"
    cost_dir.mkdir(parents=True, exist_ok=True)

    session_id   = inp.get("session_id", "")
    session_cost = inp.get("cost", {}).get("total_cost_usd", 0)

    if session_id and session_cost and session_cost != "null":
        try:
            cost_file = cost_dir / f"{cost_date}-{session_id}.cost"
            cost_file.write_text(str(session_cost), encoding="utf-8")
        except OSError:
            pass

    # Sum all session costs for today
    daily_cost = 0.0
    for p in cost_dir.glob(f"{cost_date}-*.cost"):
        try:
            daily_cost += float(p.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pass
    cost_fmt = f"{daily_cost:.2f}"

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
    # Output
    # ------------------------------------------------------------------
    line = (
        f"{SALMON}{model}{RESET} "
        f"{GREY}{style}{RESET} "
        f"{ctx_color}{pct}%{RESET} "
        f"{DARK_GREY}|{RESET} "
        f"{five_hour_color}{five_hour}%{RESET}"
        f"{DARK_GREY}/{RESET}"
        f"{GREY}{minutes_reset}m{RESET} "
        f"{DARK_GREY}|{RESET} "
        f"{AURORA_GREEN}${cost_fmt}{RESET} "
        f"{DARK_GREY}|{RESET} "
        f"{sonnet_color}{sonnet_weekly}%{RESET}"
        f"{DARK_GREY}/{RESET}"
        f"{weekly_color}{all_weekly}%{RESET} "
        f"{DARK_GREY}|{RESET} "
        f"{git_section}"
    )

    # Cache output for fallback after /clear
    save_last_output(line)

    sys.stdout.buffer.write(line.encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
