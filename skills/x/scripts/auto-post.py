#!/usr/bin/env python3
"""
Headless auto-poster for /x skill -- runs Claude Code in -p mode
to scrape, compose original posts, and reply to targets automatically.

Usage:
  python auto-post.py                        # Scrape + reply (Sonnet, 3 posts max)
  python auto-post.py --posts 10             # Scrape + reply up to 10
  python auto-post.py --mode compose         # Compose original tweet from news + distribute
  python auto-post.py --mode reply           # Reply-only mode (default)
  python auto-post.py --model haiku          # Use Haiku for cheap runs
  python auto-post.py --dry-run              # Scrape only, no posting
  python auto-post.py --budget 2.00          # Cap at $2 per run
  python auto-post.py install [HOURS]        # Install scheduler (default: 12h)
  python auto-post.py uninstall              # Remove scheduler
  python auto-post.py status                 # Show scheduler status

Modes:
  reply   -- Find targets via search queries, compose unique replies (default)
  compose -- Pick news item, compose original tweet on profile, then distribute
             by replying to related conversations with the original tweet URL

Model routing (budget-conscious):
  - Scraper: pure Python (zero LLM cost)
  - Claude -p: Sonnet by default (never Opus for auto mode)
  - Override with --model haiku for minimal cost
"""

import argparse
import json
import os
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


def load_env_var(name):
    """Read env var from system or from skills/x/.env file"""
    val = os.environ.get(name)
    if val:
        return val
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    return None


def load_config():
    """Load config.json, auto-generating from .env if missing"""
    config_path = get_data_dir() / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Auto-generate from .env vars
    config = {
        "share_url": load_env_var("X_SHARE_URL") or "",
        "handle": load_env_var("X_HANDLE") or "",
        "project_name": load_env_var("X_PROJECT_NAME") or "",
        "project_desc": load_env_var("X_PROJECT_DESC") or "",
    }
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    if not config["share_url"]:
        print("WARNING: share_url is empty. Set X_SHARE_URL in .env or skills/x/data/config.json")
    return config


