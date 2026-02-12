#!/usr/bin/env python3
"""
X API client for /x skill -- fast API-based X/Twitter posting
Uses curl_cffi (Chrome TLS fingerprint) + XClientTransaction (signed headers)
Bypasses Cloudflare + X transaction ID requirements.

Usage:
  python x_client.py test               # Verify auth works
  python x_client.py search "query"     # Search tweets, return JSON
  python x_client.py post TWEET_ID TEXT # Post reply to tweet
  python x_client.py tweet TEXT         # Post original tweet (compose mode)
  python x_client.py cookies CT0 AUTH   # Set cookies manually (no login needed)
"""

import argparse
import asyncio
import json
import re
import sys
import urllib.parse
from pathlib import Path

try:
    from curl_cffi.requests import AsyncSession
except ImportError:
    print("ERROR: curl_cffi not installed. Run: pip install curl_cffi")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")
    sys.exit(1)

try:
    from x_client_transaction import ClientTransaction
except ImportError:
    print("ERROR: x-client-transaction-id not installed. Run: pip install x-client-transaction-id")
    sys.exit(1)

# X's public bearer token (same for all clients)
BEARER = 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
ON_DEMAND_RE = re.compile(r"""['|"]{1}ondemand\.s['|"]{1}:\s*['|"]{1}([\w]*)['|"]{1}""")

# Feature flags required by X GraphQL endpoints
# Captured from live browser request (2026-02-12) — must match EXACTLY
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
    # Additional flags required by CreateTweet (not needed for search but harmless)
    "tweetypie_unmention_optimization_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
}


def get_data_dir():
    """Get path to skills/x/data/ directory"""
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def get_cookies_path():
    return get_data_dir() / "cookies.json"


def get_env_path():
    return Path(__file__).parent.parent / ".env"


def get_config_path():
    return get_data_dir() / "config.json"


def load_config():
    config_path = get_config_path()
    if not config_path.exists():
        return None
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def init_session():
    """Initialize curl_cffi session with cookies + transaction ID generator.
    Returns (session, transaction_generator, csrf_token) or raises on failure.
    """
    cookies_path = get_cookies_path()
    if not cookies_path.exists():
        print("ERROR: No cookies found. Run 'cookies' command first.", file=sys.stderr)
        sys.exit(1)

    with open(cookies_path) as f:
        cd = json.load(f)

    if "ct0" not in cd or "auth_token" not in cd:
        print("ERROR: cookies.json must have ct0 and auth_token", file=sys.stderr)
        sys.exit(1)

    s = AsyncSession(impersonate='chrome131')
    s.cookies.set('ct0', cd['ct0'], domain='.x.com')
    s.cookies.set('auth_token', cd['auth_token'], domain='.x.com')

    # Fetch homepage (sets __cf_bm and other Cloudflare cookies)
    home_r = await s.get('https://x.com', headers={'user-agent': UA})
    if home_r.status_code != 200:
        print(f"ERROR: Homepage returned {home_r.status_code}", file=sys.stderr)
        sys.exit(1)

    home_soup = BeautifulSoup(home_r.text, 'html.parser')

    # Find ondemand.s JS bundle hash
    hashes = ON_DEMAND_RE.findall(home_r.text)
    if not hashes:
        print("ERROR: Could not find ondemand.s hash in homepage", file=sys.stderr)
        sys.exit(1)

    ondemand_url = f'https://abs.twimg.com/responsive-web/client-web/ondemand.s.{hashes[0]}a.js'
    ondemand_r = await s.get(ondemand_url, headers={'user-agent': UA})

    ct = ClientTransaction(home_soup, ondemand_r.text)
    return s, ct, cd['ct0']


