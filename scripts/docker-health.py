#!/usr/bin/env python3
"""
Docker Health Check Script

Monitors Docker containers health status:
- pulsona-redis: Redis persistence stats (last save time, AOF status, bgsave)
- pulsona-mongodb: MongoDB server stats (connections, cache usage, uptime)
- claude-redis: Redis persistence stats

For each container:
- Name, status, uptime
- Memory usage/limit (percentage)
- Service-specific health metrics

Color coding:
- Green: All checks passed
- Yellow: Warning conditions (high memory, stale save)
- Red: Critical issues (not running, failed operations)

Exit codes:
- 0: All containers healthy
- 1: One or more containers unhealthy
"""

import argparse
import io
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Fix Windows cp1252 encoding for Unicode output
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ANSI color codes
class Colors:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BOLD = "\033[1m"

@dataclass
class ContainerHealth:
    """Health status for a single container."""
    name: str
    status: str
    uptime: str
    memory_used: int
    memory_limit: int
    memory_pct: float
    health_status: str  # "healthy", "warning", "critical"
    health_msg: str
    extra_metrics: dict[str, Any]


def format_size(size_bytes: int) -> str:
    """Format byte size as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f}GB"


def format_uptime(seconds: int) -> str:
    """Format uptime seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m"
    elif seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        return f"{days}d {hours}h"


