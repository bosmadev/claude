#!/usr/bin/env python3
"""
Unified X skill script -- all X/Twitter operations in one file.

API Operations (requires curl_cffi + beautifulsoup4 + x-client-transaction-id):
  python x.py test [--verbose]                      # Verify auth works
  python x.py cookies CT0 AUTH                      # Set cookies manually
  python x.py search "query" [--count N] [--min-engagement N]  # Search tweets (JSON output)
  python x.py post TWEET_ID TEXT [--allow-original] # Reply to a tweet
  python x.py quote TWEET_ID REPLY_TO TEXT [--allow-original]  # Quote tweet as reply
  python x.py analytics TWEET_ID                    # Show engagement metrics
  python x.py thread REPLY_TO TEXT1 TEXT2 [...]     # Post thread of replies
  python x.py tweet TEXT                            # Post original tweet
  python x.py delete TWEET_ID                       # Delete a tweet
  python x.py config [--set KEY VALUE]              # Show or set config

Exit Codes:
  0 = Success
  1 = API error (rate limit, auth failure, network)
  2 = Validation error (blocked text, too long, missing params)
  3 = Profile wall violation (attempted original post without reply_to)
  4 = Self-reply violation (attempted reply to own post)

Scraping (stdlib only, zero LLM cost):
  python x.py scrape                        # Full scrape -> feed.json
  python x.py feed                          # Show current feed summary

History & Rate Limiting:
  python x.py log URL AUTHOR TEXT TOPIC QUERY REACH
  python x.py check URL                     # Dedup check (exit 0=ok, 1=already replied)
  python x.py history [--days N] [--topic]  # Show posting history
  python x.py status                        # Show counts and reach
  python x.py rate-check                    # Rate limit check (exit 0=ok, 1=limited)

Auto-posting (launches Claude -p headless):
  python x.py auto [--posts N] [--mode reply|compose] [--model sonnet|haiku|opus]
                   [--budget F] [--max-turns N] [--dry-run]

Schedulers:
  python x.py scraper-install [HOURS]       # Install scraper scheduler (default: 6h)
  python x.py scraper-uninstall             # Remove scraper scheduler
  python x.py scraper-status                # Show scraper scheduler status
  python x.py poster-install [HOURS]        # Install auto-poster scheduler (default: 12h)
  python x.py poster-uninstall              # Remove auto-poster scheduler
  python x.py poster-status                 # Show auto-poster scheduler status
"""

import argparse
import asyncio
import hashlib
import html as html_mod
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Optional deps -- only needed for X API commands (test/search/post/tweet/delete/cookies)
HAS_CURL_CFFI = False
HAS_BS4 = False
HAS_XCT = False

try:
    from curl_cffi.requests import AsyncSession
    HAS_CURL_CFFI = True
except ImportError:
    pass

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    pass

try:
    from x_client_transaction import ClientTransaction
    HAS_XCT = True
except ImportError:
    pass


# =============================================================================
# TTY Colors (auto-detect terminal support)
# =============================================================================

_USE_COLOR = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    """Wrap text in ANSI escape if stdout is a TTY."""
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text


def _green(t: str) -> str: return _c("32", t)
def _red(t: str) -> str: return _c("31", t)
def _yellow(t: str) -> str: return _c("33", t)
def _cyan(t: str) -> str: return _c("36", t)
def _blue(t: str) -> str: return _c("34", t)
def _bold(t: str) -> str: return _c("1", t)
def _dim(t: str) -> str: return _c("2", t)


# =============================================================================
# Constants
# =============================================================================

# X's public bearer token (same for all clients)
BEARER = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
ON_DEMAND_RE = re.compile(r"""['|"]{1}ondemand\.s['|"]{1}:\s*['|"]{1}([\w]*)['|"]{1}""")

# Feature flags required by X GraphQL endpoints
# Captured from live browser request (2026-02-12) -- must match EXACTLY
GRAPHQL_FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": True,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": False,
    "responsive_web_enhance_cards_enabled": False,
    "tweetypie_unmention_optimization_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
}

GITHUB_API = "https://api.github.com"
SCRAPER_TASK_NAME = "XSkillScraper"
POSTER_TASK_NAME = "XSkillAutoPost"
SCRAPER_UA = "x-skill-scraper/1.0"

MODELS = {
    "sonnet": "claude-sonnet-4-5-20250929",
    "haiku": "claude-haiku-4-5-20251001",
    "opus": "claude-opus-4-6",
}

# -- News Source Configuration ------------------------------------------------

NEWS_RSS_FEEDS = [
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


# =============================================================================
# Shared Utilities
# =============================================================================


def get_skill_dir():
    """Get path to skills/x/ directory"""
    return Path(__file__).resolve().parent.parent


def get_data_dir():
    """Get path to skills/x/data/ directory, creating if needed"""
    data_dir = get_skill_dir() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_cookies_path():
    return get_data_dir() / "cookies.json"


def get_env_path():
    return get_skill_dir() / ".env"


def get_config_path():
    return get_data_dir() / "config.json"


def get_history_path():
    return get_data_dir() / "history.json"


def get_feed_path():
    return get_data_dir() / "feed.json"


def get_skill_md_path():
    return get_skill_dir() / "SKILL.md"


def load_env_var(name):
    """Load env var from system env or skills/x/.env file"""
    val = os.environ.get(name)
    if val:
        return val
    env_path = get_env_path()
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    return None


def load_config():
    """Load config.json, auto-generating from .env if missing"""
    config_path = get_config_path()
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
        print("NOTE: No share_url configured. Set X_SHARE_URL in .env or data/config.json")

    return config


def fetch_url(url, headers=None, timeout=15):
    """Fetch URL content as text, return None on failure"""
    hdrs = {"User-Agent": SCRAPER_UA}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  WARN: Failed to fetch {url[:80]}: {e}")
        return None


def _require_api_deps():
    """Check that X API dependencies are installed, exit with helpful message if not"""
    missing = []
    if not HAS_CURL_CFFI:
        missing.append("curl_cffi")
    if not HAS_BS4:
        missing.append("beautifulsoup4")
    if not HAS_XCT:
        missing.append("x-client-transaction-id")
    if missing:
        print(f"ERROR: Missing dependencies: {', '.join(missing)}")
        print(f"Install with: pip install {' '.join(missing)}")
        sys.exit(1)


# =============================================================================
# X API Client
# =============================================================================


async def init_session():
    """Initialize curl_cffi session with cookies + transaction ID generator.
    Returns (session, transaction_generator, csrf_token) or exits on failure.
    """
    _require_api_deps()

    cookies_path = get_cookies_path()
    if not cookies_path.exists():
        print("ERROR: No cookies found. Run: python x.py cookies CT0 AUTH_TOKEN", file=sys.stderr)
        sys.exit(1)

    with open(cookies_path) as f:
        cd = json.load(f)

    if "ct0" not in cd or "auth_token" not in cd:
        print("ERROR: cookies.json must have ct0 and auth_token", file=sys.stderr)
        sys.exit(1)

    s = AsyncSession(impersonate="chrome131")
    s.cookies.set("ct0", cd["ct0"], domain=".x.com")
    s.cookies.set("auth_token", cd["auth_token"], domain=".x.com")

    # Fetch homepage (sets __cf_bm and other Cloudflare cookies)
    home_r = await s.get("https://x.com", headers={"user-agent": UA})
    if home_r.status_code != 200:
        print(f"ERROR: Homepage returned {home_r.status_code}", file=sys.stderr)
        sys.exit(1)

    home_soup = BeautifulSoup(home_r.text, "html.parser")

    # Find ondemand.s JS bundle hash
    hashes = ON_DEMAND_RE.findall(home_r.text)
    if not hashes:
        print("ERROR: Could not find ondemand.s hash in homepage", file=sys.stderr)
        sys.exit(1)

    ondemand_url = f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{hashes[0]}a.js"
    ondemand_r = await s.get(ondemand_url, headers={"user-agent": UA})

    ct = ClientTransaction(home_soup, ondemand_r.text)
    return s, ct, cd["ct0"]


def build_headers(ct, csrf, method, path):
    """Build full X API headers with transaction ID"""
    tx_id = ct.generate_transaction_id(method=method, path=path)
    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "authorization": BEARER,
        "content-type": "application/json",
        "referer": "https://x.com/",
        "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": UA,
        "x-client-transaction-id": tx_id,
        "x-csrf-token": csrf,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en",
    }


def _parse_tweet_result(item_content):
    """Extract tweet data from GraphQL itemContent"""
    result = item_content.get("tweet_results", {}).get("result", {})
    if not result:
        return None

    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet", {})

    legacy = result.get("legacy", {})
    user_result = result.get("core", {}).get("user_results", {}).get("result", {})
    user_core = user_result.get("core", {})
    user_legacy = user_result.get("legacy", {})
    user_data = user_core if user_core.get("screen_name") else user_legacy

    if not legacy or not user_data:
        return None

    screen_name = user_data.get("screen_name", "unknown")
    tweet_id = legacy.get("id_str", result.get("rest_id", ""))
    views = result.get("views", {}).get("count", "0")

    return {
        "id": tweet_id,
        "text": legacy.get("full_text", ""),
        "author": screen_name,
        "author_name": user_data.get("name", "unknown"),
        "likes": legacy.get("favorite_count", 0),
        "retweets": legacy.get("retweet_count", 0),
        "replies": legacy.get("reply_count", 0),
        "views": int(views) if str(views).isdigit() else 0,
        "url": f"https://x.com/{screen_name}/status/{tweet_id}",
        "created_at": legacy.get("created_at", ""),
    }


async def cmd_test(verbose=False):
    """Verify auth works by fetching current user info"""
    s, ct, csrf = await init_session()

    if verbose:
        print("=== X API Auth Test (curl_cffi + XClientTransaction) ===\n")
        print(f"Bearer token check: ...{BEARER[-20:]}")
        print(f"  Contains %3D: {'%3D' in BEARER}\n")

    # Test 1: account/settings (v1.1 REST)
    path = "/i/api/1.1/account/settings.json"
    headers = build_headers(ct, csrf, "GET", path)
    r = await s.get(f"https://x.com{path}", headers=headers)

    if r.status_code == 200:
        data = r.json()
        print(f"Authenticated as: {_cyan('@' + data.get('screen_name', '?'))}")
        print(_green("Auth OK!"))
    else:
        print(_red(f"ERROR: Auth test failed (status {r.status_code})"))
        print(f"Body: {_dim(r.text[:300])}")
        await s.close()
        sys.exit(1)

    if verbose:
        # Test 2: Viewer GraphQL
        print("\nTesting /i/api/graphql/*/Viewer (GraphQL)...")
        path2 = "/i/api/graphql/pjFnHGVqCjTcZol0xcBJjw/Viewer"
        params2 = "?variables=%7B%22withCommunitiesMemberships%22%3Atrue%7D&features=%7B%22rweb_tipjar_consumption_enabled%22%3Atrue%7D&fieldToggles=%7B%22isDelegate%22%3Afalse%7D"
        h2 = build_headers(ct, csrf, "GET", path2)
        r2 = await s.get(f"https://x.com{path2}{params2}", headers=h2)
        print(f"  Status: {r2.status_code}, Body length: {len(r2.text)}")
        if r2.status_code == 200:
            data2 = r2.json()
            viewer = data2.get("data", {}).get("viewer", {}).get("user_results", {}).get("result", {})
            legacy2 = viewer.get("legacy", {})
            print(f"  Viewer: @{legacy2.get('screen_name', '?')}")

        # Test 3: Control test without transaction ID
        print("\nControl test (no transaction ID)...")
        h3 = build_headers(ct, csrf, "GET", path)
        del h3["x-client-transaction-id"]
        r3 = await s.get(f"https://x.com{path}", headers=h3)
        print(f"  Status: {r3.status_code} (expected 404 without tx-id)")

    await s.close()


