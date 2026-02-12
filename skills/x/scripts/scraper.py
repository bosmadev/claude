#!/usr/bin/env python3
"""
Scraper for /x skill -- aggregates GitHub, news feeds, and crypto data
into feed.json for X/Twitter outreach. Zero external dependencies (stdlib only).

Sources:
  - GitHub API (via gh CLI for 5000 req/hr, urllib fallback 60/hr)
  - Google News RSS (AI, coding, crypto)
  - Google Cloud release feeds (Gemini, Vertex AI)
  - Messari API (crypto news, needs MESSARI_API_KEY)
  - Markdown changelogs (Claude Code, etc.)

Usage:
  python scraper.py scrape              # Full scrape -> feed.json
  python scraper.py feed                # Show current feed
  python scraper.py install [HOURS]     # Install Windows Task Scheduler (default: 6h)
  python scraper.py uninstall           # Remove scheduler
  python scraper.py status              # Show scheduler + feed status
"""

import argparse
import html as html_mod
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

GITHUB_API = "https://api.github.com"
TASK_NAME = "XSkillScraper"
USER_AGENT = "x-skill-scraper/1.0"


# -- News Source Configuration ------------------------------------------------

NEWS_RSS_FEEDS = [
    # AI & Coding (Google News RSS)
    {
        "url": "https://news.google.com/rss/search?q=AI+artificial+intelligence+LLM&hl=en-US&gl=US&ceid=US:en",
        "source": "google_news_ai",
        "category": "ai",
        "max_items": 10,
    },
    {
        "url": "https://news.google.com/rss/search?q=vscode+%22visual+studio+code%22&hl=en-US&gl=US&ceid=US:en",
        "source": "google_news_vscode",
        "category": "coding",
        "max_items": 5,
    },
    {
        "url": "https://news.google.com/rss/search?q=react+nextjs+frontend&hl=en-US&gl=US&ceid=US:en",
        "source": "google_news_react",
        "category": "coding",
        "max_items": 5,
    },
    {
        "url": "https://news.google.com/rss/search?q=%22azure+AI%22+foundry&hl=en-US&gl=US&ceid=US:en",
        "source": "google_news_azure",
        "category": "ai",
        "max_items": 5,
    },
    # Google Cloud product feeds (Atom XML)
    {
        "url": "https://cloud.google.com/feeds/gemini-code-assist-release-notes.xml",
        "source": "gemini_code_assist",
        "category": "ai",
        "max_items": 5,
    },
    {
        "url": "https://cloud.google.com/feeds/vertex-ai-release-notes.xml",
        "source": "vertex_ai",
        "category": "ai",
        "max_items": 5,
    },
    # Crypto
    {
        "url": "https://news.google.com/rss/search?q=cryptocurrency+bitcoin+ethereum&hl=en-US&gl=US&ceid=US:en",
        "source": "google_news_crypto",
        "category": "crypto",
        "max_items": 10,
    },
    {
        "url": "https://cryptonews.com/news/feed/",
        "source": "cryptonews",
        "category": "crypto",
        "max_items": 10,
    },
    # Dev blogs (RSS where available)
    {
        "url": "https://nextjs.org/feed.xml",
        "source": "nextjs_blog",
        "category": "coding",
        "max_items": 5,
    },
    {
        "url": "https://code.visualstudio.com/feed.xml",
        "source": "vscode_updates",
        "category": "coding",
        "max_items": 5,
    },
]

# URLs too dynamic for regex scraping -- Claude checks via Chrome MCP
BROWSE_HINTS = [
    {"url": "https://ai.google.dev/changelog", "source": "gemini_api", "category": "ai"},
    {"url": "https://jules.google.com/changelog", "source": "jules", "category": "ai"},
    {"url": "https://newsbit.nl", "source": "newsbit", "category": "ai"},
    {"url": "https://blog.kilo.ai", "source": "kilo_ai", "category": "ai"},
    {"url": "https://artificialanalysis.ai", "source": "artificial_analysis", "category": "ai"},
    {"url": "https://finance.yahoo.com", "source": "yahoo_finance", "category": "crypto"},
]

CHANGELOGS = [
    {
        "url": "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md",
        "source": "claude_code",
        "category": "coding",
        "max_entries": 3,
    },
]