def build_headers(ct, csrf, method, path):
    """Build full X API headers with transaction ID"""
    tx_id = ct.generate_transaction_id(method=method, path=path)
    return {
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9',
        'authorization': BEARER,
        'content-type': 'application/json',
        'referer': 'https://x.com/',
        'sec-ch-ua': '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        'sec-ch-ua-mobile': '?0',
        'sec-ch-ua-platform': '"Windows"',
        'sec-fetch-dest': 'empty',
        'sec-fetch-mode': 'cors',
        'sec-fetch-site': 'same-origin',
        'user-agent': UA,
        'x-client-transaction-id': tx_id,
        'x-csrf-token': csrf,
        'x-twitter-active-user': 'yes',
        'x-twitter-auth-type': 'OAuth2Session',
        'x-twitter-client-language': 'en',
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def cmd_test():
    """Verify auth works by fetching current user info"""
    s, ct, csrf = await init_session()

    path = '/i/api/1.1/account/settings.json'
    headers = build_headers(ct, csrf, 'GET', path)
    r = await s.get(f'https://x.com{path}', headers=headers)

    if r.status_code == 200:
        data = r.json()
        print(f"Authenticated as: @{data.get('screen_name', '?')}")
        print("Auth OK!")
    else:
        print(f"ERROR: Auth test failed (status {r.status_code})")
        print(f"Body: {r.text[:300]}")
        sys.exit(1)

    await s.close()


async def cmd_search(query: str, count: int = 20):
    """Search tweets and return JSON results"""
    s, ct, csrf = await init_session()

    # Build SearchTimeline GraphQL request
    variables = {
        "rawQuery": query,
        "count": count,
        "querySource": "typed_query",
        "product": "Top",
        "withGrokTranslatedBio": False,
    }
    params = urllib.parse.urlencode({
        'variables': json.dumps(variables, separators=(',', ':')),
        'features': json.dumps(GRAPHQL_FEATURES, separators=(',', ':')),
    })

    # Use the SearchTimeline query ID (may need updating if X rotates it)
    path = '/i/api/graphql/cGK-Qeg1XJc2sZ6kgQw_Iw/SearchTimeline'
    headers = build_headers(ct, csrf, 'GET', path)
    r = await s.get(f'https://x.com{path}?{params}', headers=headers)

    if r.status_code != 200:
        # Try alternate search endpoint
        path2 = '/i/api/2/search/adaptive.json'
        params2 = urllib.parse.urlencode({
            'q': query,
            'result_filter': 'top',
            'count': count,
            'query_source': 'typed_query',
            'tweet_search_mode': 'live',
            'include_entities': 1,
        })
        headers2 = build_headers(ct, csrf, 'GET', path2)
        r = await s.get(f'https://x.com{path2}?{params2}', headers=headers2)

    if r.status_code != 200:
        print(json.dumps({"error": f"Search failed: status {r.status_code}", "tweets": []}))
        sys.exit(1)

    # Parse GraphQL search results
    results = []
    try:
        data = r.json()
        # Navigate the GraphQL response tree
        instructions = (data.get('data', {})
                       .get('search_by_raw_query', {})
                       .get('search_timeline', {})
                       .get('timeline', {})
                       .get('instructions', []))

        for inst in instructions:
            entries = inst.get('entries', [])
            for entry in entries:
                content = entry.get('content', {})
                item = content.get('itemContent', {})
                if not item:
                    # Could be in items array (conversations)
                    items = content.get('items', [])
                    for sub in items:
                        item = sub.get('item', {}).get('itemContent', {})
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

    print(json.dumps({"tweets": results, "count": len(results)}, indent=2))
    await s.close()


def _parse_tweet_result(item_content):
    """Extract tweet data from GraphQL itemContent"""
    result = item_content.get('tweet_results', {}).get('result', {})
    if not result:
        return None

    # Handle __typename: TweetWithVisibilityResults
    if result.get('__typename') == 'TweetWithVisibilityResults':
        result = result.get('tweet', {})

    legacy = result.get('legacy', {})
    user_result = result.get('core', {}).get('user_results', {}).get('result', {})
    # X moved user data: try .core first (new), then .legacy (old fallback)
    user_core = user_result.get('core', {})
    user_legacy = user_result.get('legacy', {})
    user_data = user_core if user_core.get('screen_name') else user_legacy

    if not legacy or not user_data:
        return None

    screen_name = user_data.get('screen_name', 'unknown')
    tweet_id = legacy.get('id_str', result.get('rest_id', ''))
    views = result.get('views', {}).get('count', '0')

    return {
        "id": tweet_id,
        "text": legacy.get('full_text', ''),
        "author": screen_name,
        "author_name": user_data.get('name', 'unknown'),
        "likes": legacy.get('favorite_count', 0),
        "retweets": legacy.get('retweet_count', 0),
        "replies": legacy.get('reply_count', 0),
        "views": int(views) if str(views).isdigit() else 0,
        "url": f"https://x.com/{screen_name}/status/{tweet_id}",
        "created_at": legacy.get('created_at', ''),
    }


async def cmd_post(tweet_id: str, text: str):
    """Post a reply to a specific tweet"""
    s, ct, csrf = await init_session()

    path = '/i/api/graphql/a1p9RWpkYKBjWv_I3WzS-A/CreateTweet'
    headers = build_headers(ct, csrf, 'POST', path)

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

    r = await s.post(f'https://x.com{path}', headers=headers, json=payload)

    if r.status_code == 200:
        data = r.json()
        result = (data.get('data', {})
                 .get('create_tweet', {})
                 .get('tweet_results', {})
                 .get('result', {}))
        new_id = result.get('rest_id', '')
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


async def cmd_tweet(text: str):
    """Post an original tweet (not a reply) for compose mode"""
    s, ct, csrf = await init_session()

    path = '/i/api/graphql/a1p9RWpkYKBjWv_I3WzS-A/CreateTweet'
    headers = build_headers(ct, csrf, 'POST', path)

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

    r = await s.post(f'https://x.com{path}', headers=headers, json=payload)

    if r.status_code == 200:
        data = r.json()
        result = (data.get('data', {})
                 .get('create_tweet', {})
                 .get('tweet_results', {})
                 .get('result', {}))
        new_id = result.get('rest_id', '')
        
        # Get handle from config
        config = load_config()
        handle = config.get('handle', 'unknown') if config else 'unknown'
        
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
    """Delete a tweet by ID (for cleanup)"""
    s, ct, csrf = await init_session()

    path = '/i/api/graphql/VaenaVgh5q5ih7kvyVjgtg/DeleteTweet'
    headers = build_headers(ct, csrf, 'POST', path)

    payload = {
        "variables": {"tweet_id": tweet_id, "dark_request": False},
        "queryId": "VaenaVgh5q5ih7kvyVjgtg",
    }

    r = await s.post(f'https://x.com{path}', headers=headers, json=payload)

    if r.status_code == 200:
        print(json.dumps({"success": True, "deleted": tweet_id}))
    else:
        print(json.dumps({"success": False, "error": f"Status {r.status_code}: {r.text[:200]}"}))
        sys.exit(1)

    await s.close()


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
    print("\nTest with: python x_client.py test")


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
        print("No config found. Run auto-post.py status to auto-generate from .env")
        sys.exit(1)
    print(json.dumps(config, indent=2))


def main():
    parser = argparse.ArgumentParser(description="X API client for /x skill")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    subparsers.add_parser("test", help="Test authentication")

    cookies_parser = subparsers.add_parser("cookies", help="Set cookies manually")
    cookies_parser.add_argument("ct0", help="ct0 cookie value")
    cookies_parser.add_argument("auth_token", help="auth_token cookie value")

    search_parser = subparsers.add_parser("search", help="Search tweets")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--count", type=int, default=20, help="Max results")

    post_parser = subparsers.add_parser("post", help="Post reply to tweet")
    post_parser.add_argument("tweet_id", help="Tweet ID to reply to")
    post_parser.add_argument("text", help="Reply text")

    tweet_parser = subparsers.add_parser("tweet", help="Post original tweet")
    tweet_parser.add_argument("text", help="Tweet text")

    delete_parser = subparsers.add_parser("delete", help="Delete a tweet")
    delete_parser.add_argument("tweet_id", help="Tweet ID to delete")

    config_parser = subparsers.add_parser("config", help="Show or set config")
    config_parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set a config key")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "test":
        asyncio.run(cmd_test())
    elif args.command == "cookies":
        asyncio.run(cmd_cookies(args.ct0, args.auth_token))
    elif args.command == "search":
        asyncio.run(cmd_search(args.query, args.count))
    elif args.command == "post":
        asyncio.run(cmd_post(args.tweet_id, args.text))
    elif args.command == "tweet":
        asyncio.run(cmd_tweet(args.text))
    elif args.command == "delete":
        asyncio.run(cmd_delete(args.tweet_id))
    elif args.command == "config":
        cmd_config(args)


if __name__ == "__main__":
    main()