def run_command(cmd: list[str], timeout: int = 5) -> tuple[bool, str]:
    """
    Run shell command and return (success, output).

    Returns (False, error_msg) on failure.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        if result.returncode == 0:
            return True, result.stdout.strip()
        else:
            return False, result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "docker command not found"
    except Exception as e:
        return False, str(e)


def get_container_stats(container_name: str) -> dict[str, Any] | None:
    """
    Get basic container stats (status, uptime, memory).

    Returns None if container doesn't exist or isn't accessible.
    """
    # Check if container exists and get status
    success, output = run_command(
        ["docker", "inspect", "--format={{.State.Status}}", container_name]
    )

    if not success:
        return None

    status = output

    # Get detailed stats if running
    if status != "running":
        return {
            "name": container_name,
            "status": status,
            "uptime": "0s",
            "memory_used": 0,
            "memory_limit": 0,
            "memory_pct": 0.0,
        }

    # Get uptime
    success, started_at = run_command(
        ["docker", "inspect", "--format={{.State.StartedAt}}", container_name]
    )

    if success:
        # Parse timestamp and calculate uptime
        # Docker returns RFC3339: 2024-01-01T12:00:00.123456789Z
        try:
            from datetime import datetime, timezone
            started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            uptime_seconds = int((now - started).total_seconds())
            uptime = format_uptime(uptime_seconds)
        except (ValueError, ImportError):
            uptime = "unknown"
    else:
        uptime = "unknown"

    # Get memory stats
    success, mem_output = run_command(
        ["docker", "stats", "--no-stream", "--format={{.MemUsage}}", container_name]
    )

    if success:
        # Parse format: "123.4MiB / 2GiB"
        try:
            used_str, limit_str = mem_output.split(" / ")
            memory_used = parse_memory_string(used_str)
            memory_limit = parse_memory_string(limit_str)
            memory_pct = (memory_used / memory_limit * 100) if memory_limit > 0 else 0.0
        except (ValueError, ZeroDivisionError):
            memory_used = 0
            memory_limit = 0
            memory_pct = 0.0
    else:
        memory_used = 0
        memory_limit = 0
        memory_pct = 0.0

    return {
        "name": container_name,
        "status": status,
        "uptime": uptime,
        "memory_used": memory_used,
        "memory_limit": memory_limit,
        "memory_pct": memory_pct,
    }


def parse_memory_string(mem_str: str) -> int:
    """Parse Docker memory string (e.g., '123.4MiB') to bytes."""
    mem_str = mem_str.strip()

    # Extract number and unit
    import re
    match = re.match(r"([0-9.]+)\s*([A-Za-z]+)", mem_str)

    if not match:
        return 0

    value = float(match.group(1))
    unit = match.group(2).upper()

    # Convert to bytes
    multipliers = {
        "B": 1,
        "KB": 1024,
        "KIB": 1024,
        "MB": 1024 * 1024,
        "MIB": 1024 * 1024,
        "GB": 1024 * 1024 * 1024,
        "GIB": 1024 * 1024 * 1024,
    }

    return int(value * multipliers.get(unit, 1))


def check_redis_health(container_name: str, stats: dict[str, Any]) -> ContainerHealth:
    """Check Redis container health and persistence metrics."""
    if stats["status"] != "running":
        return ContainerHealth(
            name=container_name,
            status=stats["status"],
            uptime=stats["uptime"],
            memory_used=stats["memory_used"],
            memory_limit=stats["memory_limit"],
            memory_pct=stats["memory_pct"],
            health_status="critical",
            health_msg="Not running",
            extra_metrics={},
        )

    # Get Redis INFO persistence
    success, info_output = run_command(
        ["docker", "exec", container_name, "redis-cli", "INFO", "persistence"]
    )

    if not success:
        return ContainerHealth(
            name=container_name,
            status=stats["status"],
            uptime=stats["uptime"],
            memory_used=stats["memory_used"],
            memory_limit=stats["memory_limit"],
            memory_pct=stats["memory_pct"],
            health_status="warning",
            health_msg="Cannot read Redis INFO",
            extra_metrics={},
        )

    # Parse INFO output
    metrics = {}
    for line in info_output.splitlines():
        if ":" in line and not line.startswith("#"):
            key, value = line.split(":", 1)
            metrics[key] = value.strip()

    # Extract key metrics
    rdb_last_save_time = int(metrics.get("rdb_last_save_time", "0"))
    aof_enabled = metrics.get("aof_enabled", "0") == "1"
    aof_last_rewrite_status = metrics.get("aof_last_rewrite_status", "unknown")
    rdb_last_bgsave_status = metrics.get("rdb_last_bgsave_status", "unknown")

    # Calculate time since last save
    current_time = int(time.time())
    seconds_since_save = current_time - rdb_last_save_time if rdb_last_save_time > 0 else 999999

    # Determine health status
    health_status = "healthy"
    health_msg = "OK"

    # Check for critical issues
    if rdb_last_bgsave_status == "fail":
        health_status = "critical"
        health_msg = "Last bgsave failed"
    elif aof_enabled and aof_last_rewrite_status == "fail":
        health_status = "critical"
        health_msg = "AOF rewrite failed"
    # Check for warnings
    elif stats["memory_pct"] > 80:
        health_status = "warning"
        health_msg = f"High memory ({stats['memory_pct']:.0f}%)"
    elif seconds_since_save > 300:  # 5 minutes
        health_status = "warning"
        health_msg = f"Stale save ({seconds_since_save // 60}m ago)"

    return ContainerHealth(
        name=container_name,
        status=stats["status"],
        uptime=stats["uptime"],
        memory_used=stats["memory_used"],
        memory_limit=stats["memory_limit"],
        memory_pct=stats["memory_pct"],
        health_status=health_status,
        health_msg=health_msg,
        extra_metrics={
            "rdb_last_save": f"{seconds_since_save // 60}m ago" if seconds_since_save < 999999 else "never",
            "aof_enabled": "yes" if aof_enabled else "no",
            "bgsave_status": rdb_last_bgsave_status,
        },
    )


def check_mongodb_health(container_name: str, stats: dict[str, Any]) -> ContainerHealth:
    """Check MongoDB container health and server metrics."""
    if stats["status"] != "running":
        return ContainerHealth(
            name=container_name,
            status=stats["status"],
            uptime=stats["uptime"],
            memory_used=stats["memory_used"],
            memory_limit=stats["memory_limit"],
            memory_pct=stats["memory_pct"],
            health_status="critical",
            health_msg="Not running",
            extra_metrics={},
        )

    # Get MongoDB serverStatus
    success, status_output = run_command(
        ["docker", "exec", container_name, "mongosh", "--quiet", "--eval", "JSON.stringify(db.serverStatus())"],
        timeout=10
    )

    if not success:
        return ContainerHealth(
            name=container_name,
            status=stats["status"],
            uptime=stats["uptime"],
            memory_used=stats["memory_used"],
            memory_limit=stats["memory_limit"],
            memory_pct=stats["memory_pct"],
            health_status="warning",
            health_msg="Cannot read serverStatus",
            extra_metrics={},
        )

    # Parse JSON output
    try:
        server_status = json.loads(status_output)
    except json.JSONDecodeError:
        return ContainerHealth(
            name=container_name,
            status=stats["status"],
            uptime=stats["uptime"],
            memory_used=stats["memory_used"],
            memory_limit=stats["memory_limit"],
            memory_pct=stats["memory_pct"],
            health_status="warning",
            health_msg="Invalid serverStatus JSON",
            extra_metrics={},
        )

    # Extract key metrics (MongoDB returns BSON Long objects as {low, high, unsigned} dicts)
    def safe_int(val: Any) -> int:
        """Extract int from BSON Long dict or plain value."""
        if isinstance(val, dict) and "low" in val:
            return val["low"]  # BSON NumberLong
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    connections_current = safe_int(server_status.get("connections", {}).get("current", 0))
    cache_bytes = safe_int(server_status.get("wiredTiger", {}).get("cache", {}).get("bytes currently in the cache", 0))
    uptime_secs = safe_int(server_status.get("uptime", 0))

    # Determine health status
    health_status = "healthy"
    health_msg = "OK"

    if stats["memory_pct"] > 80:
        health_status = "warning"
        health_msg = f"High memory ({stats['memory_pct']:.0f}%)"

    return ContainerHealth(
        name=container_name,
        status=stats["status"],
        uptime=stats["uptime"],
        memory_used=stats["memory_used"],
        memory_limit=stats["memory_limit"],
        memory_pct=stats["memory_pct"],
        health_status=health_status,
        health_msg=health_msg,
        extra_metrics={
            "connections": connections_current,
            "cache_size": format_size(cache_bytes),
            "uptime": format_uptime(uptime_secs),
        },
    )


def colorize(text: str, status: str, no_color: bool) -> str:
    """Add color to text based on health status."""
    if no_color:
        return text

    color_map = {
        "healthy": Colors.GREEN,
        "warning": Colors.YELLOW,
        "critical": Colors.RED,
    }

    color = color_map.get(status, Colors.RESET)
    return f"{color}{text}{Colors.RESET}"


def print_table(containers: list[ContainerHealth], no_color: bool) -> None:
    """Print health check results in table format."""
    # Header
    print(f"\n{'Container':<20} {'Status':<12} {'Uptime':<10} {'Memory':<20} {'Health':<30}")
    print("=" * 92)

    # Rows
    for container in containers:
        status_text = colorize(container.status, container.health_status, no_color)

        # Format memory usage
        mem_text = f"{format_size(container.memory_used)} / {format_size(container.memory_limit)}"
        if container.memory_limit > 0:
            mem_text += f" ({container.memory_pct:.0f}%)"

        health_text = colorize(container.health_msg, container.health_status, no_color)

        print(f"{container.name:<20} {status_text:<12} {container.uptime:<10} {mem_text:<20} {health_text:<30}")

        # Print extra metrics if present
        if container.extra_metrics:
            for key, value in container.extra_metrics.items():
                print(f"  └─ {key}: {value}")


def print_json_output(containers: list[ContainerHealth]) -> None:
    """Print health check results in JSON format."""
    output = []

    for container in containers:
        output.append({
            "name": container.name,
            "status": container.status,
            "uptime": container.uptime,
            "memory_used": container.memory_used,
            "memory_limit": container.memory_limit,
            "memory_pct": container.memory_pct,
            "health_status": container.health_status,
            "health_msg": container.health_msg,
            "extra_metrics": container.extra_metrics,
        })

    print(json.dumps(output, indent=2))


def main() -> None:
    """Run Docker health checks."""
    parser = argparse.ArgumentParser(
        description="Check Docker containers health status"
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable color output"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    args = parser.parse_args()

    # Define containers to check
    container_checks = [
        ("pulsona-redis", "redis"),
        ("pulsona-mongodb", "mongodb"),
        ("claude-redis", "redis"),
    ]

    # Run health checks
    containers = []

    for container_name, container_type in container_checks:
        # Get basic stats
        stats = get_container_stats(container_name)

        if stats is None:
            # Container doesn't exist
            containers.append(ContainerHealth(
                name=container_name,
                status="not found",
                uptime="0s",
                memory_used=0,
                memory_limit=0,
                memory_pct=0.0,
                health_status="critical",
                health_msg="Container not found",
                extra_metrics={},
            ))
            continue

        # Check service-specific health
        if container_type == "redis":
            health = check_redis_health(container_name, stats)
        elif container_type == "mongodb":
            health = check_mongodb_health(container_name, stats)
        else:
            # Fallback for unknown types
            health = ContainerHealth(
                name=container_name,
                status=stats["status"],
                uptime=stats["uptime"],
                memory_used=stats["memory_used"],
                memory_limit=stats["memory_limit"],
                memory_pct=stats["memory_pct"],
                health_status="healthy" if stats["status"] == "running" else "critical",
                health_msg="OK" if stats["status"] == "running" else "Not running",
                extra_metrics={},
            )

        containers.append(health)

    # Output results
    if args.json:
        print_json_output(containers)
    else:
        print_table(containers, args.no_color)

    # Determine exit code
    has_issues = any(c.health_status in ("warning", "critical") for c in containers)
    sys.exit(1 if has_issues else 0)


if __name__ == "__main__":
    main()