# -- Utilities ----------------------------------------------------------------


def get_data_dir():
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_feed_path():
    return get_data_dir() / "feed.json"


def load_env_var(name):
    """Load env var from system env or skills/x/.env file"""
    val = os.environ.get(name)
    if val:
        return val
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith(f"{name}="):
                    return line.split("=", 1)[1].strip()
    return None


def load_config():
    """Load config from config.json, auto-generate from .env if missing"""
    config_path = get_data_dir() / "config.json"

    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # Auto-generate from .env or defaults
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
        print("NOTE: No share_url configured. Set X_SHARE_URL in .env or pass URL in /x post.")

    return config


def fetch_url(url, headers=None, timeout=15):
    """Fetch URL content as text, return None on failure"""
    hdrs = {"User-Agent": USER_AGENT}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  WARN: Failed to fetch {url[:80]}: {e}")
        return None


def github_api(endpoint, params=None):
    """Call GitHub API -- tries gh CLI (5000/hr) then urllib (60/hr)"""
    # Try authenticated gh CLI first
    gh_url = endpoint
    if params:
        gh_url += "?" + urllib.parse.urlencode(params)
    try:
        result = subprocess.run(
            ["gh", "api", gh_url, "--cache", "1h"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    # Fallback: unauthenticated urllib (60 req/hr)
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
            print("  WARN: GitHub API rate limited. Try: gh auth login")
            return None
        if e.code == 422:
            print(f"  WARN: GitHub API rejected query: {e.read().decode()[:200]}")
            return None
        print(f"  WARN: GitHub API HTTP {e.code}")
        return None
    except Exception as e:
        print(f"  WARN: GitHub API error: {e}")
        return None


def parse_feed(xml_text):
    """Parse RSS 2.0 or Atom feed XML into list of dicts"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = []

    # RSS 2.0: rss/channel/item
    for item in root.iter("item"):
        items.append(
            {
                "title": _xml_text(item, "title"),
                "url": _xml_text(item, "link"),
                "summary": _strip_html(_xml_text(item, "description"))[:300],
                "published": _xml_text(item, "pubDate"),
            }
        )

    if items:
        return items

    # Atom with namespace
    atom_ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{atom_ns}entry"):
        link = entry.find(f"{atom_ns}link")
        url = link.get("href", "") if link is not None else ""
        items.append(
            {
                "title": _xml_text(entry, f"{atom_ns}title"),
                "url": url,
                "summary": _strip_html(_xml_text(entry, f"{atom_ns}summary"))[:300],
                "published": _xml_text(entry, f"{atom_ns}updated"),
            }
        )

    if items:
        return items

    # Atom without namespace prefix
    for entry in root.iter("entry"):
        link = entry.find("link")
        url = link.get("href", "") if link is not None else ""
        items.append(
            {
                "title": _xml_text(entry, "title"),
                "url": url,
                "summary": _strip_html(_xml_text(entry, "summary"))[:300],
                "published": _xml_text(entry, "updated"),
            }
        )

    return items


def _xml_text(parent, tag):
    el = parent.find(tag)
    return (el.text or "").strip() if el is not None else ""


def _strip_html(text):
    """Remove HTML tags and decode entities"""
    text = re.sub(r"<[^>]+>", "", text)
    return html_mod.unescape(text).strip()


def _extract_terms(text):
    """Extract meaningful search terms from a title"""
    stop = {
        "the", "a", "an", "in", "on", "at", "to", "for", "of", "with", "and",
        "or", "is", "are", "was", "were", "be", "been", "has", "have", "had",
        "do", "does", "did", "will", "would", "could", "should", "may", "might",
        "can", "new", "now", "just", "how", "what", "when", "where", "why",
        "who", "which", "this", "that", "these", "those", "it", "its", "not",
        "all", "some", "more", "most", "very", "much", "about", "also", "than",
        "into", "from", "over", "after", "before", "between", "through", "out",
        "up", "down", "been", "being", "other", "each", "every", "both", "few",
    }
    words = re.findall(r"\b[a-zA-Z0-9.]+\b", text.lower())
    terms = [w for w in words if w not in stop and len(w) > 2]
    seen = set()
    unique = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique[:5]


# -- GitHub Scrapers ----------------------------------------------------------


def scrape_trending_repos():
    """Find trending AI/ML repos via GitHub search API"""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    searches = [
        {
            "q": f"topic:ai created:>{week_ago} stars:>5",
            "sort": "stars",
            "order": "desc",
            "per_page": 15,
        },
        {
            "q": f"(free OR self-hosted OR local) topic:llm pushed:>{week_ago} stars:>50",
            "sort": "updated",
            "per_page": 10,
        },
        {
            "q": f"(ollama OR vllm OR localai OR litellm OR jan) in:name stars:>100 pushed:>{month_ago}",
            "sort": "stars",
            "per_page": 10,
        },
        {
            "q": "topic:ai (free-tier OR budget OR cost OR cheap) stars:>10",
            "sort": "stars",
            "order": "desc",
            "per_page": 10,
        },
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
            "q": "\"can't afford\" OR \"student discount\" (api OR ai OR llm) is:issue",
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


# -- News Scrapers ------------------------------------------------------------


def scrape_news_feeds():
    """Scrape RSS/Atom news feeds from configured sources"""
    all_items = []

    for feed_cfg in NEWS_RSS_FEEDS:
        url = feed_cfg["url"]
        source = feed_cfg["source"]
        category = feed_cfg["category"]
        max_items = feed_cfg.get("max_items", 10)

        xml_text = fetch_url(url)
        if not xml_text:
            continue

        items = parse_feed(xml_text)
        for item in items[:max_items]:
            if not item.get("title"):
                continue
            all_items.append(
                {
                    "title": item["title"][:200],
                    "summary": item.get("summary", "")[:300],
                    "url": item.get("url", ""),
                    "source": source,
                    "category": category,
                    "published": item.get("published", ""),
                }
            )

    return all_items


def scrape_messari():
    """Fetch crypto news from Messari API (needs MESSARI_API_KEY)"""
    api_key = load_env_var("MESSARI_API_KEY")
    if not api_key:
        print("  SKIP: MESSARI_API_KEY not set (add to skills/x/.env)")
        return []

    url = (
        "https://data.messari.io/api/v1/news"
        "?fields=id,title,content,references,author,published_at,tags"
        "&page[size]=20"
    )
    content = fetch_url(url, headers={"x-messari-api-key": api_key})
    if not content:
        return []

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        print("  WARN: Messari returned invalid JSON")
        return []

    items = []
    for article in data.get("data", []):
        # Filter to last 3 days
        published = article.get("published_at", "")
        if published:
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if pub_dt < datetime.now(timezone.utc) - timedelta(days=3):
                    continue
            except (ValueError, TypeError):
                pass

        refs = article.get("references") or []
        ref_url = refs[0].get("url", "") if refs else ""

        items.append(
            {
                "title": (article.get("title") or "")[:200],
                "summary": _strip_html(article.get("content") or "")[:300],
                "url": ref_url,
                "source": "messari",
                "category": "crypto",
                "published": published,
                "tags": [t.get("name", "") for t in (article.get("tags") or [])[:5]],
            }
        )

    return items


def scrape_markdown_changelogs():
    """Scrape markdown changelogs (e.g., Claude Code CHANGELOG.md)"""
    items = []
    for cl in CHANGELOGS:
        text = fetch_url(cl["url"])
        if not text:
            continue

        max_entries = cl.get("max_entries", 3)
        sections = re.split(r"^## ", text, flags=re.MULTILINE)[1 : max_entries + 1]

        for section in sections:
            lines = section.strip().split("\n")
            heading = lines[0].strip()
            body = "\n".join(lines[1:6]).strip()[:300]

            # Convert raw.githubusercontent.com to github.com blob URL
            display_url = cl["url"]
            display_url = display_url.replace(
                "raw.githubusercontent.com", "github.com"
            ).replace("/main/", "/blob/main/")

            items.append(
                {
                    "title": f"{cl['source'].replace('_', ' ').title()}: {heading}",
                    "summary": _strip_html(body),
                    "url": display_url,
                    "source": cl["source"],
                    "category": cl["category"],
                    "published": "",
                }
            )

    return items


# -- Query Generator ----------------------------------------------------------


def generate_x_queries(repos, issues, releases, news=None):
    """Generate X search queries from all scraped data"""
    queries = []

    # -- Standard high-value queries (always included) --
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

    # -- From trending repos --
    for repo in repos[:15]:
        name = repo["name"].split("/")[-1]
        topics = repo.get("topics", [])

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

        if repo["stars"] > 500:
            queries.append(
                {
                    "query": f'"{name}" (trying OR "just installed" OR setup) within_time:3d min_faves:3',
                    "priority": "P4",
                    "source": "github_trending",
                    "context": f"New users of {repo['name']}",
                }
            )

    # -- From cost issues -> find authors on X --
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

    # -- From new releases -> find announcement threads --
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

    # -- From news items -> find related X conversations --
    if news:
        for item in news[:20]:
            title = item.get("title", "")
            category = item.get("category", "")
            source = item.get("source", "unknown")

            terms = _extract_terms(title)
            if len(terms) < 2:
                continue

            priority = "P3" if category == "ai" else "P4"
            query_str = f'({" OR ".join(terms[:3])}) within_time:3d min_faves:3'

            queries.append(
                {
                    "query": query_str,
                    "priority": priority,
                    "source": f"news_{source}",
                    "context": f"News: {title[:80]}",
                }
            )

    return queries


# -- Commands -----------------------------------------------------------------


def cmd_scrape():
    """Run full scrape cycle"""
    print("=== /x Skill Scraper ===\n")

    print("[1/7] Scraping trending AI repos (GitHub)...")
    repos = scrape_trending_repos()
    print(f"  Found {len(repos)} repos")

    print("[2/7] Scraping cost-related issues (GitHub)...")
    issues = scrape_cost_issues()
    print(f"  Found {len(issues)} issues")

    print("[3/7] Checking recent releases (GitHub)...")
    releases = scrape_new_releases()
    print(f"  Found {len(releases)} releases")

    print("[4/7] Fetching RSS/Atom news feeds...")
    rss_news = scrape_news_feeds()
    print(f"  Found {len(rss_news)} news items from RSS")

    print("[5/7] Fetching markdown changelogs...")
    changelog_news = scrape_markdown_changelogs()
    print(f"  Found {len(changelog_news)} changelog entries")

    print("[6/7] Fetching Messari crypto news...")
    messari_news = scrape_messari()
    print(f"  Found {len(messari_news)} crypto articles")

    all_news = rss_news + changelog_news + messari_news

    print("[7/7] Generating X search queries...")
    x_queries = generate_x_queries(repos, issues, releases, all_news)
    print(f"  Generated {len(x_queries)} queries")

    feed = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "repos": repos,
        "issues": issues,
        "releases": releases,
        "news": all_news,
        "browse_hints": BROWSE_HINTS,
        "queries": x_queries,
        "stats": {
            "repos_found": len(repos),
            "issues_found": len(issues),
            "releases_found": len(releases),
            "news_items": len(all_news),
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

    # News summary by category
    if all_news:
        print(f"\n  News ({len(all_news)} items):")
        for cat in ["ai", "coding", "crypto"]:
            cat_items = [n for n in all_news if n.get("category") == cat]
            if cat_items:
                print(f"    {cat.upper()}: {len(cat_items)} items")

    print(f"\nReady for: /x post OR /x research OR /x compose")


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
    news = feed.get("news", [])

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
    print(f"News: {stats.get('news_items', 0)}")
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

    # News by category
    if news:
        print(f"\nNews ({len(news)} items):")
        for cat in ["ai", "coding", "crypto"]:
            cat_items = [n for n in news if n.get("category") == cat]
            if cat_items:
                print(f"  {cat.upper()} ({len(cat_items)}):")
                for n in cat_items[:3]:
                    title = n['title'][:70].encode('ascii', 'replace').decode('ascii')
                    print(f"    {title}")

    # Browse hints
    hints = feed.get("browse_hints", [])
    if hints:
        print(f"\nBrowse hints ({len(hints)} URLs for Claude to check):")
        for h in hints:
            print(f"  [{h['category']}] {h['url']}")

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
        print(f"  News: {stats.get('news_items', 0)}")
    else:
        print(f"\nFeed: MISSING")
        print(f"  Run: python scraper.py scrape")


def main():
    parser = argparse.ArgumentParser(
        description="Scraper for /x skill - aggregates GitHub, news, and crypto data"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("scrape", help="Full scrape -> feed.json")
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
