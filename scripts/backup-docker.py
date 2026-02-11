#!/usr/bin/env python3
"""
Docker Services Backup Script

Backs up Redis and MongoDB data from Docker containers:
- Pulsona Redis: BGSAVE + copy dump.rdb
- Pulsona MongoDB: mongodump + copy backup directory
- Claude Redis: Direct file copy from bind mount

Destination: D:/docker-data/backups/{project}/{service}/{timestamp}/
Retention: Configurable (default 7 days)
"""

import argparse
import io
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Fix Windows cp1252 encoding for Unicode output
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def is_container_running(container_name: str) -> bool:
    """Check if a Docker container is running."""
    try:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"
    except Exception as e:
        logger.error(f"Failed to check container status for {container_name}: {e}")
        return False


def backup_pulsona_redis(dest_base: Path, dry_run: bool) -> bool:
    """
    Backup Pulsona Redis database.
    
    Steps:
    1. Execute BGSAVE command
    2. Wait 2 seconds for background save to complete
    3. Copy dump.rdb from container to destination
    """
    container_name = "pulsona-redis"
    service_dest = dest_base / "pulsona" / "redis" / datetime.now().strftime("%Y%m%d-%H%M%S")
    
    logger.info(f"Backing up {container_name}...")
    
    if not is_container_running(container_name):
        logger.error(f"Container {container_name} is not running")
        return False
    
    try:
        # Step 1: Execute BGSAVE
        if dry_run:
            logger.info(f"[DRY RUN] Would execute: docker exec {container_name} redis-cli BGSAVE")
        else:
            result = subprocess.run(
                ["docker", "exec", container_name, "redis-cli", "BGSAVE"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                logger.error(f"BGSAVE failed: {result.stderr.strip()}")
                return False
            logger.info(f"BGSAVE initiated: {result.stdout.strip()}")
        
        # Step 2: Wait for background save
        if dry_run:
            logger.info("[DRY RUN] Would wait 2 seconds for BGSAVE to complete")
        else:
            time.sleep(2)
        
        # Step 3: Copy dump.rdb to destination
        if dry_run:
            logger.info(f"[DRY RUN] Would create: {service_dest}")
            logger.info(f"[DRY RUN] Would copy: docker cp {container_name}:/data/dump.rdb {service_dest}/dump.rdb")
        else:
            service_dest.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["docker", "cp", f"{container_name}:/data/dump.rdb", str(service_dest / "dump.rdb")],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                logger.error(f"Failed to copy dump.rdb: {result.stderr.strip()}")
                return False
            logger.info(f"✓ Backup saved to {service_dest}")
        
        return True
        
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout during {container_name} backup")
        return False
    except Exception as e:
        logger.error(f"Failed to backup {container_name}: {e}")
        return False


def backup_pulsona_mongodb(dest_base: Path, dry_run: bool) -> bool:
    """
    Backup Pulsona MongoDB database.
    
    Steps:
    1. Execute mongodump to /tmp/backup inside container
    2. Copy backup directory from container to destination
    """
    container_name = "pulsona-mongodb"
    service_dest = dest_base / "pulsona" / "mongodb" / datetime.now().strftime("%Y%m%d-%H%M%S")
    
    logger.info(f"Backing up {container_name}...")
    
    if not is_container_running(container_name):
        logger.error(f"Container {container_name} is not running")
        return False
    
    try:
        # Step 1: Execute mongodump
        if dry_run:
            logger.info(f"[DRY RUN] Would execute: docker exec {container_name} mongodump --out /tmp/backup")
        else:
            result = subprocess.run(
                ["docker", "exec", container_name, "mongodump", "--out", "/tmp/backup"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                logger.error(f"mongodump failed: {result.stderr.strip()}")
                return False
            logger.info("mongodump completed successfully")
        
        # Step 2: Copy backup directory to destination
        if dry_run:
            logger.info(f"[DRY RUN] Would create: {service_dest}")
            logger.info(f"[DRY RUN] Would copy: docker cp {container_name}:/tmp/backup/. {service_dest}/")
        else:
            service_dest.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["docker", "cp", f"{container_name}:/tmp/backup/.", str(service_dest) + "/"],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode != 0:
                logger.error(f"Failed to copy backup: {result.stderr.strip()}")
                return False
            logger.info(f"✓ Backup saved to {service_dest}")
        
        return True
        
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout during {container_name} backup")
        return False
    except Exception as e:
        logger.error(f"Failed to backup {container_name}: {e}")
        return False


def backup_claude_redis(dest_base: Path, dry_run: bool) -> bool:
    """
    Backup Claude Redis database.
    
    Direct file copy from bind mount:
    D:/docker-data/claude/redis/dump.rdb -> destination
    """
    source_file = Path("D:/docker-data/claude/redis/dump.rdb")
    service_dest = dest_base / "claude" / "redis" / datetime.now().strftime("%Y%m%d-%H%M%S")
    
    logger.info("Backing up claude-redis...")
    
    if not source_file.exists():
        logger.error(f"Source file not found: {source_file}")
        return False
    
    try:
        if dry_run:
            logger.info(f"[DRY RUN] Would create: {service_dest}")
            logger.info(f"[DRY RUN] Would copy: {source_file} -> {service_dest / 'dump.rdb'}")
        else:
            service_dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, service_dest / "dump.rdb")
            logger.info(f"✓ Backup saved to {service_dest}")
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to backup claude-redis: {e}")
        return False


def cleanup_old_backups(dest_base: Path, retention_days: int, dry_run: bool) -> None:
    """
    Delete backup directories older than retention_days.
    
    Walks through all project/service subdirectories and removes
    timestamp directories older than the retention period.
    """
    logger.info(f"Cleaning up backups older than {retention_days} days...")
    
    if not dest_base.exists():
        logger.info("No backup directory found, skipping cleanup")
        return
    
    cutoff_time = datetime.now() - timedelta(days=retention_days)
    deleted_count = 0
    
    # Walk through project/service/timestamp structure
    for project_dir in dest_base.iterdir():
        if not project_dir.is_dir():
            continue
        
        for service_dir in project_dir.iterdir():
            if not service_dir.is_dir():
                continue
            
            for timestamp_dir in service_dir.iterdir():
                if not timestamp_dir.is_dir():
                    continue
                
                # Parse timestamp from directory name (YYYYMMDD-HHMMSS)
                try:
                    dir_time = datetime.strptime(timestamp_dir.name, "%Y%m%d-%H%M%S")
                    
                    if dir_time < cutoff_time:
                        if dry_run:
                            logger.info(f"[DRY RUN] Would delete: {timestamp_dir}")
                        else:
                            shutil.rmtree(timestamp_dir)
                            logger.info(f"✓ Deleted old backup: {timestamp_dir}")
                        deleted_count += 1
                        
                except ValueError:
                    # Skip directories that don't match timestamp format
                    logger.warning(f"Skipping non-timestamp directory: {timestamp_dir}")
                    continue
    
    if deleted_count == 0:
        logger.info("No old backups found to delete")
    else:
        action = "Would delete" if dry_run else "Deleted"
        logger.info(f"{action} {deleted_count} old backup(s)")


def main() -> int:
    """Run Docker backup tasks."""
    parser = argparse.ArgumentParser(
        description="Backup Docker services (Redis, MongoDB)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=7,
        help="Number of days to retain backups (default: 7)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without executing",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path("D:/docker-data/backups"),
        help="Backup destination base directory (default: D:/docker-data/backups)",
    )
    
    args = parser.parse_args()
    
    logger.info("Docker Services Backup")
    logger.info("=" * 22)
    
    if args.dry_run:
        logger.info("*** DRY RUN MODE - No changes will be made ***")
    
    # Track success/failure for exit code
    results = {
        "pulsona-redis": False,
        "pulsona-mongodb": False,
        "claude-redis": False,
    }
    
    # Execute backups
    results["pulsona-redis"] = backup_pulsona_redis(args.dest, args.dry_run)
    results["pulsona-mongodb"] = backup_pulsona_mongodb(args.dest, args.dry_run)
    results["claude-redis"] = backup_claude_redis(args.dest, args.dry_run)
    
    # Cleanup old backups
    cleanup_old_backups(args.dest, args.retention_days, args.dry_run)
    
    # Summary
    logger.info("=" * 22)
    success_count = sum(1 for success in results.values() if success)
    total_count = len(results)
    logger.info(f"Summary: {success_count}/{total_count} backups succeeded")
    
    # Exit code: 0 if all succeeded, 1 if any failed
    if success_count == total_count:
        logger.info("✓ All backups completed successfully")
        return 0
    else:
        logger.error("✗ Some backups failed")
        for service, success in results.items():
            status = "✓" if success else "✗"
            logger.info(f"  {status} {service}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
