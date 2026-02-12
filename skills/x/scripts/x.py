#!/usr/bin/env python3
"""
X skill utility script
Handles reply history, deduplication, rate limiting for /x skill
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path


def get_data_file():
    """Get path to history.json (relative to script's grandparent dir)"""
    script_dir = Path(__file__).parent.parent  # skills/x/
    data_dir = script_dir / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir / "history.json"


def load_history():
    """Load history.json, initialize if not exists"""
    data_file = get_data_file()
    if not data_file.exists():
        return {"replies": [], "daily_counts": {}}

    with open(data_file, "r", encoding="utf-8") as f:
        return json.load(f)


def save_history(data):
    """Save history.json atomically"""
    data_file = get_data_file()
    temp_file = data_file.with_suffix(".json.tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    temp_file.replace(data_file)


def get_url_hash(url):
    """Generate SHA256 hash of target URL for dedup"""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def cmd_log(args):
    """Log a posted reply to history"""
    history = load_history()

    url_hash = get_url_hash(args.target_url)
    today = datetime.now().strftime("%Y-%m-%d")

    # Add reply entry
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

    # Increment daily count
    history["daily_counts"][today] = history["daily_counts"].get(today, 0) + 1

    save_history(history)
    print(f"Logged reply to {args.author} (reach: {args.reach})")


def cmd_check(args):
    """Check if target URL already replied to"""
    history = load_history()
    url_hash = get_url_hash(args.target_url)

    for reply in history["replies"]:
        if reply["id"] == url_hash:
            sys.exit(1)  # Already replied

    sys.exit(0)  # Not replied


def cmd_history(args):
    """Show posting history with optional filters"""
    history = load_history()
    replies = history["replies"]

    # Apply filters
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

    # Print table
    print(f"\n{'Date':<12} {'Author':<20} {'Topic':<25} {'Reach':<8}")
    print("-" * 70)

    for reply in sorted(replies, key=lambda x: x["timestamp"], reverse=True):
        date = reply["timestamp"][:10]
        author = reply["author"][:18]
        topic = reply["topic"][:23]
        reach = reply["estimated_reach"]
        print(f"{date:<12} {author:<20} {topic:<25} {reach:<8}")

    print(f"\nTotal: {len(replies)} replies")


def cmd_status(args):
    """Show daily/weekly post counts and reach estimates"""
    history = load_history()

    # Calculate counts
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = history["daily_counts"].get(today, 0)

    # Weekly count
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    weekly_count = sum(
        count for date, count in history["daily_counts"].items()
        if date >= week_ago
    )

    # Total reach (all time)
    total_reach = sum(r["estimated_reach"] for r in history["replies"])

    # Recent reach (last 7 days)
    week_ago_dt = datetime.now() - timedelta(days=7)
    recent_reach = sum(
        r["estimated_reach"] for r in history["replies"]
        if datetime.fromisoformat(r["timestamp"].rstrip("Z")) >= week_ago_dt
    )

    print(f"\n{'Metric':<20} {'Count':<10}")
    print("-" * 35)
    print(f"{'Today':<20} {today_count:<10} / 30 daily limit")
    print(f"{'Last 7 days':<20} {weekly_count:<10}")
    print(f"{'Total replies':<20} {len(history['replies']):<10}")
    print(f"{'Total reach':<20} {total_reach:<10,}")
    print(f"{'Recent reach (7d)':<20} {recent_reach:<10,}")


def cmd_rate_check(args):
    """Check if rate limited (exit 0=ok, 1=limited)"""
    history = load_history()
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = history["daily_counts"].get(today, 0)

    if today_count >= 30:
        print(f"Rate limited: {today_count}/30 replies today")
        sys.exit(1)

    print(f"Rate OK: {today_count}/30 replies today")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="X skill utility script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # log command
    log_parser = subparsers.add_parser("log", help="Log a posted reply")
    log_parser.add_argument("target_url", help="Target post URL")
    log_parser.add_argument("author", help="Target post author")
    log_parser.add_argument("reply_text", help="Reply text posted")
    log_parser.add_argument("topic", help="Topic/theme")
    log_parser.add_argument("query", help="Search query used")
    log_parser.add_argument("reach", help="Estimated reach")

    # check command
    check_parser = subparsers.add_parser("check", help="Check if already replied")
    check_parser.add_argument("target_url", help="Target post URL")

    # history command
    history_parser = subparsers.add_parser("history", help="Show posting history")
    history_parser.add_argument("--days", type=int, help="Filter by days ago")
    history_parser.add_argument("--topic", help="Filter by topic")

    # status command
    subparsers.add_parser("status", help="Show counts and reach")

    # rate-check command
    subparsers.add_parser("rate-check", help="Check rate limit status")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Dispatch to command handlers
    if args.command == "log":
        cmd_log(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "rate-check":
        cmd_rate_check(args)


if __name__ == "__main__":
    main()
