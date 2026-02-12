#!/usr/bin/env python3
"""
Headless auto-poster for /x skill -- runs Claude Code in -p mode
to scrape GitHub, find X targets, and post replies automatically.

Usage:
  python auto-post.py                   # Scrape + post (Sonnet, 3 posts max)
  python auto-post.py --posts 10        # Scrape + post up to 10 replies
  python auto-post.py --model haiku     # Use Haiku for cheap runs
  python auto-post.py --dry-run         # Scrape only, no posting
  python auto-post.py --budget 2.00     # Cap at $2 per run
  python auto-post.py install [HOURS]   # Install scheduler (default: 12h)
  python auto-post.py uninstall         # Remove scheduler
  python auto-post.py status            # Show scheduler status

Model routing (budget-conscious):
  - Scraper: pure Python (zero LLM cost)
  - Claude -p: Sonnet by default (never Opus for auto mode)
  - Override with --model haiku for minimal cost
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

TASK_NAME = "XSkillAutoPost"

# Model ID mapping
MODELS = {
    "sonnet": "claude-sonnet-4-5-20250929",
    "haiku": "claude-haiku-4-5-20251001",
    "opus": "claude-opus-4-6",  # NOT recommended for auto mode
}


def get_scripts_dir():
    return Path(__file__).parent


def get_data_dir():
    return Path(__file__).parent.parent / "data"


def get_skill_path():
    return Path(__file__).parent.parent / "SKILL.md"


def get_config():
    config_path = get_data_dir() / "config.json"
    if not config_path.exists():
        print("ERROR: No config.json found. Run: python twikit_client.py config --set share_url <url>")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_scraper():
    """Run GitHub scraper (pure Python, no LLM cost)"""
    scraper = get_scripts_dir() / "scraper.py"
    print("[1/2] Running GitHub scraper...")
    result = subprocess.run(
        [sys.executable, str(scraper), "scrape"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Scraper failed: {result.stderr}")
        return False
    print(result.stdout)
    return True


def load_feed():
    """Load feed.json and extract top queries"""
    feed_path = get_data_dir() / "feed.json"
    if not feed_path.exists():
        return None
    with open(feed_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_prompt(config, feed, max_posts=3, dry_run=False):
    """Build the headless Claude prompt with embedded instructions"""
    share_url = config.get("share_url", "")
    project_name = config.get("project_name", "")
    project_desc = config.get("project_desc", "")

    # Extract top queries by priority
    queries = feed.get("queries", [])
    p1 = [q for q in queries if q["priority"] == "P1"]
    p2 = [q for q in queries if q["priority"] == "P2"]
    p3 = [q for q in queries if q["priority"] == "P3"]

    top_queries = (p1 + p2 + p3)[:12]  # Max 12 queries to keep prompt lean
    query_list = "\n".join(
        f"  {i+1}. [{q['priority']}] {q['query']}  -- {q['context']}"
        for i, q in enumerate(top_queries)
    )

    # Recent releases for context
    releases = feed.get("releases", [])
    release_ctx = ""
    if releases:
        release_ctx = "Recent releases (good for finding discussion threads):\n"
        for r in releases[:3]:
            release_ctx += f"  - {r['repo']} {r['tag']}\n"

    action = "DRY RUN -- research only, do NOT post any replies" if dry_run else f"Post up to {max_posts} replies"

    skill_path = get_skill_path()

    prompt = f"""You are running the /x skill in AUTO MODE (headless, non-interactive).

PROJECT: {project_name}
DESCRIPTION: {project_desc}
SHARE URL (include in EVERY reply): {share_url}

Read the full skill instructions: {skill_path}

ACTION: {action}

PRE-COMPUTED SEARCH QUERIES (from GitHub scraper, priority-ordered):
{query_list}

{release_ctx}