def run_scraper():
    """Run multi-source scraper (pure Python, no LLM cost)"""
    scraper = get_scripts_dir() / "scraper.py"
    print("[1/2] Running scraper (GitHub + RSS + news)...")
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
    """Load feed.json"""
    feed_path = get_data_dir() / "feed.json"
    if not feed_path.exists():
        return None
    with open(feed_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_reply_prompt(config, feed, max_posts=3, dry_run=False):
    """Build prompt for reply mode -- find targets and post replies"""
    share_url = config.get("share_url", "")
    project_name = config.get("project_name", "")
    project_desc = config.get("project_desc", "")

    # Extract top queries by priority
    queries = feed.get("queries", [])
    p1 = [q for q in queries if q["priority"] == "P1"]
    p2 = [q for q in queries if q["priority"] == "P2"]
    p3 = [q for q in queries if q["priority"] == "P3"]

    top_queries = (p1 + p2 + p3)[:12]
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

    # News items for additional query generation
    news = feed.get("news", [])
    news_ctx = ""
    if news:
        news_ctx = "Recent news items (use for finding related conversations):\n"
        for n in news[:5]:
            news_ctx += f"  - [{n.get('category', 'general')}] {n['title']}\n"

    action = "DRY RUN -- research only, do NOT post any replies" if dry_run else f"Post up to {max_posts} replies"

    skill_path = get_skill_path()

    prompt = f"""You are running the /x skill in AUTO MODE (headless, non-interactive).

PROJECT: {project_name}
DESCRIPTION: {project_desc}
SHARE URL (include in EVERY reply): {share_url}

Read the full skill instructions: {skill_path}

ACTION: {action}

MODE: REPLY -- find targets and post unique replies

PRE-COMPUTED SEARCH QUERIES (priority-ordered):
{query_list}

{release_ctx}
{news_ctx}

INSTRUCTIONS:
1. Read {skill_path} for full tone guidelines and posting rules
2. Check rate limits: python {get_scripts_dir() / 'x.py'} rate-check
3. For each query above (P1 first):
   a. Navigate to X search: https://x.com/search?q={{encoded_query}}&f=top
   b. Use read_page to find reply-worthy posts (engagement > 0)
   c. Check dedup: python {get_scripts_dir() / 'x.py'} check "{{target_url}}"
   d. Compose a UNIQUE reply following tone guidelines (casual, short, reference their pain point)
   e. ALWAYS include {share_url} in the reply
   f. Post via: python {get_scripts_dir() / 'x_client.py'} post "{{tweet_id}}" "{{reply_text}}"
   g. If X API client fails (Cloudflare 403), use Chrome MCP to post manually
   h. Log: python {get_scripts_dir() / 'x.py'} log "{{url}}" "{{author}}" "{{text}}" "auto" "{{query}}" "{{reach}}"
4. Stop after {max_posts} successful posts OR when rate-limited
5. Report: how many posted, total estimated reach, any errors

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


def build_compose_prompt(config, feed, max_posts=3, dry_run=False):
    """Build prompt for compose mode -- create original tweet from news + distribute"""
    share_url = config.get("share_url", "")
    handle = config.get("handle", "")
    project_name = config.get("project_name", "")
    project_desc = config.get("project_desc", "")

    # News items -- the source material for original tweets
    news = feed.get("news", [])
    news_list = ""
    if news:
        for i, n in enumerate(news[:10]):
            cat = n.get("category", "general")
            src = n.get("source", "unknown")
            news_list += f"  {i+1}. [{cat}] {n['title']}  (via {src})\n"
            if n.get("summary"):
                news_list += f"     Summary: {n['summary'][:120]}...\n"
    else:
        news_list = "  (No news items available -- generate from your own knowledge)\n"

    # Browse hints -- URLs for Claude to check via Chrome MCP
    browse_hints = feed.get("browse_hints", [])
    hints_list = ""
    if browse_hints:
        hints_list = "BROWSE HINTS (check these URLs for fresh content via Chrome MCP):\n"
        for h in browse_hints[:5]:
            hints_list += f"  - {h['url']}  ({h.get('source', 'unknown')})\n"

    # Search queries for distribution phase
    queries = feed.get("queries", [])
    p1 = [q for q in queries if q["priority"] == "P1"]
    p2 = [q for q in queries if q["priority"] == "P2"]
    top_queries = (p1 + p2)[:8]
    query_list = "\n".join(
        f"  {i+1}. [{q['priority']}] {q['query']}  -- {q['context']}"
        for i, q in enumerate(top_queries)
    )

    action = "DRY RUN -- draft only, do NOT post anything" if dry_run else f"Compose 1 original tweet + distribute up to {max_posts} replies"

    skill_path = get_skill_path()

    prompt = f"""You are running the /x skill in AUTO MODE (headless, non-interactive).

PROJECT: {project_name}
DESCRIPTION: {project_desc}
HANDLE: {handle}
SHARE URL: {share_url}

Read the full skill instructions: {skill_path}

ACTION: {action}

MODE: COMPOSE + DISTRIBUTE

This is a TWO-PHASE operation:

===== PHASE 1: COMPOSE ORIGINAL TWEET =====

Pick the most interesting/relevant news item below and compose an original tweet
for the {handle} profile. The tweet should be informative, opinionated, and
drive engagement. Include your own take -- don't just repeat the headline.

NEWS ITEMS (pick 1 to tweet about):
{news_list}
{hints_list}

COMPOSE RULES:
- Pick the item most relevant to {project_name}'s audience
- Write 1-3 short sentences, casual tone, under 280 chars
- Add your own opinion or insight (not just headline rewrite)
- Include a relevant link if the news item has one
- You can mention {share_url} if the news relates to {project_desc}
- Post to YOUR profile (not as a reply) via:
  python {get_scripts_dir() / 'x_client.py'} tweet "{{tweet_text}}"
  OR via Chrome MCP: navigate to x.com, click compose, type, post
- Save the URL of your new tweet for Phase 2

===== PHASE 2: DISTRIBUTE (reply with your tweet URL) =====

After composing the original tweet, find related conversations on X
and reply with a link to your new tweet + brief context.

SEARCH QUERIES (for finding related conversations):
{query_list}

DISTRIBUTE INSTRUCTIONS:
1. Get the URL of the tweet you just posted
2. For each query above (P1 first):
   a. Navigate to X search: https://x.com/search?q={{encoded_query}}&f=top
   b. Find posts discussing the same topic as your tweet
   c. Check dedup: python {get_scripts_dir() / 'x.py'} check "{{target_url}}"
   d. Compose a short reply referencing their discussion + link to your tweet
   e. Post via X API client or Chrome MCP
   f. Log: python {get_scripts_dir() / 'x.py'} log "{{url}}" "{{author}}" "{{text}}" "compose-distribute" "{{query}}" "{{reach}}"
3. Stop after {max_posts} successful distribution replies

TONE RULES (same as reply mode):
- Write like texting a friend, NOT formal
- Reference their specific topic from their post
- Keep under 280 chars
- No hashtags, no "Hey!", no exclamation spam
- Every reply must be structurally different

RATE LIMITS:
- Max {max_posts} distribution replies this run
- Max 30/day total (check via x.py rate-check)
- If rate-limited, stop immediately and report
"""
    return prompt


def find_claude_binary():
    """Find the claude CLI binary"""
    claude = shutil.which("claude")
    if claude:
        return claude

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
    config = load_config()
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
    news_count = len(feed.get("news", []))
    mode_label = args.mode.upper()
    print(f"\n[2/2] Launching Claude headless ({args.model}, {mode_label}, {args.posts} posts max, {query_count} queries, {news_count} news items)...")

    if args.dry_run:
        print("  DRY RUN -- no posts will be made")

    # Step 3: Build prompt based on mode
    if args.mode == "compose":
        prompt = build_compose_prompt(config, feed, max_posts=args.posts, dry_run=args.dry_run)
    else:
        prompt = build_reply_prompt(config, feed, max_posts=args.posts, dry_run=args.dry_run)

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
    print(f"  Mode: {mode_label}")
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
                print(f"  Mode: reply (default)")
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
        stats = feed.get("stats", {})
        print(f"\nFeed: {stats.get('queries_generated', 0)} queries, {stats.get('news_items', 0)} news items")
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
        "--mode",
        choices=["reply", "compose"],
        default="reply",
        help="Mode: reply (find+reply targets) or compose (original tweet + distribute)",
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
