#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orphan Artifact Auditor for Claude Code

Scans ~/.claude/ directory for orphaned/stale artifacts:
- Orphaned session .jsonl files (not in sessions-index.json)
- Orphaned UUID directories (no matching .jsonl)
- Stale scratchpad directories
- Orphaned plan files
- Stale team/task configs
- Dead index entries
- D: drive temp remnants

Usage:
    python audit-orphans.py              # Dry-run (report only)
    python audit-orphans.py --fix        # Interactive cleanup with confirmations
    python audit-orphans.py --fix --yes  # Non-interactive cleanup (dangerous!)
"""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


class OrphanAuditor:
    """Audits and optionally cleans up orphaned artifacts in ~/.claude/"""

    def __init__(self, dry_run: bool = True, auto_confirm: bool = False):
        self.dry_run = dry_run
        self.auto_confirm = auto_confirm
        self.claude_root = Path(os.path.expanduser("~/.claude"))
        self.project_root = self.claude_root / "projects" / "C--Users-Dennis--claude"
        self.temp_scratchpad = Path(os.path.expanduser("~/AppData/Local/Temp/claude/C--Users-Dennis--claude"))
        self.plans_dir = self.claude_root / "plans"
        self.teams_dir = self.claude_root / "teams"
        self.tasks_dir = self.claude_root / "tasks"

        # Results
        self.orphaned_jsonl: List[str] = []
        self.orphaned_uuid_dirs: List[Tuple[str, int]] = []
        self.stale_scratchpads: List[str] = []
        self.orphaned_plans: List[str] = []
        self.completed_plans: List[str] = []
        self.stale_teams: List[str] = []
        self.stale_tasks: List[str] = []
        self.dead_index_entries: List[str] = []
        self.d_drive_remnants: List[str] = []

    def run_audit(self) -> None:
        """Execute all audit checks"""
        print("=" * 70)
        print("Claude Code Orphan Artifact Audit")
        print("=" * 70)
        print()

        # Load sessions index
        index_path = self.project_root / "sessions-index.json"
        if not index_path.exists():
            print(f"[ERROR] sessions-index.json not found at {index_path}")
            sys.exit(1)

        with open(index_path, encoding='utf-8') as f:
            sessions_index = json.load(f)

        indexed_sessions = {entry["sessionId"] for entry in sessions_index["entries"]}
        indexed_files = {Path(entry["fullPath"]).name for entry in sessions_index["entries"]}

        # Run checks
        self._check_orphaned_jsonl(indexed_files)
        self._check_orphaned_uuid_dirs(indexed_sessions)
        self._check_stale_scratchpads(indexed_sessions)
        self._check_orphaned_plans(indexed_sessions)
        self._check_stale_teams_tasks()
        self._check_dead_index_entries(sessions_index)
        self._check_d_drive_remnants()

        # Print summary
        self._print_summary()

    def _check_orphaned_jsonl(self, indexed_files: Set[str]) -> None:
        """Find .jsonl files not in sessions-index.json"""
        print("[1] Checking orphaned .jsonl files...")

        if not self.project_root.exists():
            print(f"  ⚠️  Project root not found: {self.project_root}")
            return

        all_jsonl = [f.name for f in self.project_root.glob("*.jsonl")]
        self.orphaned_jsonl = sorted(set(all_jsonl) - indexed_files)

        print(f"  Found {len(all_jsonl)} total .jsonl files")
        print(f"  Found {len(indexed_files)} indexed .jsonl files")
        print(f"  Found {len(self.orphaned_jsonl)} orphaned .jsonl files")
        print()

    def _check_orphaned_uuid_dirs(self, indexed_sessions: Set[str]) -> None:
        """Find UUID directories without matching .jsonl files"""
        print("[2] Checking orphaned UUID directories...")

        if not self.project_root.exists():
            print(f"  ⚠️  Project root not found: {self.project_root}")
            return

        # Find all UUID directories
        uuid_pattern = "[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f]-[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]"

        for item in self.project_root.iterdir():
            if item.is_dir() and len(item.name) == 36 and item.name.count("-") == 4:
                session_id = item.name
                jsonl_file = self.project_root / f"{session_id}.jsonl"

                if not jsonl_file.exists():
                    # Calculate directory size
                    size_bytes = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
                    self.orphaned_uuid_dirs.append((session_id, size_bytes))

        # Sort by size (largest first)
        self.orphaned_uuid_dirs.sort(key=lambda x: x[1], reverse=True)

        total_size = sum(size for _, size in self.orphaned_uuid_dirs)
        print(f"  Found {len(self.orphaned_uuid_dirs)} orphaned UUID directories")
        print(f"  Total size: {self._format_size(total_size)}")
        print()

    def _check_stale_scratchpads(self, indexed_sessions: Set[str]) -> None:
        """Find scratchpad directories for sessions not in index"""
        print("[3] Checking stale scratchpad directories...")

        if not self.temp_scratchpad.exists():
            print(f"  ⚠️  Scratchpad directory not found: {self.temp_scratchpad}")
            return

        all_scratchpad_dirs = [d.name for d in self.temp_scratchpad.iterdir() if d.is_dir() and d.name != "tasks"]
        stale_count = 0

        for session_id in all_scratchpad_dirs:
            if session_id not in indexed_sessions:
                self.stale_scratchpads.append(session_id)
                stale_count += 1

        total_size = sum(
            sum(f.stat().st_size for f in (self.temp_scratchpad / sid).rglob("*") if f.is_file())
            for sid in self.stale_scratchpads
        )

        print(f"  Found {len(all_scratchpad_dirs)} total scratchpad directories")
        print(f"  Found {stale_count} stale scratchpad directories")
        print(f"  Total stale size: {self._format_size(total_size)}")
        print()

    def _check_orphaned_plans(self, indexed_sessions: Set[str]) -> None:
        """Find plan files and categorize by status"""
        print("[4] Checking plan files...")

        if not self.plans_dir.exists():
            print(f"  ⚠️  Plans directory not found: {self.plans_dir}")
            return

        for plan_file in self.plans_dir.glob("*.md"):
            try:
                with open(plan_file, encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # Check status
                if "**Status:** Completed" in content or "Status: Completed" in content or plan_file.name.endswith("-COMPLETED.md"):
                    self.completed_plans.append(plan_file.name)

                # Check for session references (future enhancement)
                # This is a basic check - could be enhanced to parse session IDs from plan content

            except Exception as e:
                print(f"  [WARNING] Error reading {plan_file.name}: {str(e)}")

        total_plans = len(list(self.plans_dir.glob("*.md")))
        print(f"  Found {total_plans} total plan files")
        print(f"  Found {len(self.completed_plans)} completed plans (candidates for archival)")
        print()

    def _check_stale_teams_tasks(self) -> None:
        """Find leftover team/task configs"""
        print("[5] Checking team/task configurations...")

        # Check teams
        if self.teams_dir.exists():
            team_dirs = [d.name for d in self.teams_dir.iterdir() if d.is_dir()]
            self.stale_teams = team_dirs
            print(f"  Found {len(team_dirs)} team directories")
        else:
            print(f"  ⚠️  Teams directory not found: {self.teams_dir}")

        # Check tasks
        if self.tasks_dir.exists():
            task_dirs = [d.name for d in self.tasks_dir.iterdir() if d.is_dir()]
            self.stale_tasks = task_dirs
            print(f"  Found {len(task_dirs)} task directories")
        else:
            print(f"  ⚠️  Tasks directory not found: {self.tasks_dir}")

        print()

    def _check_dead_index_entries(self, sessions_index: Dict) -> None:
        """Find index entries pointing to non-existent files"""
        print("[6] Checking dead index entries...")

        for entry in sessions_index["entries"]:
            full_path = Path(entry["fullPath"])
            if not full_path.exists():
                self.dead_index_entries.append(entry["sessionId"])

        print(f"  Found {len(self.dead_index_entries)} dead index entries")
        print()

    def _check_d_drive_remnants(self) -> None:
        """Check for D:\\tmp\\claude remnants"""
        print("[7] Checking D: drive temp remnants...")

        d_tmp_claude = Path("D:/tmp/claude")
        d_tmp = Path("D:/tmp")

        if d_tmp_claude.exists():
            files = list(d_tmp_claude.rglob("*"))
            total_size = sum(f.stat().st_size for f in files if f.is_file())
            self.d_drive_remnants.append(str(d_tmp_claude))
            print(f"  [!] Found D:\\tmp\\claude with {len(files)} files ({self._format_size(total_size)})")
        else:
            print(f"  [OK] No D:\\tmp\\claude directory found")

        if d_tmp.exists() and d_tmp.is_dir():
            items = list(d_tmp.iterdir())
            if items:
                print(f"  [INFO] D:\\tmp contains {len(items)} items")

        print()

    def _print_summary(self) -> None:
        """Print comprehensive summary of findings"""
        print()
        print("=" * 70)
        print("AUDIT SUMMARY")
        print("=" * 70)
        print()

        # Calculate total reclaimable space
        total_size = 0

        # Orphaned UUID dirs
        uuid_size = sum(size for _, size in self.orphaned_uuid_dirs)
        total_size += uuid_size
        print(f"[ORPHANED] UUID Directories: {len(self.orphaned_uuid_dirs)} ({self._format_size(uuid_size)})")
        if self.orphaned_uuid_dirs[:5]:
            print("   Largest 5:")
            for session_id, size in self.orphaned_uuid_dirs[:5]:
                print(f"     • {session_id} - {self._format_size(size)}")

        # Orphaned .jsonl files
        jsonl_size = sum((self.project_root / f).stat().st_size for f in self.orphaned_jsonl if (self.project_root / f).exists())
        total_size += jsonl_size
        print(f"\n[ORPHANED] .jsonl Files: {len(self.orphaned_jsonl)} ({self._format_size(jsonl_size)})")

        # Stale scratchpads
        scratchpad_size = sum(
            sum(f.stat().st_size for f in (self.temp_scratchpad / sid).rglob("*") if f.is_file())
            for sid in self.stale_scratchpads
            if (self.temp_scratchpad / sid).exists()
        )
        total_size += scratchpad_size
        print(f"\n[STALE] Scratchpad Directories: {len(self.stale_scratchpads)} ({self._format_size(scratchpad_size)})")

        # Completed plans
        print(f"\n[ARCHIVAL] Completed Plans: {len(self.completed_plans)}")
        if self.completed_plans[:5]:
            print("   Top 5:")
            for plan in self.completed_plans[:5]:
                print(f"     • {plan}")

        # Team/task configs
        print(f"\n[TEAMS] Team Directories: {len(self.stale_teams)}")
        print(f"[TASKS] Task Directories: {len(self.stale_tasks)}")

        # Dead index entries
        print(f"\n[DEAD] Index Entries: {len(self.dead_index_entries)}")

        # D: drive remnants
        if self.d_drive_remnants:
            print(f"\n[D:DRIVE] Remnants: {len(self.d_drive_remnants)}")
            for remnant in self.d_drive_remnants:
                print(f"   • {remnant}")

        print()
        print("=" * 70)
        print(f"TOTAL RECLAIMABLE SPACE: {self._format_size(total_size)}")
        print("=" * 70)
        print()

        if self.dry_run:
            print("[DRY-RUN] This was a dry-run. No changes were made.")
            print("          Run with --fix to clean up (with confirmations)")
            print("          Run with --fix --yes for non-interactive cleanup (DANGEROUS!)")
        else:
            print("\n[FIX MODE] Proceeding with cleanup...")
            self._perform_cleanup()

    def _perform_cleanup(self) -> None:
        """Perform actual cleanup operations"""
        if not self.auto_confirm:
            print("\n[WARNING] This will permanently delete orphaned artifacts!")
            response = input("Continue? (yes/no): ").strip().lower()
            if response != "yes":
                print("[ABORTED] Cleanup aborted by user")
                return

        print("\n[CLEANUP] Starting cleanup...")

        # Clean orphaned UUID directories
        if self.orphaned_uuid_dirs:
            print(f"\n[DELETE] Deleting {len(self.orphaned_uuid_dirs)} orphaned UUID directories...")
            for session_id, size in self.orphaned_uuid_dirs:
                dir_path = self.project_root / session_id
                if dir_path.exists():
                    try:
                        shutil.rmtree(dir_path)
                        print(f"   [OK] Deleted {session_id} ({self._format_size(size)})")
                    except Exception as e:
                        print(f"   [ERROR] Failed to delete {session_id}: {e}")

        # Orphaned .jsonl files — DO NOT DELETE, re-index instead
        if self.orphaned_jsonl:
            print(f"\n[NOTE] {len(self.orphaned_jsonl)} orphaned .jsonl files found")
            print("       These should be RE-INDEXED, not deleted.")
            print("       Run: python scripts/repair-sessions-index.py --fix")

        # Clean stale scratchpads
        if self.stale_scratchpads:
            print(f"\n[DELETE] Deleting {len(self.stale_scratchpads)} stale scratchpad directories...")
            for session_id in self.stale_scratchpads:
                scratchpad_path = self.temp_scratchpad / session_id
                if scratchpad_path.exists():
                    try:
                        shutil.rmtree(scratchpad_path)
                        print(f"   [OK] Deleted scratchpad for {session_id}")
                    except Exception as e:
                        print(f"   [ERROR] Failed to delete scratchpad for {session_id}: {e}")

        # Archive completed plans
        if self.completed_plans:
            print(f"\n[ARCHIVE] Archiving {len(self.completed_plans)} completed plans...")
            archive_dir = self.plans_dir / "archive"
            archive_dir.mkdir(exist_ok=True)

            for plan_file in self.completed_plans:
                src = self.plans_dir / plan_file
                dst = archive_dir / plan_file
                if src.exists():
                    try:
                        shutil.move(str(src), str(dst))
                        print(f"   [OK] Archived {plan_file}")
                    except Exception as e:
                        print(f"   [ERROR] Failed to archive {plan_file}: {e}")

        # Clean D: drive remnants
        if self.d_drive_remnants:
            print(f"\n[DELETE] Cleaning D: drive remnants...")
            for remnant in self.d_drive_remnants:
                remnant_path = Path(remnant)
                if remnant_path.exists():
                    try:
                        shutil.rmtree(remnant_path)
                        print(f"   [OK] Deleted {remnant}")
                    except Exception as e:
                        print(f"   [ERROR] Failed to delete {remnant}: {e}")

        # Note: Dead index entries require manual index rebuild
        if self.dead_index_entries:
            print(f"\n[NOTE] {len(self.dead_index_entries)} dead index entries found")
            print("       These require manual repair via repair-sessions-index.py")

        print("\n[COMPLETE] Cleanup complete!")

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format bytes as human-readable size"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"


def main():
    parser = argparse.ArgumentParser(
        description="Audit and clean up orphaned artifacts in ~/.claude/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python audit-orphans.py              # Dry-run (report only)
  python audit-orphans.py --fix        # Interactive cleanup
  python audit-orphans.py --fix --yes  # Non-interactive cleanup (dangerous!)
        """
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Perform cleanup (default is dry-run)"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Auto-confirm all prompts (use with --fix, DANGEROUS!)"
    )

    args = parser.parse_args()

    auditor = OrphanAuditor(
        dry_run=not args.fix,
        auto_confirm=args.yes
    )
    auditor.run_audit()


if __name__ == "__main__":
    main()