async def cmd_search(query: str, count: int = 20, min_engagement: int = 0):
    """Search tweets and return JSON results

    Args:
        query: Search query
        count: Max results to return
        min_engagement: Minimum engagement score (views + likes*5 + retweets*10 + replies*13.5)
    """
    s, ct, csrf = await init_session()

    variables = {
        "rawQuery": query,
        "count": count,
        "querySource": "typed_query",
        "product": "Top",
        "withGrokTranslatedBio": False,
    }
    params = urllib.parse.urlencode({
        "variables": json.dumps(variables, separators=(",", ":")),
        "features": json.dumps(GRAPHQL_FEATURES, separators=(",", ":")),
    })

    path = "/i/api/graphql/cGK-Qeg1XJc2sZ6kgQw_Iw/SearchTimeline"
    headers = build_headers(ct, csrf, "GET", path)
    r = await s.get(f"https://x.com{path}?{params}", headers=headers)

    if r.status_code != 200:
        # Try alternate search endpoint
        path2 = "/i/api/2/search/adaptive.json"
        params2 = urllib.parse.urlencode({
            "q": query,
            "result_filter": "top",
            "count": count,
            "query_source": "typed_query",
            "tweet_search_mode": "live",
            "include_entities": 1,
        })
        headers2 = build_headers(ct, csrf, "GET", path2)
        r = await s.get(f"https://x.com{path2}?{params2}", headers=headers2)

    if r.status_code != 200:
        print(json.dumps({"error": f"Search failed: status {r.status_code}", "tweets": []}))
        sys.exit(1)

    results = []
    try:
        raw = r.text.strip()
        if not raw:
            print(json.dumps({"error": "Empty response body", "tweets": [], "raw_status": r.status_code}))
            sys.exit(1)
        data = json.loads(raw)
        instructions = (
            data.get("data", {})
            .get("search_by_raw_query", {})
            .get("search_timeline", {})
            .get("timeline", {})
            .get("instructions", [])
        )
        for inst in instructions:
            entries = inst.get("entries", [])
            for entry in entries:
                content = entry.get("content", {})
                item = content.get("itemContent", {})
                if not item:
                    items = content.get("items", [])
                    for sub in items:
                        item = sub.get("item", {}).get("itemContent", {})
                        if item:
                            tweet = _parse_tweet_result(item)
                            if tweet:
                                results.append(tweet)
                    continue
                tweet = _parse_tweet_result(item)
                if tweet:
                    results.append(tweet)
    except Exception as e:
        print(json.dumps({"error": f"Parse error: {e}", "tweets": [], "raw_status": r.status_code}))
        sys.exit(1)

    # Filter by min_engagement if specified
    if min_engagement > 0:
        filtered = []
        for t in results:
            engagement = t['views'] + (t['likes'] * 5) + (t['retweets'] * 10) + (t['replies'] * 13.5)
            if engagement >= min_engagement:
                filtered.append(t)
        results = filtered

    print(json.dumps({"tweets": results, "count": len(results)}, indent=2))
    await s.close()


def sanitize_reply_text(text: str) -> str:
    """Enforce reply quality rules at the Python level.

    This runs BEFORE every post/reply to catch agent mistakes:
    - Strip non-ASCII characters (encoding artifacts)
    - Block banned words/references
    - Validate number format
    - Enforce character limit for reply-style posts
    """
    import unicodedata

    # 1. Replace common unicode artifacts with ASCII equivalents
    replacements = {
        "\u2014": "--",   # em-dash
        "\u2013": "-",    # en-dash
        "\u2018": "'",    # left single quote
        "\u2019": "'",    # right single quote
        "\u201c": '"',    # left double quote
        "\u201d": '"',    # right double quote
        "\u2026": "...",  # ellipsis
        "\u00e4": "a", "\u00c4": "A",  # a-umlaut
        "\u00f6": "o", "\u00d6": "O",  # o-umlaut
        "\u00fc": "u", "\u00dc": "U",  # u-umlaut
        "\u00e9": "e", "\u00c9": "E",  # e-acute
        "\u00e8": "e", "\u00c8": "E",  # e-grave
        "\u00e0": "a", "\u00c0": "A",  # a-grave
        "\u00f1": "n", "\u00d1": "N",  # n-tilde
    }
    for uni, ascii_eq in replacements.items():
        text = text.replace(uni, ascii_eq)

    # 1.5. Remove unnecessary backslash escaping (agents sometimes add \! \? \" \')
    # With echo 'TEXT', these backslashes are literal and look wrong in the post
    text = re.sub(r'\\([!?"\'])', r'\1', text)

    # 2. Strip any remaining non-ASCII (keep only printable ASCII + newlines)
    cleaned = []
    for ch in text:
        if ord(ch) < 128 or ch == "\n":
            cleaned.append(ch)
        # silently drop non-ASCII
    text = "".join(cleaned)

    # 3. Block banned references (case-insensitive)
    banned_patterns = [
        r"github\.com",
        r"gist\.github",
        r"\bgithub\b",
        r"\bgist\b",
        r"\brepo\b",
        r"\brepository\b",
        r"\bsource\s*code\b",
        r"\bopen\s*source\b",
    ]
    for pat in banned_patterns:
        if re.search(pat, text, re.IGNORECASE):
            print(_red(f"BLOCKED: Reply contains banned reference matching '{pat}'"))
            print(_red(f"Text was: {text[:200]}"))
            sys.exit(1)

    # 4. Block negative/aggressive sarcasm (must be helpful/funny, not mean)
    negative_patterns = [
        r"love watching (people|you|them|others) (discover|realize|learn|find out)",
        r"isn't magic",
        r"not (magic|perfect|flawless)",
        r"hope you (fail|struggle|suffer|hit|encounter)",
        r"(welcome to|enjoy) (reality|the real world|pain)",
        r"good luck with that",
        r"sure that('ll|will) work",
        r"let me know how that (goes|works out)",
        r"why so (aggro|aggressive|angry|negative)",
    ]
    for pat in negative_patterns:
        if re.search(pat, text, re.IGNORECASE):
            print(_red(f"BLOCKED: Reply contains negative/sarcastic tone matching '{pat}'"))
            print(_red(f"Text was: {text[:200]}"))
            print(_yellow("TIP: Be helpful/funny, not sarcastic/mean. Suggest solutions or ask questions."))
            sys.exit(1)

    # 4.5. Block vague/generic "AI slop" comments (must be specific and helpful)
    vague_patterns = [
        r"^(nice|cool|great|awesome|interesting|amazing)!?$",  # Single-word reactions
        r"^(this is|that's|it's) (nice|cool|great|awesome|interesting|amazing)!?$",
        r"^(love|like) this!?$",
        r"^thanks for sharing!?$",
        r"^(good|great) (post|tweet|thread)!?$",
        r"^(totally|completely|absolutely) agree!?$",
        r"^so true!?$",
        r"^exactly!?$",
        r"^this!?$",
        r"^yep!?$",
        r"^yeah!?$",
        r"^wow!?$",
    ]
    for pat in vague_patterns:
        if re.search(pat, text.strip(), re.IGNORECASE):
            print(_red(f"BLOCKED: Reply is too vague/generic matching '{pat}'"))
            print(_red(f"Text was: {text[:200]}"))
            print(_yellow("TIP: Reference specific details from the original post. Add your own experience or ask a question."))
            sys.exit(1)

    # 4.6. Block Wikipedia/narrator/news anchor tone (must sound like a real person)
    narrator_patterns = [
        r"\b(furthermore|moreover|additionally|in addition|consequently)\b",  # Formal transitions
        r"\b(one can|one should|one might|it is worth noting)\b",  # Impersonal voice
        r"\b(it('s| is) important to note|it('s| is) worth mentioning)\b",  # Narrator framing
        r"\b(this (allows|enables|provides|offers) (users?|developers?|teams?))\b",  # Feature description style
        r"^(the|this) .{20,}(is|are|was|were) (a|an|the)",  # Wikipedia opening style
        r"\b(comprehensive|robust|powerful|versatile|feature-rich)\b",  # Marketing speak
        r"\?(\\n| ){0,3}(what|how|have you|did you|are you).{10,}\?$",  # Forced double question
    ]
    for pat in narrator_patterns:
        if re.search(pat, text, re.IGNORECASE):
            print(_red(f"BLOCKED: Reply sounds like Wikipedia/narrator matching '{pat}'"))
            print(_red(f"Text was: {text[:200]}"))
            print(_yellow("TIP: Write like you're texting a friend. Drop the formal tone. Just react naturally."))
            sys.exit(1)

    # 4.7. Block passive observations (no engagement hook - people won't respond)
    passive_patterns = [
        r"\b(is wild|that'?s wild|so wild)\b",  # Passive observation
        r"\b(hits different|hit different)\b",  # No engagement trigger
        r"\b(really (hits|slaps|goes hard))\b",  # Observation without question/help
        r"^[^?!.]{1,30}(is|was|are) (wild|crazy|insane|nuts|sick)$",  # Just adjective, no hook
        r"\b(lowkey|highkey|ngl) [^?]{10,}$",  # Observation ending without question
        r"^(the way|the fact that) [^?]{15,}$",  # Observation with no engagement
        r"\b(gotta love|you love to see)\b",  # Passive approval
        r"^respect[^?]{0,20}$",  # One-word approval
        r"^(big|huge|massive) (W|L|win|loss|mood|vibe)[^?]{0,20}$",  # Reaction without hook
        r"\bbro\b",  # NEVER use "bro" - sounds forced/cringe
    ]
    for pat in passive_patterns:
        if re.search(pat, text, re.IGNORECASE):
            print(_red(f"BLOCKED: Reply is passive observation (no engagement trigger) matching '{pat}'"))
            print(_red(f"Text was: {text[:200]}"))
            print(_yellow("TIP: Add a question, share a solution, or help them solve their problem. Engagement requires a hook."))
            sys.exit(1)

    # Also block if reply is suspiciously short (< 20 chars) without being a question
    if len(text.strip()) < 20 and "?" not in text:
        print(_red(f"BLOCKED: Reply too short ({len(text.strip())} chars) without being a question"))
        print(_red(f"Text was: {text[:200]}"))
        print(_yellow("TIP: Add more substance. Reference the original post or share your experience."))
        sys.exit(1)

    # 5. Block "bro" -- user explicitly banned this word
    if re.search(r"\bbro\b", text, re.IGNORECASE):
        text = re.sub(r"\bbro\b", "dude", text, flags=re.IGNORECASE)
        print(_yellow("SANITIZED: Replaced 'bro' with 'dude'"))

    # 6. Warn if reply looks too long for a casual reply (>280 chars)
    if len(text) > 280:
        print(_yellow(f"WARNING: Reply is {len(text)} chars -- might be too long for engagement"))

    return text.strip()


