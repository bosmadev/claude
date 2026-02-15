#!/usr/bin/env python3
"""
Receipt Audit Trail CLI - View and manage Ralph agent audit receipts.

Usage:
    audit-receipts.py list [--agent AGENT] [--action ACTION] [--limit N]
    audit-receipts.py show <receipt-id>
    audit-receipts.py report [--by-agent|--by-phase|--by-time]
    audit-receipts.py cleanup [--before DATE] [--dry-run]

Commands:
    list      List receipts with optional filtering
    show      Show detailed receipt by ID
    report    Generate summary reports
    cleanup   Delete old receipts

Examples:
    # List all receipts for agent-3
    audit-receipts.py list --agent agent-3

    # Show specific receipt
    audit-receipts.py show abc123

    # Generate report by agent
    audit-receipts.py report --by-agent

    # Cleanup receipts older than 7 days
    audit-receipts.py cleanup --before 7d
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from collections import defaultdict


RECEIPTS_DIR = Path.home() / ".claude" / "ralph" / "receipts"


def load_receipt(receipt_path: Path) -> Optional[dict[str, Any]]:
    """Load and parse a receipt JSON file."""
    try:
        return json.loads(receipt_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_receipts(
    agent_filter: Optional[str] = None,
    action_filter: Optional[str] = None,
    limit: int = 50
) -> None:
    """List receipts with optional filtering."""
    if not RECEIPTS_DIR.exists():
        print("No receipts directory found.")
        return

    receipts = []
    for path in sorted(RECEIPTS_DIR.glob("*.json"), reverse=True):
        receipt = load_receipt(path)
        if not receipt:
            continue

        # Apply filters
        if agent_filter and receipt.get("agent_id") != agent_filter:
            continue
        if action_filter and receipt.get("action") != action_filter:
            continue

        receipts.append((path, receipt))

        if len(receipts) >= limit:
            break

    if not receipts:
        print("No receipts found matching criteria.")
        return

    # Print table header
    print(f"{'Timestamp':<20} {'Agent':<12} {'Action':<18} {'Receipt ID':<10}")
    print("-" * 80)

    # Print receipts
    for path, receipt in receipts:
        timestamp = receipt.get("timestamp", "unknown")
        # Format timestamp for readability
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            timestamp_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            timestamp_str = timestamp[:19] if len(timestamp) > 19 else timestamp

        agent_id = receipt.get("agent_id", "unknown")
        action = receipt.get("action", "unknown")
        receipt_id = receipt.get("id", "unknown")[:8]  # Short ID

        print(f"{timestamp_str:<20} {agent_id:<12} {action:<18} {receipt_id}")

    print(f"\nShowing {len(receipts)} receipt(s)")


def show_receipt(receipt_id: str) -> None:
    """Show detailed receipt information."""
    if not RECEIPTS_DIR.exists():
        print("No receipts directory found.")
        return

    # Find receipt by ID (support both full and short IDs)
    matching_receipts = []
    for path in RECEIPTS_DIR.glob("*.json"):
        receipt = load_receipt(path)
        if not receipt:
            continue
        if receipt.get("id", "").startswith(receipt_id):
            matching_receipts.append(receipt)

    if not matching_receipts:
        print(f"No receipt found with ID: {receipt_id}")
        return

    if len(matching_receipts) > 1:
        print(f"Multiple receipts match ID: {receipt_id}")
        print("Use a longer ID prefix to narrow results.")
        return

    receipt = matching_receipts[0]

    # Format output
    print("=" * 80)
    print(f"Receipt ID: {receipt.get('id')}")
    print(f"Timestamp:  {receipt.get('timestamp')}")
    print(f"Agent:      {receipt.get('agent_id')}")
    print(f"Action:     {receipt.get('action')}")
    print(f"Session:    {receipt.get('session_id')}")
    print("-" * 80)
    print("Details:")
    details = receipt.get("details", {})
    for key, value in details.items():
        print(f"  {key}: {value}")
    print("=" * 80)


def generate_report(
    by_agent: bool = False,
    by_phase: bool = False,
    by_time: bool = False
) -> None:
    """Generate summary reports."""
    if not RECEIPTS_DIR.exists():
        print("No receipts directory found.")
        return

    receipts = []
    for path in RECEIPTS_DIR.glob("*.json"):
        receipt = load_receipt(path)
        if receipt:
            receipts.append(receipt)

    if not receipts:
        print("No receipts found.")
        return

    print(f"Receipt Audit Report - Total: {len(receipts)} receipt(s)")
    print("=" * 80)

    if by_agent:
        # Group by agent_id
        by_agent_data: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for receipt in receipts:
            agent = receipt.get("agent_id", "unknown")
            action = receipt.get("action", "unknown")
            by_agent_data[agent][action] += 1

        print("\nReport by Agent:")
        print("-" * 80)
        for agent in sorted(by_agent_data.keys()):
            print(f"\n{agent}:")
            actions = by_agent_data[agent]
            for action in sorted(actions.keys()):
                count = actions[action]
                print(f"  {action:<20} {count:>4}")

    elif by_phase:
        # Group by action type (phase)
        by_phase_data: dict[str, int] = defaultdict(int)
        for receipt in receipts:
            action = receipt.get("action", "unknown")
            by_phase_data[action] += 1

        print("\nReport by Action Type:")
        print("-" * 80)
        for action in sorted(by_phase_data.keys()):
            count = by_phase_data[action]
            print(f"{action:<20} {count:>4}")

    elif by_time:
        # Group by time range (hourly buckets)
        by_time_data: dict[str, int] = defaultdict(int)
        for receipt in receipts:
            timestamp = receipt.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                hour_bucket = dt.strftime("%Y-%m-%d %H:00")
                by_time_data[hour_bucket] += 1
            except (ValueError, AttributeError):
                by_time_data["unknown"] += 1

        print("\nReport by Time (hourly):")
        print("-" * 80)
        for time_bucket in sorted(by_time_data.keys()):
            count = by_time_data[time_bucket]
            print(f"{time_bucket:<20} {count:>4}")

    else:
        # Default: summary stats
        print("\nSummary Statistics:")
        print("-" * 80)

        # Count by action
        action_counts: dict[str, int] = defaultdict(int)
        for receipt in receipts:
            action = receipt.get("action", "unknown")
            action_counts[action] += 1

        for action in sorted(action_counts.keys()):
            count = action_counts[action]
            print(f"{action:<20} {count:>4}")

        # Count by agent
        print("\nBy Agent:")
        agent_counts: dict[str, int] = defaultdict(int)
        for receipt in receipts:
            agent = receipt.get("agent_id", "unknown")
            agent_counts[agent] += 1

        for agent in sorted(agent_counts.keys()):
            count = agent_counts[agent]
            print(f"{agent:<20} {count:>4}")

    print("=" * 80)


def cleanup_receipts(before_date: Optional[str] = None, dry_run: bool = False) -> None:
    """Delete old receipts."""
    if not RECEIPTS_DIR.exists():
        print("No receipts directory found.")
        return

    # Parse before_date
    cutoff_date = None
    if before_date:
        # Support formats: "7d", "2025-01-01", etc.
        if before_date.endswith("d"):
            # Relative days
            try:
                days = int(before_date[:-1])
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
            except ValueError:
                print(f"Invalid date format: {before_date}")
                return
        else:
            # Absolute date
            try:
                cutoff_date = datetime.fromisoformat(before_date)
                if cutoff_date.tzinfo is None:
                    cutoff_date = cutoff_date.replace(tzinfo=timezone.utc)
            except ValueError:
                print(f"Invalid date format: {before_date}")
                return

    receipts_to_delete = []
    for path in RECEIPTS_DIR.glob("*.json"):
        receipt = load_receipt(path)
        if not receipt:
            continue

        # Check timestamp
        timestamp = receipt.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if cutoff_date and dt < cutoff_date:
                receipts_to_delete.append(path)
        except (ValueError, AttributeError):
            # Invalid timestamp - optionally delete
            pass

    if not receipts_to_delete:
        print("No receipts to delete.")
        return

    print(f"Found {len(receipts_to_delete)} receipt(s) to delete")

    if dry_run:
        print("\n[DRY RUN] Would delete:")
        for path in receipts_to_delete:
            print(f"  {path.name}")
    else:
        for path in receipts_to_delete:
            try:
                path.unlink()
            except OSError:
                print(f"Failed to delete: {path.name}")

        print(f"Deleted {len(receipts_to_delete)} receipt(s)")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Receipt Audit Trail CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # List command
    list_parser = subparsers.add_parser("list", help="List receipts")
    list_parser.add_argument("--agent", help="Filter by agent ID")
    list_parser.add_argument("--action", help="Filter by action type")
    list_parser.add_argument("--limit", type=int, default=50, help="Limit results (default: 50)")

    # Show command
    show_parser = subparsers.add_parser("show", help="Show receipt details")
    show_parser.add_argument("receipt_id", help="Receipt ID (full or prefix)")

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate summary report")
    report_group = report_parser.add_mutually_exclusive_group()
    report_group.add_argument("--by-agent", action="store_true", help="Group by agent")
    report_group.add_argument("--by-phase", action="store_true", help="Group by phase/action")
    report_group.add_argument("--by-time", action="store_true", help="Group by time")

    # Cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Delete old receipts")
    cleanup_parser.add_argument("--before", help="Delete receipts before date (e.g., '7d', '2025-01-01')")
    cleanup_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "list":
        list_receipts(args.agent, args.action, args.limit)
    elif args.command == "show":
        show_receipt(args.receipt_id)
    elif args.command == "report":
        generate_report(args.by_agent, args.by_phase, args.by_time)
    elif args.command == "cleanup":
        cleanup_receipts(args.before, args.dry_run)


if __name__ == "__main__":
    main()