INSTRUCTIONS:
1. Read {skill_path} for full tone guidelines and posting rules
2. Read {get_data_dir() / 'config.json'} for your config
3. Check rate limits: python {get_scripts_dir() / 'x.py'} rate-check
4. For each query above (P1 first):
   a. Navigate to X search: https://x.com/search?q={{encoded_query}}&f=top
   b. Use read_page to find reply-worthy posts (engagement > 0)
   c. Check dedup: python {get_scripts_dir() / 'x.py'} check "{{target_url}}"
   d. Compose a UNIQUE reply following tone guidelines (casual, short, reference their pain point)
   e. ALWAYS include {share_url} in the reply
   f. Post via: python {get_scripts_dir() / 'twikit_client.py'} post "{{tweet_id}}" "{{reply_text}}"
   g. If Twikit fails (Cloudflare 403), use Chrome MCP to post manually
   h. Log: python {get_scripts_dir() / 'x.py'} log "{{url}}" "{{author}}" "{{text}}" "auto" "{{query}}" "{{reach}}"
5. Stop after {max_posts} successful posts OR when rate-limited
6. Report: how many posted, total estimated reach, any errors

TONE RULES (critical):
- Write like texting a friend, NOT formal
- Reference their specific pain point from their post
- Keep under 280 chars
- No hashtags, no "Hey!", no exclamation spam
- Every reply must be structurally different

RATE LIMITS:
- Max {max_posts} posts this run
- Max 30/day total (check via x.py rate-check)
- If rate-limited, stop immediately and report
"""
    return prompt


def find_claude_binary():
    """Find the claude CLI binary"""
    # Check common locations
    claude = shutil.which("claude")
    if claude:
        return claude

    # Windows common paths
    for path in [
        Path.home() / ".local" / "bin" / "claude.exe",
        Path.home() / ".local" / "bin" / "claude",
        Path(r"C:\Users\Dennis\.local\bin\claude.exe"),
    ]:
        if path.exists():
            return str(path)

    return None


def cmd_run(args):
    """Run the full auto-post pipeline"""
    config = get_config()
    model_id = MODELS.get(args.model, MODELS["sonnet"])

    if args.model == "opus":
        print("WARNING: Using Opus for auto mode burns weekly quota. Consider --model sonnet")

    # Step 1: Run scraper
    if not run_scraper():
        print("Scraper failed. Aborting.")
        sys.exit(1)

    # Step 2: Load feed
    feed = load_feed()
    if not feed:
        print("No feed data. Aborting.")
        sys.exit(1)

    query_count = feed.get("stats", {}).get("queries_generated", 0)
    print(f"\n[2/2] Launching Claude headless ({args.model}, {args.posts} posts max, {query_count} queries)...")

    if args.dry_run:
        print("  DRY RUN -- no posts will be made")

    # Step 3: Build prompt
    prompt = build_prompt(config, feed, max_posts=args.posts, dry_run=args.dry_run)

    # Step 4: Find claude binary
    claude_bin = find_claude_binary()
    if not claude_bin:
        print("ERROR: claude CLI not found. Install Claude Code first.")
        sys.exit(1)

    # Step 5: Run claude -p
    cmd = [
        claude_bin,
        "-p",
        prompt,
        "--model",
        model_id,
        "--max-turns",
        str(args.max_turns),
    ]

    if args.budget:
        cmd.extend(["--max-budget-usd", str(args.budget)])

    # Allow necessary tools
    cmd.extend([
        "--allowedTools",
        "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,"
        "mcp__claude-in-chrome__tabs_context_mcp,"
        "mcp__claude-in-chrome__tabs_create_mcp,"
        "mcp__claude-in-chrome__navigate,"
        "mcp__claude-in-chrome__read_page,"
        "mcp__claude-in-chrome__find,"
        "mcp__claude-in-chrome__computer,"
        "mcp__claude-in-chrome__get_page_text,"
        "mcp__playwriter__execute",
    ])

    print(f"\n  Running: {claude_bin} -p ... --model {model_id}")
    print(f"  Max turns: {args.max_turns}")
    if args.budget:
        print(f"  Budget cap: ${args.budget}")
    print()

    # Run and stream output
    try:
        result = subprocess.run(cmd, text=True, timeout=600)  # 10 min timeout
        if result.returncode != 0:
            print(f"\nClaude exited with code {result.returncode}")
    except subprocess.TimeoutExpired:
        print("\nTimeout: Claude took longer than 10 minutes. Check /x history for results.")
    except KeyboardInterrupt:
        print("\nAborted by user.")


def cmd_install(hours=12):
    """Install Windows Task Scheduler for auto-posting"""
    script_path = Path(__file__).resolve()
    python_path = sys.executable

    if sys.platform == "win32":
        cmd = [
            "schtasks",
            "/create",
            "/tn",
            TASK_NAME,
            "/tr",
            f'"{python_path}" "{script_path}" --posts 5 --model sonnet --budget 1.00',
            "/sc",
            "HOURLY",
            "/mo",
            str(hours),
            "/f",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"Auto-poster installed: runs every {hours}h")
                print(f"  Task: {TASK_NAME}")
                print(f"  Model: Sonnet (budget-safe)")
                print(f"  Posts: 5 per run")
                print(f"  Budget: $1.00 per run")
                print(f"\nManage:")
                print(f"  python auto-post.py status")
                print(f"  python auto-post.py uninstall")
            else:
                print(f"Failed: {result.stderr.strip()}")
        except FileNotFoundError:
            print("schtasks not found.")
    else:
        cron = f"0 */{hours} * * * {python_path} {script_path} --posts 5 --model sonnet --budget 1.00 >> /tmp/x-autopost.log 2>&1"
        print(f"Add to crontab (crontab -e):\n  {cron}")


def cmd_uninstall():
    """Remove auto-poster scheduler"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"Auto-poster removed: {TASK_NAME}")
            else:
                print(f"Not found: {result.stderr.strip()}")
        except FileNotFoundError:
            print("schtasks not found.")


