#!/usr/bin/env python3
"""
GitHub trending scraper for /x skill -- auto-generates X search queries
from GitHub ecosystem signals. Zero external dependencies (stdlib only).

Usage:
  python scraper.py scrape              # Scrape GitHub API → generate feed.json
  python scraper.py feed                # Show current feed
  python scraper.py install [HOURS]     # Install Windows Task Scheduler (default: 6h)
  python scraper.py uninstall           # Remove scheduler
  python scraper.py status              # Show scheduler + feed status
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

GITHUB_API = "https://api.github.com"
TASK_NAME = "XSkillScraper"
USER_AGENT = "x-skill-scraper/1.0"


def get_data_dir():
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_feed_path():
    return get_data_dir() / "feed.json"


def github_api(endpoint, params=None):
    """Call GitHub REST API (no auth needed, 60 req/hr limit)"""
    url = f"{GITHUB_API}{endpoint}"
    if params:
        query = urllib.parse.urlencode(params)
        url += f"?{query}"

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": USER_AGENT,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print("  WARN: GitHub API rate limited (60 req/hr). Wait and retry.")
            return None
        if e.code == 422:
            print(f"  WARN: GitHub API rejected query: {e.read().decode()[:200]}")
            return None
        print(f"  WARN: GitHub API HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  WARN: GitHub API error: {e}")
        return None


# ─── Scrapers ────────────────────────────────────────────────────────────────


def scrape_trending_repos():
    """Find trending AI/ML repos via GitHub search API"""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    searches = [
        # New AI repos this week with traction
        {
            "q": f"topic:ai created:>{week_ago} stars:>5",
            "sort": "stars",
            "order": "desc",
            "per_page": 15,
        },
        # Free/open LLM tools recently pushed
        {
            "q": f"(free OR self-hosted OR local) topic:llm pushed:>{week_ago} stars:>50",
            "sort": "updated",
            "per_page": 10,
        },
        # Inference frameworks actively maintained
        {
            "q": f"(ollama OR vllm OR localai OR litellm OR jan) in:name stars:>100 pushed:>{month_ago}",
            "sort": "stars",
            "per_page": 10,
        },
        # Budget/cost-aware AI tools
        {
            "q": "topic:ai (free-tier OR budget OR cost OR cheap) stars:>10",
            "sort": "stars",
            "order": "desc",
            "per_page": 10,
        },
        # New CLI tools for AI
        {
            "q": f"(cli OR terminal) (ai OR llm OR gpt) created:>{month_ago} stars:>20",
            "sort": "stars",
            "per_page": 10,
        },
    ]

    repos = []
    seen = set()

    for params in searches:
        data = github_api("/search/repositories", params)
        if not data or "items" not in data:
            continue

        for item in data["items"]:
            name = item["full_name"]
            if name in seen:
                continue
            seen.add(name)

            repos.append(
                {
                    "name": name,
                    "description": (item.get("description") or "")[:200],
                    "stars": item.get("stargazers_count", 0),
                    "language": item.get("language", ""),
                    "topics": item.get("topics", []),
                    "created": item.get("created_at", ""),
                    "updated": item.get("updated_at", ""),
                    "url": item.get("html_url", ""),
                    "owner": item.get("owner", {}).get("login", ""),
                }
            )

    # Sort by stars descending
    repos.sort(key=lambda r: r["stars"], reverse=True)
    return repos


def scrape_cost_issues():
    """Find GitHub issues about API costs, rate limits, billing"""
    searches = [
        {
            "q": '"rate limit" OR "quota exceeded" label:bug is:open language:python',
            "sort": "created",
            "order": "desc",
            "per_page": 10,
        },
        {
            "q": '"too expensive" OR "free alternative" OR "billing" is:issue is:open',
            "sort": "reactions",
            "order": "desc",
            "per_page": 10,
        },
        {
            "q": '"can\'t afford" OR "student discount" (api OR ai OR llm) is:issue',
            "sort": "created",
            "order": "desc",
            "per_page": 10,
        },
    ]

    issues = []
    seen = set()

    for params in searches:
        data = github_api("/search/issues", params)
        if not data or "items" not in data:
            continue

        for item in data["items"]:
            url = item.get("html_url", "")
            if url in seen:
                continue
            seen.add(url)

            # Extract repo from URL: github.com/owner/repo/issues/N
            parts = url.split("/")
            repo = "/".join(parts[3:5]) if len(parts) >= 5 else ""

            issues.append(
                {
                    "title": item.get("title", "")[:200],
                    "repo": repo,
                    "author": item.get("user", {}).get("login", ""),
                    "url": url,
                    "reactions": item.get("reactions", {}).get("total_count", 0),
                    "created": item.get("created_at", ""),
                }
            )

    return issues


def scrape_new_releases():
    """Find recent releases of popular free AI tools"""
    # Check releases for key repos
    key_repos = [
        "ollama/ollama",
        "vllm-project/vllm",
        "mudler/LocalAI",
        "BerriAI/litellm",
        "janhq/jan",
        "ggml-org/llama.cpp",
        "oobabooga/text-generation-webui",
        "lm-sys/FastChat",
    ]

    releases = []
    for repo in key_repos:
        data = github_api(f"/repos/{repo}/releases", {"per_page": 1})
        if not data or not isinstance(data, list) or len(data) == 0:
            continue

        rel = data[0]
        published = rel.get("published_at", "")

        # Only include releases from last 7 days
        if published:
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if pub_dt < datetime.now(timezone.utc) - timedelta(days=7):
                    continue
            except (ValueError, TypeError):
                continue

        releases.append(
            {
                "repo": repo,
                "tag": rel.get("tag_name", ""),
                "name": rel.get("name", "")[:100],
                "published": published,
                "url": rel.get("html_url", ""),
            }
        )

    return releases


# ─── Query Generator ─────────────────────────────────────────────────────────


def generate_x_queries(repos, issues, releases):
    """Generate X search queries from scraped GitHub data"""
    queries = []

    # ── Standard high-value queries (always included) ──
    standard = [
        {
            "query": "\"can't afford\" (API OR AI OR LLM) min_faves:5 within_time:3d",
            "priority": "P1",
            "source": "standard",
            "context": "Direct cost complaints",
        },
        {
            "query": "\"rate limit\" (hit OR exceeded OR stuck) (openai OR anthropic OR gemini) within_time:3d",
            "priority": "P1",
            "source": "standard",
            "context": "Rate limit frustration",
        },
        {
            "query": "\"API bill\" (shocked OR surprised OR expensive OR crazy) min_faves:3 within_time:7d",
            "priority": "P1",
            "source": "standard",
            "context": "Billing shock",
        },
        {
            "query": "\"free tier\" (AI OR LLM OR API) (not enough OR limited OR upgrade) within_time:3d",
            "priority": "P2",
            "source": "standard",
            "context": "Free tier limitations",
        },
        {
            "query": "(student OR \"broke dev\" OR \"no budget\") (AI OR API) (expensive OR cost OR afford) within_time:7d",
            "priority": "P2",
            "source": "standard",
            "context": "Budget-constrained users",
        },
        {
            "query": "\"switching from\" (openai OR anthropic) (free OR local OR self-host) within_time:7d",
            "priority": "P3",
            "source": "standard",
            "context": "Migration signals",
        },
        {
            "query": "\"just launched\" (AI OR LLM) (free OR \"open source\") within_time:7d min_faves:5",
            "priority": "P4",
            "source": "standard",
            "context": "New free tool launches - cross-promote",
        },
        {
            "query": "hackathon (AI OR LLM) (built OR won OR demo) within_time:7d",
            "priority": "P5",
            "source": "standard",
            "context": "Hackathon projects needing free APIs",
        },
    ]
    queries.extend(standard)

    # ── From trending repos ──
    for repo in repos[:15]:
        name = repo["name"].split("/")[-1]
        topics = repo.get("topics", [])

        # People tweeting about cost-conscious tools
        if any(
            t in topics for t in ["free", "self-hosted", "local", "budget", "inference"]
        ):
            queries.append(
                {
                    "query": f'"{name}" (free OR cost OR rate-limit) within_time:7d',
                    "priority": "P3",
                    "source": "github_trending",
                    "context": f"Users of {repo['name']} ({repo['stars']} stars)",
                }
            )

        # Discussions about popular repos
        if repo["stars"] > 500:
            queries.append(
                {
                    "query": f'"{name}" (trying OR "just installed" OR setup) within_time:3d min_faves:3',
                    "priority": "P4",
                    "source": "github_trending",
                    "context": f"New users of {repo['name']}",
                }
            )

    # ── From cost issues → find authors on X ──
    for issue in issues[:10]:
        author = issue.get("author", "")
        if author and len(author) > 2:
            queries.append(
                {
                    "query": f"from:{author} (AI OR API OR LLM OR cost OR rate) within_time:30d",
                    "priority": "P2",
                    "source": "github_issues",
                    "context": f"GitHub user {author} posted about costs in {issue['repo']}",
                }
            )

    # ── From new releases → find announcement threads ──
    for rel in releases:
        repo_name = rel["repo"].split("/")[-1]
        queries.append(
            {
                "query": f'"{repo_name}" (release OR update OR "{rel["tag"]}") within_time:3d min_faves:5',
                "priority": "P4",
                "source": "github_releases",
                "context": f"Release thread for {rel['repo']} {rel['tag']}",
            }
        )

    return queries


# ─── Commands ────────────────────────────────────────────────────────────────


def cmd_scrape():
    """Run full scrape cycle"""
    print("=== GitHub Scraper for /x Skill ===\n")

    print("[1/4] Scraping trending AI repos...")
    repos = scrape_trending_repos()
    print(f"  Found {len(repos)} repos")

    print("[2/4] Scraping cost-related issues...")
    issues = scrape_cost_issues()
    print(f"  Found {len(issues)} issues")

    print("[3/4] Checking recent releases...")
    releases = scrape_new_releases()
    print(f"  Found {len(releases)} releases")

    print("[4/4] Generating X search queries...")
    x_queries = generate_x_queries(repos, issues, releases)
    print(f"  Generated {len(x_queries)} queries")

    feed = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "repos": repos,
        "issues": issues,
        "releases": releases,
        "queries": x_queries,
        "stats": {
            "repos_found": len(repos),
            "issues_found": len(issues),
            "releases_found": len(releases),
            "queries_generated": len(x_queries),
        },
    }

    feed_path = get_feed_path()
    with open(feed_path, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2)

    print(f"\nFeed saved: {feed_path}")

    # Summary by priority
    for p in ["P1", "P2", "P3", "P4", "P5"]:
        pq = [q for q in x_queries if q["priority"] == p]
        if pq:
            print(f"\n  {p} ({len(pq)} queries):")
            for q in pq[:2]:
                print(f"    {q['query'][:80]}")

    print(f"\nReady for: /x post OR /x research")


def cmd_feed():
    """Show current feed summary"""
    feed_path = get_feed_path()
    if not feed_path.exists():
        print("No feed found. Run: python scraper.py scrape")
        sys.exit(1)

    with open(feed_path, "r", encoding="utf-8") as f:
        feed = json.load(f)

    updated = feed.get("last_updated", "unknown")
    stats = feed.get("stats", {})
    queries = feed.get("queries", [])
    repos = feed.get("repos", [])
    releases = feed.get("releases", [])

    # Check freshness
    try:
        updated_dt = datetime.fromisoformat(updated)
        age_hours = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600
        freshness = f"{age_hours:.1f}h ago"
        if age_hours > 12:
            freshness += " (STALE - run scrape)"
    except (ValueError, TypeError):
        freshness = "unknown"

    print(f"Feed updated: {updated} ({freshness})")
    print(f"Repos: {stats.get('repos_found', 0)}")
    print(f"Issues: {stats.get('issues_found', 0)}")
    print(f"Releases: {stats.get('releases_found', 0)}")
    print(f"Queries: {stats.get('queries_generated', 0)}")

    # Top repos
    if repos:
        print(f"\nTop repos:")
        for r in repos[:5]:
            print(f"  {r['name']:40s} {r['stars']:>6d} stars  {r['language'] or '?'}")

    # Recent releases
    if releases:
        print(f"\nRecent releases:")
        for r in releases:
            print(f"  {r['repo']:40s} {r['tag']}")

    # Queries by priority
    print(f"\nQueries by priority:")
    for p in ["P1", "P2", "P3", "P4", "P5"]:
        pq = [q for q in queries if q["priority"] == p]
        if pq:
            print(f"  {p}: {len(pq)} queries")
            for q in pq[:2]:
                print(f"    {q['query'][:75]}")

    # Output as JSON for piping
    if not sys.stdout.isatty():
        print(json.dumps(feed, indent=2))


def cmd_install(hours=6):
    """Install Windows Task Scheduler job (or show cron for Linux)"""
    script_path = Path(__file__).resolve()
    python_path = sys.executable

    if sys.platform == "win32":
        cmd = [
            "schtasks",
            "/create",
            "/tn",
            TASK_NAME,
            "/tr",
            f'"{python_path}" "{script_path}" scrape',
            "/sc",
            "HOURLY",
            "/mo",
            str(hours),
            "/f",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"Scheduler installed: runs every {hours}h")
                print(f"Task name: {TASK_NAME}")
                print(f"\nManage:")
                print(f"  python scraper.py status")
                print(f"  python scraper.py uninstall")
            else:
                print(f"Failed: {result.stderr.strip()}")
                print(f"\nTry running as administrator.")
        except FileNotFoundError:
            print("schtasks not found.")
    else:
        # Linux/Mac: show crontab command
        cron = f"0 */{hours} * * * {python_path} {script_path} scrape >> /tmp/x-scraper.log 2>&1"
        print(f"Add to crontab (crontab -e):\n  {cron}")


def cmd_uninstall():
    """Remove scheduler"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"Scheduler removed: {TASK_NAME}")
            else:
                print(f"Not found or error: {result.stderr.strip()}")
        except FileNotFoundError:
            print("schtasks not found.")
    else:
        print(f"Remove from crontab: crontab -e, delete the {TASK_NAME} line")