async def cmd_post(tweet_id: str, text: str, allow_original: bool = False):
    """Post a reply to a specific tweet

    Args:
        tweet_id: Tweet ID to reply to (REQUIRED - no standalone posts allowed)
        text: Reply text
        allow_original: Override profile wall protection (manual use only)

    Exit codes:
        0: Success
        1: API error (rate limit, auth failure, network)
        2: Validation error (blocked text, too long, missing params)
        3: Profile wall violation (attempted original post - no reply_to)
        4: Self-reply violation (attempted reply to own post)
    """
    # Profile wall guard: reply_to is MANDATORY
    if not tweet_id:
        print(_red("ERROR: Profile wall violation - reply_to parameter required"))
        print(_red("This account NEVER posts original tweets, only replies"))
        sys.exit(3)

    # Self-reply guard: check if replying to own post
    if not allow_original:
        config = load_config()
        my_handle = config.get("handle", "").lstrip("@") if config else ""

        if my_handle:
            tweet_info = await get_tweet_details(tweet_id)
            if tweet_info and tweet_info.get("author", "").lstrip("@") == my_handle:
                print(_red(f"ERROR: Self-reply violation - cannot reply to own post"))
                print(_red(f"Target tweet author: @{tweet_info.get('author')}"))
                print(_red(f"Your handle: @{my_handle}"))
                sys.exit(4)

    # Fix literal \n from shell arguments → actual newlines
    text = text.replace("\\n", "\n")
    # Enforce reply quality rules
    text = sanitize_reply_text(text)
    max_chars = 4000  # X Premium limit
    if len(text) > max_chars:
        print(_red(f"ERROR: Reply exceeds {max_chars} character limit ({len(text)} chars)"))
        sys.exit(2)
    s, ct, csrf = await init_session()

    path = "/i/api/graphql/a1p9RWpkYKBjWv_I3WzS-A/CreateTweet"
    headers = build_headers(ct, csrf, "POST", path)

    payload = {
        "variables": {
            "tweet_text": text,
            "reply": {
                "in_reply_to_tweet_id": tweet_id,
                "exclude_reply_user_ids": [],
            },
            "dark_request": False,
            "media": {"media_entities": [], "possibly_sensitive": False},
            "semantic_annotation_ids": [],
        },
        "features": GRAPHQL_FEATURES,
        "queryId": "a1p9RWpkYKBjWv_I3WzS-A",
    }

    r = await s.post(f"https://x.com{path}", headers=headers, json=payload)

    if r.status_code == 200:
        data = r.json()
        result = (
            data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
        )
        new_id = result.get("rest_id", "")
        print(json.dumps({
            "success": True,
            "tweet_id": new_id,
            "reply_to": tweet_id,
            "text": text,
        }))
    else:
        print(json.dumps({
            "success": False,
            "error": f"Status {r.status_code}: {r.text[:200]}",
            "reply_to": tweet_id,
            "text": text,
        }))
        sys.exit(1)

    await s.close()


