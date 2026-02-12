#!/usr/bin/env python3
"""
Twikit client for /x skill -- fast API-based X/Twitter posting
Replaces Chrome MCP browser automation for posting (1-2 sec vs 17 sec per post)

Usage:
  python twikit_client.py setup              # Interactive login, saves cookies
  python twikit_client.py test               # Verify auth works
  python twikit_client.py search "query"     # Search tweets, return JSON
  python twikit_client.py post TWEET_ID TEXT # Post reply to tweet
  python twikit_client.py cookies CT0 AUTH   # Set cookies manually (no login needed)
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure twikit is installed
try:
    from twikit import Client
except ImportError:
    print("ERROR: twikit not installed. Run: pip install twikit")
    sys.exit(1)


def get_data_dir():
    """Get path to skills/x/data/ directory"""
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


def get_cookies_path():
    """Get path to cookies.json in skills/x/data/"""
    return get_data_dir() / "cookies.json"


def get_config_path():
    """Get path to config.json in skills/x/data/"""
    return get_data_dir() / "config.json"


def get_env_path():
    """Get path to .env file in skills/x/"""
    return Path(__file__).parent.parent / ".env"


def load_config():
    """Load user config from skills/x/data/config.json"""
    config_path = get_config_path()
    if not config_path.exists():
        return None
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


async def cmd_setup():
    """Interactive login - saves cookies for future use"""
    print("=== X/Twitter Login Setup ===")
    print("This saves a session cookie so you don't need to login again.\n")

    username = input("Username or email: ").strip()
    email = input("Email (for 2FA verification, can be same): ").strip()
    password = input("Password: ").strip()

    if not username or not password:
        print("ERROR: Username and password required")
        sys.exit(1)

    client = Client("en-US")

    try:
        await client.login(
            auth_info_1=username,
            auth_info_2=email,
            password=password,
        )
    except Exception as e:
        print(f"ERROR: Login failed: {e}")
        print("\nIf you see a challenge, try the 'cookies' command instead:")
        print("  python twikit_client.py cookies <ct0> <auth_token>")
        sys.exit(1)

    cookies_path = get_cookies_path()
    client.save_cookies(str(cookies_path))
    print(f"\nLogin successful! Cookies saved to {cookies_path}")
    print("Future /x commands will use these cookies automatically.")


async def cmd_cookies(ct0: str, auth_token: str):
    """Save cookies manually (extracted from DevTools or Cookie-Editor extension)"""
    cookies_path = get_cookies_path()

    # Twikit expects cookies in its own format via save_cookies/load_cookies
    # But we can also create a client and set cookies directly
    # For manual cookies, we write a JSON that load_cookies can read
    cookie_data = {
        "ct0": ct0,
        "auth_token": auth_token,
    }

    # Save as .env file for the skill to reference
    env_path = get_env_path()
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"X_CT0={ct0}\n")
        f.write(f"X_AUTH_TOKEN={auth_token}\n")

    # Also try to create a twikit-compatible cookies file
    # Twikit uses httpx cookies format
    client = Client("en-US")
    client.http.cookies.set("ct0", ct0, domain=".x.com")
    client.http.cookies.set("auth_token", auth_token, domain=".x.com")

    try:
        client.save_cookies(str(cookies_path))
        print(f"Cookies saved to {cookies_path}")
    except Exception:
        # Fallback: save raw JSON
        with open(cookies_path, "w", encoding="utf-8") as f:
            json.dump(cookie_data, f, indent=2)
        print(f"Cookies saved to {cookies_path} (raw format)")

    print(f"Env file saved to {env_path}")
    print("\nTest with: python twikit_client.py test")


async def cmd_test():
    """Verify auth works by fetching current user info"""
    cookies_path = get_cookies_path()

    if not cookies_path.exists():
        print("ERROR: No cookies found. Run 'setup' or 'cookies' first.")
        sys.exit(1)

    client = Client("en-US")

    try:
        client.load_cookies(str(cookies_path))
    except Exception:
        # Try raw JSON format
        with open(cookies_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "ct0" in data and "auth_token" in data:
            client.http.cookies.set("ct0", data["ct0"], domain=".x.com")
            client.http.cookies.set("auth_token", data["auth_token"], domain=".x.com")
        else:
            print("ERROR: Invalid cookies file format")
            sys.exit(1)

    try:
        user = await client.user()
        print(f"Authenticated as: @{user.screen_name}")
        print(f"Name: {user.name}")
        print(f"Followers: {user.followers_count}")
        print("Auth OK!")
    except Exception as e:
        print(f"ERROR: Auth test failed: {e}")
        print("Cookies may be expired. Run 'setup' again.")
        sys.exit(1)


async def cmd_search(query: str, count: int = 20):
    """Search tweets and return JSON results"""
    cookies_path = get_cookies_path()

    if not cookies_path.exists():
        print("ERROR: No cookies found. Run 'setup' or 'cookies' first.")
        sys.exit(1)

    client = Client("en-US")
    await _load_cookies(client, cookies_path)

    try:
        tweets = await client.search_tweet(query, "Top", count=count)
    except Exception as e:
        print(json.dumps({"error": str(e), "tweets": []}))
        sys.exit(1)

    results = []
    for tweet in tweets:
        results.append({
            "id": tweet.id,
            "text": tweet.text,
            "author": tweet.user.screen_name if tweet.user else "unknown",
            "author_name": tweet.user.name if tweet.user else "unknown",
            "likes": tweet.favorite_count,
            "retweets": tweet.retweet_count,
            "replies": tweet.reply_count,
            "views": getattr(tweet, "view_count", 0) or 0,
            "url": f"https://x.com/{tweet.user.screen_name}/status/{tweet.id}" if tweet.user else "",
            "created_at": str(tweet.created_at) if tweet.created_at else "",
        })

    print(json.dumps({"tweets": results, "count": len(results)}, indent=2))


async def cmd_post(tweet_id: str, text: str):
    """Post a reply to a specific tweet"""
    cookies_path = get_cookies_path()

    if not cookies_path.exists():
        print("ERROR: No cookies found. Run 'setup' or 'cookies' first.")
        sys.exit(1)

    client = Client("en-US")
    await _load_cookies(client, cookies_path)

    try:
        result = await client.create_tweet(text, reply_to=tweet_id)
        print(json.dumps({
            "success": True,
            "tweet_id": result.id if result else None,
            "reply_to": tweet_id,
            "text": text,
        }))
    except Exception as e:
        print(json.dumps({
            "success": False,
            "error": str(e),
            "reply_to": tweet_id,
            "text": text,
        }))
        sys.exit(1)


async def _load_cookies(client: Client, cookies_path: Path):
    """Load cookies with fallback for different formats"""
    try:
        client.load_cookies(str(cookies_path))
        return
    except Exception:
        pass

    # Try raw JSON format
    try:
        with open(cookies_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "ct0" in data and "auth_token" in data:
            client.http.cookies.set("ct0", data["ct0"], domain=".x.com")
            client.http.cookies.set("auth_token", data["auth_token"], domain=".x.com")
            return
    except Exception:
        pass

    print("ERROR: Could not load cookies from any format")
    sys.exit(1)


def cmd_config(args):
    """Show or set config values"""
    config_path = get_config_path()
    example_path = Path(__file__).parent.parent / "config.example.json"

    if args.set:
        key, value = args.set
        config = load_config() or {}
        config[key] = value
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        print(f"Set {key} = {value}")
        print(f"Config saved to {config_path}")
        return

    config = load_config()
    if not config:
        print("No config found.")
        print(f"\nCopy the example config:")
        print(f"  cp {example_path} {config_path}")
        print(f"\nThen edit {config_path} with your settings.")
        sys.exit(1)

    print(json.dumps(config, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Twikit client for /x skill")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # setup command
    subparsers.add_parser("setup", help="Interactive login setup")

    # test command
    subparsers.add_parser("test", help="Test authentication")

    # cookies command
    cookies_parser = subparsers.add_parser("cookies", help="Set cookies manually")
    cookies_parser.add_argument("ct0", help="ct0 cookie value")
    cookies_parser.add_argument("auth_token", help="auth_token cookie value")

    # search command
    search_parser = subparsers.add_parser("search", help="Search tweets")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--count", type=int, default=20, help="Max results")

    # post command
    post_parser = subparsers.add_parser("post", help="Post reply to tweet")
    post_parser.add_argument("tweet_id", help="Tweet ID to reply to")
    post_parser.add_argument("text", help="Reply text")

    # config command
    config_parser = subparsers.add_parser("config", help="Show or set config")
    config_parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set a config key")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Route to async handlers
    if args.command == "setup":
        asyncio.run(cmd_setup())
    elif args.command == "test":
        asyncio.run(cmd_test())
    elif args.command == "cookies":
        asyncio.run(cmd_cookies(args.ct0, args.auth_token))
    elif args.command == "search":
        asyncio.run(cmd_search(args.query, args.count))
    elif args.command == "post":
        asyncio.run(cmd_post(args.tweet_id, args.text))
    elif args.command == "config":
        cmd_config(args)


if __name__ == "__main__":
    main()