def cmd_status():
    """Show auto-poster status"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "TABLE"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print("Auto-poster: INSTALLED")
                for line in result.stdout.strip().split("\n"):
                    print(f"  {line}")
            else:
                print("Auto-poster: NOT INSTALLED")
        except FileNotFoundError:
            print("Auto-poster: schtasks not available")

    # Feed freshness
    feed = load_feed()
    if feed:
        print(f"\nFeed: {feed.get('stats', {}).get('queries_generated', 0)} queries")
        print(f"  Updated: {feed.get('last_updated', 'unknown')}")

    # Posting status
    x_py = get_scripts_dir() / "x.py"
    result = subprocess.run(
        [sys.executable, str(x_py), "status"],
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(f"\n{result.stdout.strip()}")


def main():
    parser = argparse.ArgumentParser(
        description="Headless auto-poster for /x skill"
    )
    parser.add_argument(
        "--posts",
        type=int,
        default=3,
        help="Max posts per run (default: 3)",
    )
    parser.add_argument(
        "--model",
        choices=["sonnet", "haiku", "opus"],
        default="sonnet",
        help="Model to use (default: sonnet, NEVER use opus for auto)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=1.00,
        help="Max USD per run (default: 1.00)",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=30,
        help="Max Claude turns (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Research only, no posting",
    )

    # Subcommands for scheduler
    subparsers = parser.add_subparsers(dest="command")
    install_p = subparsers.add_parser("install", help="Install auto-poster scheduler")
    install_p.add_argument(
        "hours", nargs="?", type=int, default=12, help="Interval in hours"
    )
    subparsers.add_parser("uninstall", help="Remove scheduler")
    subparsers.add_parser("status", help="Show status")

    args = parser.parse_args()

    if args.command == "install":
        cmd_install(args.hours)
    elif args.command == "uninstall":
        cmd_uninstall()
    elif args.command == "status":
        cmd_status()
    else:
        cmd_run(args)


if __name__ == "__main__":
    main()