async def get_tweet_details(tweet_id: str):
    """Fetch tweet details including author

    Args:
        tweet_id: Tweet ID to fetch

    Returns:
        dict with keys: id, text, author, author_name, likes, retweets, replies, views, url
        or None if fetch fails
    """
    try:
        s, ct, csrf = await init_session()

        # Use TweetDetail GraphQL endpoint
        path = "/i/api/graphql/rePnxwe9LZ51nQ7Sn_xN_A/TweetDetail"
        variables = {
            "focalTweetId": tweet_id,
            "with_rux_injections": False,
            "includePromotedContent": True,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        params = urllib.parse.urlencode({
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(GRAPHQL_FEATURES, separators=(",", ":")),
        })

        headers = build_headers(ct, csrf, "GET", path)
        r = await s.get(f"https://x.com{path}?{params}", headers=headers)

        if r.status_code != 200:
            await s.close()
            return None

        data = r.json()
        # Navigate the TweetDetail response structure
        instructions = (
            data.get("data", {})
            .get("threaded_conversation_with_injections_v2", {})
            .get("instructions", [])
        )

        for inst in instructions:
            entries = inst.get("entries", [])
            for entry in entries:
                if entry.get("entryId", "").startswith("tweet-"):
                    content = entry.get("content", {})
                    item = content.get("itemContent", {})
                    tweet = _parse_tweet_result(item)
                    if tweet and tweet.get("id") == tweet_id:
                        await s.close()
                        return tweet

        await s.close()
        return None
    except Exception as e:
        return None


async def cmd_tweet(text: str):
    """Post an original tweet (not a reply) for compose mode"""
    # Fix literal \n from shell arguments → actual newlines
    text = text.replace("\\n", "\n")
    # Enforce reply quality rules (same sanitization for tweets)
    text = sanitize_reply_text(text)
    # X Premium allows up to 4,000 chars
    max_chars = 4000
    if len(text) > max_chars:
        print(_red(f"ERROR: Tweet exceeds {max_chars} character limit ({len(text)} chars)"))
        sys.exit(2)
    s, ct, csrf = await init_session()

    path = "/i/api/graphql/a1p9RWpkYKBjWv_I3WzS-A/CreateTweet"
    headers = build_headers(ct, csrf, "POST", path)

    payload = {
        "variables": {
            "tweet_text": text,
            "dark_request": False,
            "media": {"media_entities": [], "possibly_sensitive": False},
            "semantic_annotation_ids": [],
        },
        "features": GRAPHQL_FEATURES,
        "queryId": "a1p9RWpkYKBjWv_I3WzS-A",
    }

    r = await s.post(f"https://x.com{path}", headers=headers, json=payload)

    if r.status_code == 200:
        data = r.json()
        result = (
            data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
        )
        new_id = result.get("rest_id", "")
        config = load_config()
        handle = config.get("handle", "unknown") if config else "unknown"
        print(json.dumps({
            "success": True,
            "tweet_id": new_id,
            "text": text,
            "url": f"https://x.com/{handle}/status/{new_id}" if new_id else "",
        }))
    else:
        print(json.dumps({
            "success": False,
            "error": f"Status {r.status_code}: {r.text[:200]}",
            "text": text,
        }))
        sys.exit(1)

    await s.close()


async def cmd_delete(tweet_id: str):
    """Delete a tweet by ID"""
    s, ct, csrf = await init_session()

    path = "/i/api/graphql/VaenaVgh5q5ih7kvyVjgtg/DeleteTweet"
    headers = build_headers(ct, csrf, "POST", path)

    payload = {
        "variables": {"tweet_id": tweet_id, "dark_request": False},
        "queryId": "VaenaVgh5q5ih7kvyVjgtg",
    }

    r = await s.post(f"https://x.com{path}", headers=headers, json=payload)

    if r.status_code == 200:
        print(json.dumps({"success": True, "deleted": tweet_id}))
    else:
        print(json.dumps({"success": False, "error": f"Status {r.status_code}: {r.text[:200]}"}))
        sys.exit(1)

    await s.close()


async def cmd_quote(tweet_id: str, text: str, reply_to: str, allow_original: bool = False):
    """Create a quote tweet with commentary, posted as a reply

    Args:
        tweet_id: Tweet ID to quote
        text: Commentary text
        reply_to: REQUIRED - tweet ID to reply to (quote is always posted as a reply)
        allow_original: Override profile wall protection (manual use only)

    Exit codes:
        0: Success
        1: API error (rate limit, auth failure, network)
        2: Validation error (blocked text, too long, missing params)
        3: Profile wall violation (no reply_to specified)
        4: Self-reply violation (attempted reply to own post)
    """
    # Profile wall guard: reply_to is MANDATORY
    if not reply_to:
        print(_red("ERROR: Profile wall violation - reply_to parameter required for quote tweets"))
        print(_red("Quote tweets MUST be posted as replies, not standalone"))
        sys.exit(3)

    # Self-reply guard: check if replying to own post
    if not allow_original:
        config = load_config()
        my_handle = config.get("handle", "").lstrip("@") if config else ""

        if my_handle:
            tweet_info = await get_tweet_details(reply_to)
            if tweet_info and tweet_info.get("author", "").lstrip("@") == my_handle:
                print(_red(f"ERROR: Self-reply violation - cannot reply to own post"))
                print(_red(f"Target tweet author: @{tweet_info.get('author')}"))
                print(_red(f"Your handle: @{my_handle}"))
                sys.exit(4)

    # Append quoted tweet URL to the text (X's quote tweet format)
    quoted_tweet_info = await get_tweet_details(tweet_id)
    if quoted_tweet_info:
        quoted_url = quoted_tweet_info.get("url", f"https://x.com/i/status/{tweet_id}")
    else:
        quoted_url = f"https://x.com/i/status/{tweet_id}"

    # Add quote URL at the end (X will render it as embedded quote)
    full_text = f"{text}\n\n{quoted_url}"

    # Fix literal \n from shell arguments → actual newlines
    full_text = full_text.replace("\\n", "\n")
    # Enforce reply quality rules
    full_text = sanitize_reply_text(full_text)
    max_chars = 4000
    if len(full_text) > max_chars:
        print(_red(f"ERROR: Quote tweet exceeds {max_chars} character limit ({len(full_text)} chars)"))
        sys.exit(2)

    s, ct, csrf = await init_session()

    path = "/i/api/graphql/a1p9RWpkYKBjWv_I3WzS-A/CreateTweet"
    headers = build_headers(ct, csrf, "POST", path)

    payload = {
        "variables": {
            "tweet_text": full_text,
            "reply": {
                "in_reply_to_tweet_id": reply_to,
                "exclude_reply_user_ids": [],
            },
            "dark_request": False,
            "media": {"media_entities": [], "possibly_sensitive": False},
            "semantic_annotation_ids": [],
        },
        "features": GRAPHQL_FEATURES,
        "queryId": "a1p9RWpkYKBjWv_I3WzS-A",
    }

    r = await s.post(f"https://x.com{path}", headers=headers, json=payload)

    if r.status_code == 200:
        data = r.json()
        result = (
            data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
        )
        new_id = result.get("rest_id", "")
        print(json.dumps({
            "success": True,
            "tweet_id": new_id,
            "reply_to": reply_to,
            "quoted_tweet": tweet_id,
            "text": full_text,
        }))
    else:
        print(json.dumps({
            "success": False,
            "error": f"Status {r.status_code}: {r.text[:200]}",
            "reply_to": reply_to,
            "quoted_tweet": tweet_id,
            "text": full_text,
        }))
        sys.exit(1)

    await s.close()


async def cmd_analytics(tweet_id: str):
    """Fetch and display engagement metrics for a tweet

    Exit codes:
        0: Success
        1: API error or tweet not found
    """
    tweet = await get_tweet_details(tweet_id)

    if not tweet:
        print(json.dumps({"success": False, "error": "Tweet not found or API error"}))
        sys.exit(1)

    # Calculate engagement score
    engagement_score = (
        tweet['views'] +
        (tweet['likes'] * 5) +
        (tweet['retweets'] * 10) +
        (tweet['replies'] * 13.5)
    )

    # Format as table
    print(f"\n{_bold('Tweet Analytics')}: {tweet['url']}")
    print(f"\n{_cyan('Author:')} @{tweet['author']} ({tweet['author_name']})")
    print(f"{_cyan('Text:')} {tweet['text'][:100]}{'...' if len(tweet['text']) > 100 else ''}")
    print(f"\n{_bold('Engagement Metrics:')}")
    print(f"  {'Views:':<12} {tweet['views']:>10,}")
    print(f"  {'Likes:':<12} {tweet['likes']:>10,}  (weight: 5x)")
    print(f"  {'Retweets:':<12} {tweet['retweets']:>10,}  (weight: 10x)")
    print(f"  {'Replies:':<12} {tweet['replies']:>10,}  (weight: 13.5x)")
    print(f"\n  {_green('Total Score:')} {_bold(f'{engagement_score:>10,.1f}')}")
    print()

    # Also output JSON for machine parsing
    analytics_data = {
        "success": True,
        "tweet_id": tweet_id,
        "metrics": {
            "views": tweet['views'],
            "likes": tweet['likes'],
            "retweets": tweet['retweets'],
            "replies": tweet['replies'],
            "engagement_score": engagement_score,
        },
        "author": tweet['author'],
        "url": tweet['url'],
    }
    print(json.dumps(analytics_data, indent=2))


async def cmd_thread(reply_to: str, texts: list, allow_original: bool = False):
    """Post a thread of replies (each replying to the previous)

    Implements the two-tweet pattern: main reply + self-reply with link

    Args:
        reply_to: First tweet ID to reply to (REQUIRED)
        texts: List of reply texts (each becomes a tweet in the thread)
        allow_original: Override profile wall protection (manual use only)

    Exit codes:
        0: Success
        1: API error
        2: Validation error
        3: Profile wall violation
        4: Self-reply violation
    """
    # Profile wall guard: reply_to is MANDATORY
    if not reply_to:
        print(_red("ERROR: Profile wall violation - reply_to parameter required"))
        sys.exit(3)

    # Self-reply guard on FIRST tweet only (subsequent are self-replies by design)
    if not allow_original:
        config = load_config()
        my_handle = config.get("handle", "").lstrip("@") if config else ""

        if my_handle:
            tweet_info = await get_tweet_details(reply_to)
            if tweet_info and tweet_info.get("author", "").lstrip("@") == my_handle:
                print(_red(f"ERROR: Self-reply violation - cannot reply to own post"))
                print(_red(f"Target tweet author: @{tweet_info.get('author')}"))
                sys.exit(4)

    s, ct, csrf = await init_session()
    path = "/i/api/graphql/a1p9RWpkYKBjWv_I3WzS-A/CreateTweet"

    thread_ids = []
    current_reply_to = reply_to

    for i, text in enumerate(texts):
        # Fix literal \n and sanitize
        text = text.replace("\\n", "\n")
        text = sanitize_reply_text(text)
        max_chars = 4000
        if len(text) > max_chars:
            print(_red(f"ERROR: Thread item {i+1} exceeds {max_chars} chars ({len(text)} chars)"))
            sys.exit(2)

        headers = build_headers(ct, csrf, "POST", path)
        payload = {
            "variables": {
                "tweet_text": text,
                "reply": {
                    "in_reply_to_tweet_id": current_reply_to,
                    "exclude_reply_user_ids": [],
                },
                "dark_request": False,
                "media": {"media_entities": [], "possibly_sensitive": False},
                "semantic_annotation_ids": [],
            },
            "features": GRAPHQL_FEATURES,
            "queryId": "a1p9RWpkYKBjWv_I3WzS-A",
        }

        r = await s.post(f"https://x.com{path}", headers=headers, json=payload)

        if r.status_code != 200:
            print(json.dumps({
                "success": False,
                "error": f"Thread item {i+1} failed: status {r.status_code}",
                "failed_at": i+1,
                "posted": thread_ids,
            }))
            await s.close()
            sys.exit(1)

        data = r.json()
        result = (
            data.get("data", {})
            .get("create_tweet", {})
            .get("tweet_results", {})
            .get("result", {})
        )
        new_id = result.get("rest_id", "")
        thread_ids.append(new_id)
        current_reply_to = new_id  # Next tweet replies to this one

    await s.close()

    print(json.dumps({
        "success": True,
        "thread": thread_ids,
        "count": len(thread_ids),
        "first_reply_to": reply_to,
    }))



async def cmd_cookies(ct0: str, auth_token: str):
    """Save cookies manually (from DevTools or Cookie-Editor extension)"""
    cookies_path = get_cookies_path()
    cookie_data = {"ct0": ct0, "auth_token": auth_token}

    with open(cookies_path, "w", encoding="utf-8") as f:
        json.dump(cookie_data, f, indent=2)
    print(f"Cookies saved to {cookies_path}")

    # Update auth tokens in .env file (preserve other vars)
    env_path = get_env_path()
    existing_lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

    new_lines = []
    found_ct0 = found_auth = False
    for line in existing_lines:
        stripped = line.strip()
        if stripped.startswith("X_CT0="):
            new_lines.append(f"X_CT0={ct0}\n")
            found_ct0 = True
        elif stripped.startswith("X_AUTH_TOKEN="):
            new_lines.append(f"X_AUTH_TOKEN={auth_token}\n")
            found_auth = True
        else:
            new_lines.append(line)
    if not found_ct0:
        new_lines.insert(0, f"X_CT0={ct0}\n")
    if not found_auth:
        new_lines.insert(1, f"X_AUTH_TOKEN={auth_token}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"Env file updated at {env_path}")
    print("\nTest with: python x.py test")


def cmd_config(args):
    """Show or set config values"""
    config_path = get_config_path()
    if args.set:
        key, value = args.set
        config = load_config() or {}
        config[key] = value
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Set {key} = {value}")
        return

    config = load_config()
    if not config:
        print("No config found. Run: python x.py scraper-status to auto-generate from .env")
        sys.exit(1)
    print(json.dumps(config, indent=2))


# =============================================================================
# Scraper
# =============================================================================


def github_api(endpoint, params=None):
    """Call GitHub API -- tries gh CLI (5000/hr) then urllib (60/hr)"""
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

    url = f"{GITHUB_API}{endpoint}"
    if params:
        url += f"?{urllib.parse.urlencode(params)}"

    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": SCRAPER_UA,
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


def github_lookup_x_handles(usernames, cached_users=None, limit=20):
    """Look up X/Twitter handles for GitHub users via /users/{name} API, with 24h cache"""
    if cached_users is None:
        cached_users = {}
    results = {}
    to_lookup = []

    for username in usernames:
        if username in cached_users:
            cached = cached_users[username]
            cached_time = cached.get("cached_at", "")
            if cached_time:
                try:
                    ct = datetime.fromisoformat(cached_time)
                    if ct > datetime.now(timezone.utc) - timedelta(hours=24):
                        results[username] = cached
                        continue
                except (ValueError, TypeError):
                    pass
        to_lookup.append(username)

    for username in to_lookup[:limit]:
        data = github_api(f"/users/{username}")
        if not data:
            continue
        twitter = data.get("twitter_username", "")
        results[username] = {
            "github": username,
            "twitter": twitter or "",
            "name": data.get("name", "") or "",
            "bio": (data.get("bio") or "")[:200],
            "followers": data.get("followers", 0),
            "blog": data.get("blog", "") or "",
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

    return results


def parse_feed(xml_text):
    """Parse RSS 2.0 or Atom feed XML into list of dicts"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = []

    # RSS 2.0: rss/channel/item
    for item in root.iter("item"):
        items.append({
            "title": _xml_text(item, "title"),
            "url": _xml_text(item, "link"),
            "summary": _strip_html(_xml_text(item, "description"))[:300],
            "published": _xml_text(item, "pubDate"),
        })

    if items:
        return items

    # Atom with namespace
    atom_ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{atom_ns}entry"):
        link = entry.find(f"{atom_ns}link")
        url = link.get("href", "") if link is not None else ""
        items.append({
            "title": _xml_text(entry, f"{atom_ns}title"),
            "url": url,
            "summary": _strip_html(_xml_text(entry, f"{atom_ns}summary"))[:300],
            "published": _xml_text(entry, f"{atom_ns}updated"),
        })

    if items:
        return items

    # Atom without namespace prefix
    for entry in root.iter("entry"):
        link = entry.find("link")
        url = link.get("href", "") if link is not None else ""
        items.append({
            "title": _xml_text(entry, "title"),
            "url": url,
            "summary": _strip_html(_xml_text(entry, "summary"))[:300],
            "published": _xml_text(entry, "updated"),
        })

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


def scrape_trending_repos():
    """Find trending AI/ML repos via GitHub search API"""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    searches = [
        {"q": f"topic:ai created:>{week_ago} stars:>5", "sort": "stars", "order": "desc", "per_page": 15},
        {"q": f"(free OR self-hosted OR local) topic:llm pushed:>{week_ago} stars:>50", "sort": "updated", "per_page": 10},
        {"q": f"(ollama OR vllm OR localai OR litellm OR jan) in:name stars:>100 pushed:>{month_ago}", "sort": "stars", "per_page": 10},
        {"q": "topic:ai (free-tier OR budget OR cost OR cheap) stars:>10", "sort": "stars", "order": "desc", "per_page": 10},
        {"q": f"(cli OR terminal) (ai OR llm OR gpt) created:>{month_ago} stars:>20", "sort": "stars", "per_page": 10},
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
            repos.append({
                "name": name,
                "description": (item.get("description") or "")[:200],
                "stars": item.get("stargazers_count", 0),
                "language": item.get("language", ""),
                "topics": item.get("topics", []),
                "created": item.get("created_at", ""),
                "updated": item.get("updated_at", ""),
                "url": item.get("html_url", ""),
                "owner": item.get("owner", {}).get("login", ""),
            })

    repos.sort(key=lambda r: r["stars"], reverse=True)
    return repos


def scrape_cost_issues():
    """Find GitHub issues about API costs, rate limits, billing"""
    searches = [
        {"q": '"rate limit" OR "quota exceeded" label:bug is:open language:python', "sort": "created", "order": "desc", "per_page": 10},
        {"q": '"too expensive" OR "free alternative" OR "billing" is:issue is:open', "sort": "reactions", "order": "desc", "per_page": 10},
        {"q": "\"can't afford\" OR \"student discount\" (api OR ai OR llm) is:issue", "sort": "created", "order": "desc", "per_page": 10},
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
            issues.append({
                "title": item.get("title", "")[:200],
                "repo": repo,
                "author": item.get("user", {}).get("login", ""),
                "url": url,
                "reactions": item.get("reactions", {}).get("total_count", 0),
                "created": item.get("created_at", ""),
            })

    return issues


def scrape_new_releases():
    """Find recent releases of popular free AI tools"""
    key_repos = [
        "ollama/ollama", "vllm-project/vllm", "mudler/LocalAI",
        "BerriAI/litellm", "janhq/jan", "ggml-org/llama.cpp",
        "oobabooga/text-generation-webui", "lm-sys/FastChat",
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
        releases.append({
            "repo": repo,
            "tag": rel.get("tag_name", ""),
            "name": rel.get("name", "")[:100],
            "published": published,
            "url": rel.get("html_url", ""),
        })

    return releases


def scrape_news_feeds():
    """Scrape RSS/Atom news feeds from configured sources"""
    all_items = []
    for feed_cfg in NEWS_RSS_FEEDS:
        xml_text = fetch_url(feed_cfg["url"])
        if not xml_text:
            continue
        items = parse_feed(xml_text)
        for item in items[: feed_cfg.get("max_items", 10)]:
            if not item.get("title"):
                continue
            all_items.append({
                "title": item["title"][:200],
                "summary": item.get("summary", "")[:300],
                "url": item.get("url", ""),
                "source": feed_cfg["source"],
                "category": feed_cfg["category"],
                "published": item.get("published", ""),
            })
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
        items.append({
            "title": (article.get("title") or "")[:200],
            "summary": _strip_html(article.get("content") or "")[:300],
            "url": ref_url,
            "source": "messari",
            "category": "crypto",
            "published": published,
            "tags": [t.get("name", "") for t in (article.get("tags") or [])[:5]],
        })

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
            display_url = cl["url"].replace(
                "raw.githubusercontent.com", "github.com"
            ).replace("/main/", "/blob/main/")
            items.append({
                "title": f"{cl['source'].replace('_', ' ').title()}: {heading}",
                "summary": _strip_html(body),
                "url": display_url,
                "source": cl["source"],
                "category": cl["category"],
                "published": "",
            })
    return items


def generate_x_queries(repos, issues, releases, news=None):
    """Generate X search queries from all scraped data"""
    queries = []

    # Standard high-value queries
    standard = [
        {"query": "\"can't afford\" (API OR AI OR LLM) min_faves:5 within_time:3d", "priority": "P1", "source": "standard", "context": "Direct cost complaints"},
        {"query": "\"rate limit\" (hit OR exceeded OR stuck) (openai OR anthropic OR gemini) within_time:3d", "priority": "P1", "source": "standard", "context": "Rate limit frustration"},
        {"query": "\"API bill\" (shocked OR surprised OR expensive OR crazy) min_faves:3 within_time:7d", "priority": "P1", "source": "standard", "context": "Billing shock"},
        {"query": "\"free tier\" (AI OR LLM OR API) (not enough OR limited OR upgrade) within_time:3d", "priority": "P2", "source": "standard", "context": "Free tier limitations"},
        {"query": "(student OR \"broke dev\" OR \"no budget\") (AI OR API) (expensive OR cost OR afford) within_time:7d", "priority": "P2", "source": "standard", "context": "Budget-constrained users"},
        {"query": "\"switching from\" (openai OR anthropic) (free OR local OR self-host) within_time:7d", "priority": "P3", "source": "standard", "context": "Migration signals"},
        {"query": "\"just launched\" (AI OR LLM) (free OR \"open source\") within_time:7d min_faves:5", "priority": "P4", "source": "standard", "context": "New free tool launches"},
        {"query": "hackathon (AI OR LLM) (built OR won OR demo) within_time:7d", "priority": "P5", "source": "standard", "context": "Hackathon projects needing free APIs"},
    ]
    queries.extend(standard)

    # From trending repos
    for repo in repos[:15]:
        name = repo["name"].split("/")[-1]
        topics = repo.get("topics", [])
        if any(t in topics for t in ["free", "self-hosted", "local", "budget", "inference"]):
            queries.append({
                "query": f'"{name}" (free OR cost OR rate-limit) within_time:7d',
                "priority": "P3", "source": "github_trending",
                "context": f"Users of {repo['name']} ({repo['stars']} stars)",
            })
        if repo["stars"] > 500:
            queries.append({
                "query": f'"{name}" (trying OR "just installed" OR setup) within_time:3d min_faves:3',
                "priority": "P4", "source": "github_trending",
                "context": f"New users of {repo['name']}",
            })

    # From cost issues -> find authors on X
    for issue in issues[:10]:
        author = issue.get("author", "")
        if author and len(author) > 2:
            queries.append({
                "query": f"from:{author} (AI OR API OR LLM OR cost OR rate) within_time:30d",
                "priority": "P2", "source": "github_issues",
                "context": f"GitHub user {author} posted about costs in {issue['repo']}",
            })

    # From new releases
    for rel in releases:
        repo_name = rel["repo"].split("/")[-1]
        queries.append({
            "query": f'"{repo_name}" (release OR update OR "{rel["tag"]}") within_time:3d min_faves:5',
            "priority": "P4", "source": "github_releases",
            "context": f"Release thread for {rel['repo']} {rel['tag']}",
        })

    # From news items
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
            queries.append({
                "query": query_str,
                "priority": priority,
                "source": f"news_{source}",
                "context": f"News: {title[:80]}",
            })

    return queries


def cmd_scrape():
    """Run full scrape cycle"""
    print(_bold("=== /x Skill Scraper ===") + "\n")

    print(f"{_blue('[1/7]')} Scraping trending AI repos (GitHub)...")
    repos = scrape_trending_repos()
    print(f"  Found {_cyan(str(len(repos)))} repos")

    print(f"{_blue('[2/7]')} Scraping cost-related issues (GitHub)...")
    issues = scrape_cost_issues()
    print(f"  Found {_cyan(str(len(issues)))} issues")

    print(f"{_blue('[3/7]')} Checking recent releases (GitHub)...")
    releases = scrape_new_releases()
    print(f"  Found {_cyan(str(len(releases)))} releases")

    print(f"{_blue('[4/7]')} Fetching RSS/Atom news feeds...")
    rss_news = scrape_news_feeds()
    print(f"  Found {_cyan(str(len(rss_news)))} news items from RSS")

    print(f"{_blue('[5/7]')} Fetching markdown changelogs...")
    changelog_news = scrape_markdown_changelogs()
    print(f"  Found {_cyan(str(len(changelog_news)))} changelog entries")

    print(f"{_blue('[6/7]')} Fetching Messari crypto news...")
    messari_news = scrape_messari()
    print(f"  Found {_cyan(str(len(messari_news)))} crypto articles")

    all_news = rss_news + changelog_news + messari_news

    print(f"{_blue('[7/7]')} Generating X search queries...")
    x_queries = generate_x_queries(repos, issues, releases, all_news)
    print(f"  Generated {_cyan(str(len(x_queries)))} queries")

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

    print(f"\n{_green('Feed saved:')} {feed_path}")

    _PRIORITY_COLOR = {"P1": _red, "P2": _yellow, "P3": _cyan, "P4": _blue, "P5": _dim}
    for p in ["P1", "P2", "P3", "P4", "P5"]:
        pq = [q for q in x_queries if q["priority"] == p]
        if pq:
            color = _PRIORITY_COLOR.get(p, _dim)
            print(f"\n  {color(p)} ({len(pq)} queries):")
            for q in pq[:2]:
                print(f"    {_dim(q['query'][:80])}")

    if all_news:
        print(f"\n  News ({_cyan(str(len(all_news)))} items):")
        for cat in ["ai", "coding", "crypto"]:
            cat_items = [n for n in all_news if n.get("category") == cat]
            if cat_items:
                print(f"    {cat.upper()}: {_cyan(str(len(cat_items)))} items")

    print(f"\n{_green('Ready for:')} python x.py auto --mode reply OR --mode compose")


def cmd_feed():
    """Show current feed summary"""
    feed_path = get_feed_path()
    if not feed_path.exists():
        print("No feed found. Run: python x.py scrape")
        sys.exit(1)

    with open(feed_path, "r", encoding="utf-8") as f:
        feed = json.load(f)

    updated = feed.get("last_updated", "unknown")
    stats = feed.get("stats", {})
    queries = feed.get("queries", [])
    repos = feed.get("repos", [])
    releases = feed.get("releases", [])
    news = feed.get("news", [])

    try:
        updated_dt = datetime.fromisoformat(updated)
        age_hours = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600
        fresh_fn = _green if age_hours < 12 else _red
        freshness = fresh_fn(f"{age_hours:.1f}h ago")
        if age_hours > 12:
            freshness += _red(" (STALE - run scrape)")
    except (ValueError, TypeError):
        freshness = _dim("unknown")

    print(f"{_bold('Feed updated:')} {_dim(updated)} ({freshness})")
    print(f"  Repos:    {_cyan(str(stats.get('repos_found', 0)))}")
    print(f"  Issues:   {_cyan(str(stats.get('issues_found', 0)))}")
    print(f"  Releases: {_cyan(str(stats.get('releases_found', 0)))}")
    print(f"  News:     {_cyan(str(stats.get('news_items', 0)))}")
    print(f"  Queries:  {_cyan(str(stats.get('queries_generated', 0)))}")

    if repos:
        print(f"\n{_bold('Top repos:')}")
        for r in repos[:5]:
            stars = r["stars"]
            print(f"  {r['name']:40s} {_yellow(f'{stars:>6d}')} stars  {_dim(r['language'] or '?')}")

    if releases:
        print(f"\n{_bold('Recent releases:')}")
        for r in releases:
            print(f"  {r['repo']:40s} {_green(r['tag'])}")

    if news:
        print(f"\n{_bold('News')} ({_cyan(str(len(news)))} items):")
        for cat in ["ai", "coding", "crypto"]:
            cat_items = [n for n in news if n.get("category") == cat]
            if cat_items:
                print(f"  {_yellow(cat.upper())} ({len(cat_items)}):")
                for n in cat_items[:3]:
                    title = n["title"][:70].encode("ascii", "replace").decode("ascii")
                    print(f"    {_dim(title)}")

    hints = feed.get("browse_hints", [])
    if hints:
        print(f"\n{_bold('Browse hints')} ({len(hints)} URLs for Claude to check):")
        for h in hints:
            print(f"  {_dim('[' + h['category'] + ']')} {h['url']}")

    _PRIORITY_COLOR = {"P1": _red, "P2": _yellow, "P3": _cyan, "P4": _blue, "P5": _dim}
    print(f"\n{_bold('Queries by priority:')}")
    for p in ["P1", "P2", "P3", "P4", "P5"]:
        pq = [q for q in queries if q["priority"] == p]
        if pq:
            color = _PRIORITY_COLOR.get(p, _dim)
            print(f"  {color(p)}: {len(pq)} queries")
            for q in pq[:2]:
                print(f"    {_dim(q['query'][:75])}")

    if not sys.stdout.isatty():
        print(json.dumps(feed, indent=2))


def cmd_github(args):
    """GitHub-to-X pipeline: scan GitHub, map users to X handles, generate targeted queries"""
    do_search = getattr(args, "search", False)
    json_out = getattr(args, "json", False)
    limit = getattr(args, "limit", 20)

    # Load cached github_users from feed.json
    feed_path = get_feed_path()
    cached_users = {}
    if feed_path.exists():
        try:
            with open(feed_path, encoding="utf-8") as f:
                feed_data = json.load(f)
            cached_users = feed_data.get("github_users", {})
        except (json.JSONDecodeError, OSError):
            pass

    # Phase 1: Scan GitHub
    if not json_out:
        print(_bold("Phase 1: Scanning GitHub..."))
    repos = scrape_trending_repos()
    issues = scrape_cost_issues()
    releases = scrape_new_releases()
    if not json_out:
        print(f"  {len(repos)} trending repos, {len(issues)} cost issues, {len(releases)} releases")

    # Phase 2: Collect unique usernames + track source
    usernames = set()
    user_sources = {}
    for repo in repos:
        owner = repo.get("owner", "")
        if owner and len(owner) > 1:
            usernames.add(owner)
            user_sources.setdefault(owner, []).append(f"trending:{repo['name']}")
    for issue in issues:
        author = issue.get("author", "")
        if author and len(author) > 1:
            usernames.add(author)
            user_sources.setdefault(author, []).append(f"issue:{issue['repo']}")

    if not json_out:
        print(f"\n{_bold('Phase 2: Looking up X handles')} for {len(usernames)} GitHub users...")

    # Phase 3: Look up X handles (with caching)
    users = github_lookup_x_handles(list(usernames), cached_users, limit)

    # Attach sources
    for username, info in users.items():
        info["sources"] = user_sources.get(username, info.get("sources", []))

    # Save to feed cache
    try:
        if feed_path.exists():
            with open(feed_path, encoding="utf-8") as f:
                feed_data = json.load(f)
        else:
            feed_data = {}
        feed_data["github_users"] = users
        with open(feed_path, "w", encoding="utf-8") as f:
            json.dump(feed_data, f, indent=2, ensure_ascii=False)
    except (OSError, json.JSONDecodeError):
        pass

    mapped = {k: v for k, v in users.items() if v.get("twitter")}
    unmapped = {k: v for k, v in users.items() if not v.get("twitter")}

    if not json_out:
        cached_count = len(users) - len([u for u in users if u not in cached_users])
        print(f"  Looked up: {len(users)} users ({cached_count} cached), {_green(str(len(mapped)))} with X handles")
        if mapped:
            print(f"\n{_bold('GitHub -> X Mappings:')}")
            for uname, info in sorted(mapped.items(), key=lambda x: x[1].get("followers", 0), reverse=True):
                srcs = ", ".join(info.get("sources", [])[:2])
                print(f"  {uname:25s} -> @{_cyan(info['twitter']):20s} {info.get('followers',0):>7,} followers  [{srcs}]")

    # Phase 4: Generate targeted queries
    queries = []

    # Direct from:{handle} queries for mapped users
    for username, info in mapped.items():
        handle = info["twitter"]
        queries.append({
            "query": f"from:{handle} (AI OR API OR LLM OR cost OR rate OR free) within_time:30d",
            "priority": "P2",
            "source": "github_user_direct",
            "context": f"@{username} -> X @{handle}",
            "github_user": username,
            "x_handle": handle,
        })

    # Repo context queries
    for repo in repos[:10]:
        name = repo["name"].split("/")[-1]
        queries.append({
            "query": f'"{name}" (free OR cost OR "rate limit") within_time:7d',
            "priority": "P3",
            "source": "github_repo",
            "context": f"Discussions about {repo['name']} ({repo['stars']} stars)",
        })

    # Issue context queries (skip users already covered by direct mapping)
    for issue in issues[:10]:
        author = issue.get("author", "")
        if author in mapped:
            continue
        title_terms = _extract_terms(issue.get("title", ""))
        if len(title_terms) >= 2:
            queries.append({
                "query": f'({" OR ".join(title_terms[:3])}) within_time:7d min_faves:3',
                "priority": "P2",
                "source": "github_issue_context",
                "context": f"Issue: {issue['title'][:60]}",
            })

    # Release thread queries
    for rel in releases:
        repo_name = rel["repo"].split("/")[-1]
        queries.append({
            "query": f'"{repo_name}" ("{rel["tag"]}" OR release OR update) within_time:3d min_faves:3',
            "priority": "P4",
            "source": "github_release",
            "context": f"Release {rel['repo']} {rel['tag']}",
        })

    if not json_out:
        print(f"\n{_bold('Phase 3: Generated')} {len(queries)} targeted queries")
        print(f"  Direct @user:    {sum(1 for q in queries if q['source'] == 'github_user_direct')}")
        print(f"  Repo context:    {sum(1 for q in queries if q['source'] == 'github_repo')}")
        print(f"  Issue context:   {sum(1 for q in queries if q['source'] == 'github_issue_context')}")
        print(f"  Release threads: {sum(1 for q in queries if q['source'] == 'github_release')}")

    # Phase 5: Optionally search X for targets
    targets = []
    if do_search:
        search_count = min(len(queries), limit)
        if not json_out:
            print(f"\n{_bold('Phase 4: Searching X API')} for {search_count} queries...")
        for i, q in enumerate(queries[:search_count]):
            try:
                result = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "search", q["query"], "--count", "5"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                )
                if result.returncode == 0 and result.stdout:
                    search_data = json.loads(result.stdout)
                    tweets = search_data.get("tweets", [])
                    for tw in tweets:
                        tw["source_query"] = q
                    targets.extend(tweets)
                    if not json_out:
                        total_v = sum(t.get("views", 0) for t in tweets)
                        print(f"  [{i+1}/{search_count}] {q['query'][:55]}... -> {len(tweets)} hits, {total_v:,} views")
            except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
                if not json_out:
                    print(f"  [{i+1}] {_red('Error')}: {e}")

        if not json_out and targets:
            targets.sort(key=lambda t: t.get("views", 0), reverse=True)
            print(f"\n{_bold('Top targets by reach:')}")
            for t in targets[:10]:
                print(f"  {t.get('views',0):>8,} views  @{t.get('author',''):20s} {t.get('text','')[:60]}...")

    # Final output
    if json_out:
        output = {
            "users": list(users.values()),
            "mapped_count": len(mapped),
            "unmapped_count": len(unmapped),
            "queries": queries,
            "targets": targets,
            "stats": {
                "repos_scanned": len(repos),
                "issues_scanned": len(issues),
                "releases_found": len(releases),
                "users_looked_up": len(users),
                "x_handles_found": len(mapped),
                "queries_generated": len(queries),
                "targets_found": len(targets),
            },
        }
        print(json.dumps(output, indent=2, ensure_ascii=True))
    else:
        total_reach = sum(t.get("views", 0) for t in targets)
        print(f"\n{_bold('=== Summary ===')}")
        print(f"  GitHub users:     {len(users)}")
        print(f"  X handles found:  {_green(str(len(mapped)))}")
        print(f"  Queries ready:    {len(queries)}")
        if targets:
            print(f"  Targets found:    {len(targets)}")
            print(f"  Combined reach:   {total_reach:,} views")
        print(f"\n  Cache: {feed_path}")
        if not do_search:
            print(f"\n  {_dim('Tip: --search  to also search X for each query')}")
            print(f"  {_dim('     --json    for machine-readable output')}")


# =============================================================================
# History Tracking
# =============================================================================


def load_history():
    """Load history.json, initialize if not exists"""
    history_path = get_history_path()
    if not history_path.exists():
        return {"replies": [], "daily_counts": {}}
    with open(history_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(data):
    """Save history.json atomically"""
    history_path = get_history_path()
    temp_file = history_path.with_suffix(".json.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    temp_file.replace(history_path)


def get_url_hash(url):
    """Generate SHA256 hash of normalized target URL for dedup"""
    # Normalize: strip query params, trailing slashes, lowercase
    parsed = urllib.parse.urlparse(url)
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}".lower()
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()


def cmd_log(args):
    """Log a posted reply to history"""
    history = load_history()
    url_hash = get_url_hash(args.target_url)
    today = datetime.now().strftime("%Y-%m-%d")

    reply_entry = {
        "id": url_hash,
        "target_url": args.target_url,
        "author": args.author,
        "reply_text": args.reply_text,
        "topic": args.topic,
        "query_used": args.query,
        "estimated_reach": int(args.reach),
        "timestamp": datetime.now().isoformat() + "Z",
    }

    history["replies"].append(reply_entry)
    history["daily_counts"][today] = history["daily_counts"].get(today, 0) + 1
    save_history(history)
def cmd_check(args):
    """Check if target URL already replied to (exit 0=ok, 1=already replied)"""
    history = load_history()
    url_hash = get_url_hash(args.target_url)

    # Extract author from URL for secondary check (x.com/{author}/status/...)
    url_author = ""
    parts = urllib.parse.urlparse(args.target_url).path.strip("/").split("/")
    if len(parts) >= 1:
        url_author = parts[0].lower()

    for reply in history["replies"]:
        # Primary: hash match (handles normalized URLs)
        if reply["id"] == url_hash:
            print("Already replied (URL match)")
            sys.exit(1)
        # Secondary: same author + same tweet ID in URL
        stored_url = reply.get("target_url", "")
        if stored_url:
            stored_parts = urllib.parse.urlparse(stored_url).path.strip("/").split("/")
            if len(stored_parts) >= 3 and len(parts) >= 3:
                # Compare /author/status/id — case-insensitive author, exact ID
                if stored_parts[0].lower() == url_author and stored_parts[2] == parts[2]:
                    print("Already replied (author+ID match)")
                    sys.exit(1)
        # Tertiary: same author handle in last 24h (avoid spamming same person)
        reply_author = reply.get("author", "").lstrip("@").lower()
        if url_author and reply_author == url_author:
            try:
                ts = datetime.fromisoformat(reply["timestamp"].rstrip("Z"))
                if ts > datetime.now() - timedelta(hours=24):
                    print(f"Already replied to @{url_author} in last 24h")
                    sys.exit(1)
            except (ValueError, KeyError):
                pass
    sys.exit(0)


def cmd_history(args):
    """Show posting history with optional filters"""
    history = load_history()
    replies = history["replies"]

    if args.days:
        cutoff = datetime.now() - timedelta(days=args.days)
        replies = [
            r for r in replies
            if datetime.fromisoformat(r["timestamp"].rstrip("Z")) >= cutoff
        ]

    if args.topic:
        replies = [r for r in replies if args.topic.lower() in r["topic"].lower()]

    if not replies:
        print("No replies found matching filters")
        return

    header = f"{'Date':<12} {'Author':<20} {'Topic':<25} {'Reach':<8}"
    print(f"\n{_bold(header)}")
    print(_dim("-" * 65))

    for reply in sorted(replies, key=lambda x: x["timestamp"], reverse=True):
        date = f"{reply['timestamp'][:10]:<12}"
        author = f"{reply['author'][:18]:<20}"
        topic = f"{reply['topic'][:23]:<25}"
        reach = f"{reply['estimated_reach']:<8}"
        print(f"{_dim(date)} {_cyan(author)} {topic} {_yellow(reach)}")

def cmd_status_history():
    """Show posting stats (no hard limits)"""
    history = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = history["daily_counts"].get(today, 0)
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    weekly_count = sum(
        count for date, count in history["daily_counts"].items()
        if date >= week_ago
    )

    total_reach = sum(r["estimated_reach"] for r in history["replies"])

    week_ago_dt = datetime.now() - timedelta(days=7)
    recent_reach = sum(
        r["estimated_reach"] for r in history["replies"]
        if datetime.fromisoformat(r["timestamp"].rstrip("Z")) >= week_ago_dt
    )

    header = f"{'Metric':<20} {'Count':<10}"
    print(f"\n{_bold(header)}")
    print(_dim("-" * 35))
    print(f"{'Today':<20} {_cyan(f'{today_count:<10}')}")
    print(f"{'Last 7 days':<20} {_cyan(f'{weekly_count:<10}')}")
    total_replies = len(history["replies"])
    print(f"{'Total replies':<20} {_cyan(f'{total_replies:<10}')}")
    print(f"{'Total reach':<20} {_cyan(f'{total_reach:<10,}')}")
    print(f"{'Recent reach (7d)':<20} {_cyan(f'{recent_reach:<10,}')}")


def cmd_rate_check():
    """Show today's post count (no hard limits enforced)"""
    history = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = history["daily_counts"].get(today, 0)
    print(_green(f"Rate OK: {today_count} replies today"))
    sys.exit(0)


# =============================================================================
# Auto-Poster
# =============================================================================


def load_feed_data():
    """Load feed.json"""
    feed_path = get_feed_path()
    if not feed_path.exists():
        return None
    with open(feed_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_reply_prompt(config, feed, max_posts=3, dry_run=False):
    """Build prompt for reply mode -- find targets and post replies"""
    share_url = config.get("share_url", "")
    project_name = config.get("project_name", "")
    project_desc = config.get("project_desc", "")
    script_path = Path(__file__).resolve()

    queries = feed.get("queries", [])
    p1 = [q for q in queries if q["priority"] == "P1"]
    p2 = [q for q in queries if q["priority"] == "P2"]
    p3 = [q for q in queries if q["priority"] == "P3"]
    top_queries = (p1 + p2 + p3)[:12]
    query_list = "\n".join(
        f"  {i+1}. [{q['priority']}] {q['query']}  -- {q['context']}"
        for i, q in enumerate(top_queries)
    )

    releases = feed.get("releases", [])
    release_ctx = ""
    if releases:
        release_ctx = "Recent releases (good for finding discussion threads):\n"
        for r in releases[:3]:
            release_ctx += f"  - {r['repo']} {r['tag']}\n"

    news = feed.get("news", [])
    news_ctx = ""
    if news:
        news_ctx = "Recent news items (use for finding related conversations):\n"
        for n in news[:5]:
            news_ctx += f"  - [{n.get('category', 'general')}] {n['title']}\n"

    action = "DRY RUN -- research only, do NOT post any replies" if dry_run else f"Post up to {max_posts} replies"
    skill_path = get_skill_md_path()

    return f"""You are running the /x skill in AUTO MODE (headless, non-interactive).

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
2. Check rate limits: python {script_path} rate-check
3. For each query above (P1 first):
   a. Navigate to X search: https://x.com/search?q={{encoded_query}}&f=top
   b. Use read_page to find reply-worthy posts (engagement > 0)
   c. Check dedup: python {script_path} check "{{target_url}}"
   d. Compose a UNIQUE reply following tone guidelines (casual, short, reference their pain point)
   e. ALWAYS include {share_url} in the reply
   f. Post via: echo '{{reply_text}}' | python {script_path} post "{{tweet_id}}" --stdin
      CRITICAL: ALWAYS use --stdin with echo pipe to avoid shell expansion of $ signs.
      NEVER pass reply text as a positional argument — $ signs get mangled by the shell.
      Use single quotes around the echo text to prevent variable expansion.
   g. If X API client fails (Cloudflare 403), use Chrome MCP to post manually
   h. Log: python {script_path} log "{{url}}" "{{author}}" "{{text}}" "auto" "{{query}}" "{{reach}}"
4. Stop after {max_posts} successful posts
5. Report: how many posted, total estimated reach, any errors

TONE PROFILES (rotate between these -- never use same twice in a row):

1. THE STEAL (40%): Sound like sharing an insider secret, too-good-to-be-true energy
   "wait you're paying for API calls? someone pooled free gmails into 300rpm on gemini flash. zero cost"

2. THE SARCASTIC (30%): Dry humor about AI pricing. Wry, never mean.
   "openai charging $20/month for rate limits is peak comedy when this does 300rpm for free"

3. THE EMPATHETIC (30%): Genuine, warm, you've been there.
   "been there with the rate limits. this pools free gmails for 300rpm on gemini flash - saved my project"

RULES:
- Rotate profiles: steal → sarcastic → empathetic → steal → ...
- Reference their specific pain point
- Keep under 280 chars, no hashtags, no "Hey!"
- Every reply must be structurally different
- Sound like a discovery, not an ad
- NUMBER FORMATTING: Use period for thousands separator, comma for decimals (European format)
  Examples: $1.256/year (not $1,256), $0.004 stays as-is (decimal), 300 RPM (no separator needed)
  NEVER write bare dollar amounts without the $ sign. Double-check all numbers before posting.
- SHELL SAFETY: Always use echo '...' | python x.py post ID --stdin to avoid $ expansion

POST TRACKING:
- Max {max_posts} posts this run
- Check count via rate-check between batches
"""


def build_compose_prompt(config, feed, max_posts=3, dry_run=False):
    """Build prompt for compose mode -- create original tweet from news + distribute"""
    share_url = config.get("share_url", "")
    handle = config.get("handle", "")
    project_name = config.get("project_name", "")
    project_desc = config.get("project_desc", "")
    script_path = Path(__file__).resolve()

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

    browse_hints = feed.get("browse_hints", [])
    hints_list = ""
    if browse_hints:
        hints_list = "BROWSE HINTS (check these URLs for fresh content via Chrome MCP):\n"
        for h in browse_hints[:5]:
            hints_list += f"  - {h['url']}  ({h.get('source', 'unknown')})\n"

    queries = feed.get("queries", [])
    p1 = [q for q in queries if q["priority"] == "P1"]
    p2 = [q for q in queries if q["priority"] == "P2"]
    top_queries = (p1 + p2)[:8]
    query_list = "\n".join(
        f"  {i+1}. [{q['priority']}] {q['query']}  -- {q['context']}"
        for i, q in enumerate(top_queries)
    )

    action = "DRY RUN -- draft only, do NOT post anything" if dry_run else f"Compose 1 original tweet + distribute up to {max_posts} replies"
    skill_path = get_skill_md_path()

    return f"""You are running the /x skill in AUTO MODE (headless, non-interactive).

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
for the {handle} profile.

NEWS ITEMS (pick 1 to tweet about):
{news_list}
{hints_list}

COMPOSE RULES:
- Pick the item most relevant to {project_name}'s audience
- Write 1-3 short sentences, casual tone, under 280 chars
- Add your own opinion or insight (not just headline rewrite)
- Include a relevant link if the news item has one
- Post to YOUR profile via: python {script_path} tweet "{{tweet_text}}"
  OR via Chrome MCP: navigate to x.com, click compose, type, post
- Save the URL of your new tweet for Phase 2

===== PHASE 2: DISTRIBUTE (reply with your tweet URL) =====

SEARCH QUERIES (for finding related conversations):
{query_list}

DISTRIBUTE INSTRUCTIONS:
1. Get the URL of the tweet you just posted
2. For each query above (P1 first):
   a. Navigate to X search: https://x.com/search?q={{encoded_query}}&f=top
   b. Find posts discussing the same topic as your tweet
   c. Check dedup: python {script_path} check "{{target_url}}"
   d. Compose a short reply referencing their discussion + link to your tweet
   e. Post via: python {script_path} post "{{tweet_id}}" "{{reply_text}}"
   f. Log: python {script_path} log "{{url}}" "{{author}}" "{{text}}" "compose-distribute" "{{query}}" "{{reach}}"
3. Stop after {max_posts} successful distribution replies

TONE PROFILES (rotate between these -- never use same twice in a row):

1. THE STEAL (40%): Insider secret, too-good-to-be-true energy
   "genuinely wild that this exists - free gemini flash at 300rpm while everyone pays per token"

2. THE SARCASTIC (30%): Dry humor about AI pricing
   "love how the AI industry convinced everyone paying per token is normal. anyway here's 300rpm for $0"

3. THE EMPATHETIC (30%): Genuine, warm
   "been there with the rate limits. this pools free gmails for 300rpm on gemini flash"

RULES:
- Rotate profiles: steal → sarcastic → empathetic → steal → ...
- Reference their specific topic
- Keep under 280 chars, no hashtags, no "Hey!"
- Sound like a discovery, not an ad

POST TRACKING:
- Max {max_posts} distribution replies this run
- Check count via rate-check between batches
"""


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


def cmd_auto(args):
    """Run the full auto-post pipeline"""
    config = load_config()
    model_id = MODELS.get(args.model, MODELS["sonnet"])

    if args.model == "opus":
        print("WARNING: Using Opus for auto mode burns weekly quota. Consider --model sonnet")

    # Step 1: Run scraper (direct call, no subprocess)
    print("[1/2] Running scraper (GitHub + RSS + news)...")
    cmd_scrape()

    # Step 2: Load feed
    feed = load_feed_data()
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
        claude_bin, "-p", prompt,
        "--model", model_id,
        "--max-turns", str(args.max_turns),
    ]

    if args.budget:
        cmd.extend(["--max-budget-usd", str(args.budget)])

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

    try:
        result = subprocess.run(cmd, text=True, timeout=600)
        if result.returncode != 0:
            print(f"\nClaude exited with code {result.returncode}")
    except subprocess.TimeoutExpired:
        print("\nTimeout: Claude took longer than 10 minutes.")
    except KeyboardInterrupt:
        print("\nAborted by user.")


# =============================================================================
# Scheduler Management
# =============================================================================


def cmd_scraper_install(hours=6):
    """Install Windows Task Scheduler for scraper"""
    script_path = Path(__file__).resolve()
    python_path = sys.executable

    if sys.platform == "win32":
        # schtasks HOURLY max is 23; use DAILY for 24h+
        if hours >= 24:
            sc_type, sc_mod = "DAILY", str(hours // 24)
        else:
            sc_type, sc_mod = "HOURLY", str(hours)
        cmd = [
            "schtasks", "/create", "/tn", SCRAPER_TASK_NAME,
            "/tr", f'"{python_path}" "{script_path}" scrape',
            "/sc", sc_type, "/mo", sc_mod, "/f",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(_green(f"Scraper scheduler installed: runs every {hours}h"))
                print(f"  Task: {_dim(SCRAPER_TASK_NAME)}")
            else:
                print(_red(f"Failed: {result.stderr.strip()}"))
                print(_yellow("Try running as administrator."))
        except FileNotFoundError:
            print("schtasks not found.")
    else:
        cron = f"0 */{hours} * * * {python_path} {script_path} scrape >> /tmp/x-scraper.log 2>&1"
        print(f"Add to crontab (crontab -e):\n  {cron}")


def cmd_scraper_uninstall():
    """Remove scraper scheduler"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["schtasks", "/delete", "/tn", SCRAPER_TASK_NAME, "/f"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(_green(f"Scraper scheduler removed: {SCRAPER_TASK_NAME}"))
            else:
                print(_yellow(f"Not found: {result.stderr.strip()}"))
        except FileNotFoundError:
            print(_yellow("schtasks not found."))
    else:
        print(f"Remove from crontab: {_dim(f'crontab -e, delete the {SCRAPER_TASK_NAME} line')}")


def cmd_scraper_status():
    """Show scraper scheduler + feed status"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", SCRAPER_TASK_NAME, "/fo", "TABLE"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(f"Scraper scheduler: {_green('INSTALLED')}")
                for line in result.stdout.strip().split("\n"):
                    print(f"  {_dim(line)}")
            else:
                print(f"Scraper scheduler: {_red('NOT INSTALLED')}")
                print(f"  Install: {_dim('python x.py scraper-install')}")
        except FileNotFoundError:
            print(f"Scraper scheduler: {_yellow('schtasks not available')}")

    feed_path = get_feed_path()
    if feed_path.exists():
        with open(feed_path, "r", encoding="utf-8") as f:
            feed = json.load(f)
        updated = feed.get("last_updated", "unknown")
        stats = feed.get("stats", {})
        try:
            updated_dt = datetime.fromisoformat(updated)
            age_hours = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600
            fresh_fn = _green if age_hours < 12 else _red
            status = "FRESH" if age_hours < 12 else "STALE"
            print(f"\nFeed: {fresh_fn(status)} ({age_hours:.1f}h old)")
        except (ValueError, TypeError):
            print(f"\nFeed: {_dim('exists (age unknown)')}")
        print(f"  Queries: {_cyan(str(stats.get('queries_generated', 0)))}")
        print(f"  Repos:   {_cyan(str(stats.get('repos_found', 0)))}")
        print(f"  News:    {_cyan(str(stats.get('news_items', 0)))}")
    else:
        print(f"\nFeed: {_red('MISSING')}")
        print(f"  Run: {_dim('python x.py scrape')}")


def cmd_poster_install(hours=12):
    """Install auto-poster scheduler"""
    script_path = Path(__file__).resolve()
    python_path = sys.executable

    if sys.platform == "win32":
        if hours >= 24:
            sc_type, sc_mod = "DAILY", str(hours // 24)
        else:
            sc_type, sc_mod = "HOURLY", str(hours)
        cmd = [
            "schtasks", "/create", "/tn", POSTER_TASK_NAME,
            "/tr", f'"{python_path}" "{script_path}" auto --posts 5 --model sonnet --budget 1.00',
            "/sc", sc_type, "/mo", sc_mod, "/f",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(_green(f"Auto-poster installed: runs every {hours}h"))
                print(f"  Task:   {_dim(POSTER_TASK_NAME)}")
                print(f"  Model:  {_cyan('Sonnet')} {_dim('(budget-safe)')}")
                print(f"  Posts:  {_cyan('5')} per run, {_yellow('$1.00')} budget cap")
            else:
                print(_red(f"Failed: {result.stderr.strip()}"))
        except FileNotFoundError:
            print(_yellow("schtasks not found."))
    else:
        cron = f"0 */{hours} * * * {python_path} {script_path} auto --posts 5 --model sonnet --budget 1.00 >> /tmp/x-autopost.log 2>&1"
        print(f"Add to crontab (crontab -e):\n  {_dim(cron)}")


def cmd_poster_uninstall():
    """Remove auto-poster scheduler"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["schtasks", "/delete", "/tn", POSTER_TASK_NAME, "/f"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(_green(f"Auto-poster removed: {POSTER_TASK_NAME}"))
            else:
                print(_yellow(f"Not found: {result.stderr.strip()}"))
        except FileNotFoundError:
            print(_yellow("schtasks not found."))


def cmd_poster_status():
    """Show auto-poster status"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", POSTER_TASK_NAME, "/fo", "TABLE"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(f"Auto-poster: {_green('INSTALLED')}")
                for line in result.stdout.strip().split("\n"):
                    print(f"  {_dim(line)}")
            else:
                print(f"Auto-poster: {_red('NOT INSTALLED')}")
        except FileNotFoundError:
            print(f"Auto-poster: {_yellow('schtasks not available')}")

    feed = load_feed_data()
    if feed:
        stats = feed.get("stats", {})
        print(f"\nFeed: {_cyan(str(stats.get('queries_generated', 0)))} queries, {_cyan(str(stats.get('news_items', 0)))} news items")
        updated = feed.get("last_updated", "unknown")
        try:
            updated_dt = datetime.fromisoformat(updated)
            age_hours = (datetime.now(timezone.utc) - updated_dt).total_seconds() / 3600
            fresh_fn = _green if age_hours < 12 else _red
            print(f"  Updated: {_dim(updated)} ({fresh_fn(f'{age_hours:.1f}h ago')})")
        except (ValueError, TypeError):
            print(f"  Updated: {_dim(updated)}")

    # Compact posting summary (not the full table — use `status` for that)
    history = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = history["daily_counts"].get(today, 0)
    print(f"\nToday: {_green(str(today_count))} posts  |  Total: {_cyan(str(len(history['replies'])))} replies")


# =============================================================================
# Main Entry Point
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Unified X skill -- API, scraping, history, auto-posting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python x.py test                    # Verify X API auth
  python x.py search "AI tools"       # Search tweets
  python x.py scrape                  # Scrape all sources -> feed.json
  python x.py auto --mode compose     # Auto-post in compose mode
  python x.py status                  # Show posting stats
  python x.py rate-check              # Check rate limits
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # --- X API commands ---
    test_p = subparsers.add_parser("test", help="Test X API authentication")
    test_p.add_argument("--verbose", "-v", action="store_true", help="Run extended auth tests")

    cookies_p = subparsers.add_parser("cookies", help="Set cookies manually")
    cookies_p.add_argument("ct0", help="ct0 cookie value")
    cookies_p.add_argument("auth_token", help="auth_token cookie value")

    search_p = subparsers.add_parser("search", help="Search tweets (JSON output)")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--count", type=int, default=20, help="Max results (default: 20)")
    search_p.add_argument("--min-engagement", type=int, default=0, help="Minimum engagement score filter (default: 0)")

    post_p = subparsers.add_parser("post", help="Post reply to a tweet")
    post_p.add_argument("tweet_id", help="Tweet ID to reply to")
    post_p.add_argument("text", nargs="?", default=None, help="Reply text (or use --stdin)")
    post_p.add_argument("--stdin", action="store_true", help="Read reply text from stdin (avoids shell expansion of $ signs)")
    post_p.add_argument("--allow-original", action="store_true", help="Override profile wall protection (manual use only)")

    quote_p = subparsers.add_parser("quote", help="Create quote tweet with commentary (posted as reply)")
    quote_p.add_argument("tweet_id", help="Tweet ID to quote")
    quote_p.add_argument("reply_to", help="Tweet ID to reply to (REQUIRED)")
    quote_p.add_argument("text", nargs="?", default=None, help="Commentary text (or use --stdin)")
    quote_p.add_argument("--stdin", action="store_true", help="Read commentary from stdin")
    quote_p.add_argument("--allow-original", action="store_true", help="Override profile wall protection (manual use only)")

    analytics_p = subparsers.add_parser("analytics", help="Show engagement metrics for a tweet")
    analytics_p.add_argument("tweet_id", help="Tweet ID to analyze")

    thread_p = subparsers.add_parser("thread", help="Post a thread of replies")
    thread_p.add_argument("reply_to", help="First tweet ID to reply to")
    thread_p.add_argument("texts", nargs="+", help="Reply texts (each becomes a tweet in thread)")
    thread_p.add_argument("--allow-original", action="store_true", help="Override profile wall protection (manual use only)")

    tweet_p = subparsers.add_parser("tweet", help="Post original tweet")
    tweet_p.add_argument("text", help="Tweet text")

    delete_p = subparsers.add_parser("delete", help="Delete a tweet")
    delete_p.add_argument("tweet_id", help="Tweet ID to delete")

    config_p = subparsers.add_parser("config", help="Show or set config values")
    config_p.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set a config key")

    # --- Scraper commands ---
    subparsers.add_parser("scrape", help="Full scrape -> feed.json")
    subparsers.add_parser("feed", help="Show current feed summary")

    # --- GitHub-to-X pipeline ---
    github_p = subparsers.add_parser("github", help="GitHub-to-X: scan repos/issues, map users to X handles, generate queries")
    github_p.add_argument("--search", action="store_true", help="Also search X API for each generated query")
    github_p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    github_p.add_argument("--limit", type=int, default=20, help="Max users to look up / queries to search (default: 20)")

    # --- History commands ---
    log_p = subparsers.add_parser("log", help="Log a posted reply")
    log_p.add_argument("target_url", help="Target post URL")
    log_p.add_argument("author", help="Target post author")
    log_p.add_argument("reply_text", help="Reply text posted")
    log_p.add_argument("topic", help="Topic/theme")
    log_p.add_argument("query", help="Search query used")
    log_p.add_argument("reach", help="Estimated reach")

    check_p = subparsers.add_parser("check", help="Check if already replied to URL")
    check_p.add_argument("target_url", help="Target post URL")

    history_p = subparsers.add_parser("history", help="Show posting history")
    history_p.add_argument("--days", type=int, help="Filter by days ago")
    history_p.add_argument("--topic", help="Filter by topic")

    subparsers.add_parser("status", help="Show posting counts and reach")
    subparsers.add_parser("rate-check", help="Check rate limit status")

    # --- Auto-poster command ---
    auto_p = subparsers.add_parser("auto", help="Run headless auto-post pipeline")
    auto_p.add_argument("--posts", type=int, default=3, help="Max posts per run (default: 3)")
    auto_p.add_argument("--mode", choices=["reply", "compose"], default="reply", help="Mode (default: reply)")
    auto_p.add_argument("--model", choices=["sonnet", "haiku", "opus"], default="sonnet", help="Model (default: sonnet)")
    auto_p.add_argument("--budget", type=float, default=1.00, help="Max USD per run (default: 1.00)")
    auto_p.add_argument("--max-turns", type=int, default=30, help="Max Claude turns (default: 30)")
    auto_p.add_argument("--dry-run", action="store_true", help="Research only, no posting")

    # --- Scheduler commands ---
    si_p = subparsers.add_parser("scraper-install", help="Install scraper scheduler")
    si_p.add_argument("hours", nargs="?", type=int, default=6, help="Interval in hours (default: 6)")
    subparsers.add_parser("scraper-uninstall", help="Remove scraper scheduler")
    subparsers.add_parser("scraper-status", help="Show scraper scheduler status")

    pi_p = subparsers.add_parser("poster-install", help="Install auto-poster scheduler")
    pi_p.add_argument("hours", nargs="?", type=int, default=12, help="Interval in hours (default: 12)")
    subparsers.add_parser("poster-uninstall", help="Remove auto-poster scheduler")
    subparsers.add_parser("poster-status", help="Show auto-poster scheduler status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch
    cmd = args.command

    # X API commands (async)
    if cmd == "test":
        asyncio.run(cmd_test(verbose=args.verbose))
    elif cmd == "cookies":
        asyncio.run(cmd_cookies(args.ct0, args.auth_token))
    elif cmd == "search":
        asyncio.run(cmd_search(args.query, args.count, args.min_engagement))
    elif cmd == "post":
        text = args.text
        if args.stdin or text is None:
            text = sys.stdin.read().strip()
        if not text:
            print(_red("ERROR: No reply text provided (use positional arg or --stdin)"))
            sys.exit(2)
        asyncio.run(cmd_post(args.tweet_id, text, args.allow_original))
    elif cmd == "quote":
        text = args.text
        if args.stdin or text is None:
            text = sys.stdin.read().strip()
        if not text:
            print(_red("ERROR: No commentary text provided (use positional arg or --stdin)"))
            sys.exit(2)
        asyncio.run(cmd_quote(args.tweet_id, text, args.reply_to, args.allow_original))
    elif cmd == "analytics":
        asyncio.run(cmd_analytics(args.tweet_id))
    elif cmd == "thread":
        asyncio.run(cmd_thread(args.reply_to, args.texts, args.allow_original))
    elif cmd == "tweet":
        asyncio.run(cmd_tweet(args.text))
    elif cmd == "delete":
        asyncio.run(cmd_delete(args.tweet_id))
    elif cmd == "config":
        cmd_config(args)

    # Scraper commands
    elif cmd == "scrape":
        cmd_scrape()
    elif cmd == "feed":
        cmd_feed()
    elif cmd == "github":
        cmd_github(args)

    # History commands
    elif cmd == "log":
        cmd_log(args)
    elif cmd == "check":
        cmd_check(args)
    elif cmd == "history":
        cmd_history(args)
    elif cmd == "status":
        cmd_status_history()
    elif cmd == "rate-check":
        cmd_rate_check()

    # Auto-poster
    elif cmd == "auto":
        cmd_auto(args)

    # Schedulers
    elif cmd == "scraper-install":
        cmd_scraper_install(args.hours)
    elif cmd == "scraper-uninstall":
        cmd_scraper_uninstall()
    elif cmd == "scraper-status":
        cmd_scraper_status()
    elif cmd == "poster-install":
        cmd_poster_install(args.hours)
    elif cmd == "poster-uninstall":
        cmd_poster_uninstall()
    elif cmd == "poster-status":
        cmd_poster_status()


if __name__ == "__main__":
    main()