def cmd_status():
    """Show scheduler + feed status"""
    # Scheduler status
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "TABLE"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print("Scheduler: INSTALLED")
                for line in result.stdout.strip().split("\n"):
                    print(f"  {line}")
            else:
                print("Scheduler: NOT INSTALLED")
                print("  Install: python scraper.py install")
        except FileNotFoundError:
            print("Scheduler: schtasks not available")
    else:
        print("Scheduler: check crontab -l")

    # Feed freshness
    feed_path = get_feed_path()
    if feed_path.exists():
        with open(feed_path, "r", encoding="utf-8") as f:
            feed = json.load(f)
        updated = feed.get("last_updated", "unknown")
        stats = feed.get("stats", {})
        try:
            updated_dt = datetime.fromisoformat(updated)
            age_hours = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600
            status = "FRESH" if age_hours < 12 else "STALE"
            print(f"\nFeed: {status} ({age_hours:.1f}h old)")
        except (ValueError, TypeError):
            print(f"\nFeed: exists (age unknown)")
        print(f"  Queries: {stats.get('queries_generated', 0)}")
        print(f"  Repos: {stats.get('repos_found', 0)}")
    else:
        print(f"\nFeed: MISSING")
        print(f"  Run: python scraper.py scrape")


def main():
    parser = argparse.ArgumentParser(
        description="GitHub scraper for /x skill - auto-generates X search queries"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("scrape", help="Scrape GitHub, generate X queries")
    subparsers.add_parser("feed", help="Show current feed")

    install_p = subparsers.add_parser("install", help="Install scheduler")
    install_p.add_argument(
        "hours", nargs="?", type=int, default=6, help="Interval in hours (default: 6)"
    )

    subparsers.add_parser("uninstall", help="Remove scheduler")
    subparsers.add_parser("status", help="Show scheduler + feed status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "scrape":
        cmd_scrape()
    elif args.command == "feed":
        cmd_feed()
    elif args.command == "install":
        cmd_install(args.hours)
    elif args.command == "uninstall":
        cmd_uninstall()
    elif args.command == "status":
        cmd_status()


if __name__ == "__main__":
    main()
