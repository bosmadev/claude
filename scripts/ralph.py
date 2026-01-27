#!/usr/bin/env python3
"""
Ralph Protocol - Unified Autonomous Agent Loop Implementation

This module implements the Ralph Protocol for managing autonomous Claude agent
loops with state persistence, hook integration, and multi-agent orchestration.

The protocol ensures:
- Agents complete their designated iterations before exit
- State is preserved across sessions via checkpointing
- Hook handlers inject proper context and block premature exits
- Multiple agents can be spawned concurrently with asyncio

Usage:
    ralph.py loop N M [task]  - Run N agents × M iterations
    ralph.py status           - Show current state
    ralph.py resume           - Resume from checkpoint
    ralph.py cleanup          - Clean state files
"""

import asyncio
import json
import os
import pty
import shutil
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class AgentStatus(str, Enum):
    """Status of an individual agent."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ReviewSpecialty(str, Enum):
    """Review agent specialties - dynamically discovered from agents/ directory."""
    SECURITY = "security"
    PERFORMANCE = "performance"
    A11Y = "a11y"
    ARCHITECTURE = "architecture"
    API = "api"
    DATABASE = "database"
    COMMIT = "commit"
    GENERAL = "general"


@dataclass
class AgentState:
    """State for a single agent instance."""
    agent_id: int
    current_iteration: int = 0
    max_iterations: int = 3
    status: str = AgentStatus.PENDING.value
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    ralph_complete: bool = False
    exit_signal: bool = False


@dataclass
class RalphState:
    """Complete state for Ralph Protocol execution."""
    session_id: str
    task: Optional[str] = None
    total_agents: int = 3
    max_iterations: int = 3
    agents: list = field(default_factory=list)
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    checkpoint_path: Optional[str] = None
    # Stale session detection fields
    phase: str = "implementation"  # implementation|review|complete
    process_pids: list = field(default_factory=list)  # PIDs for liveness check
    last_heartbeat: Optional[str] = None  # ISO timestamp of last activity

    def to_dict(self) -> dict:
        """Convert state to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "task": self.task,
            "total_agents": self.total_agents,
            "max_iterations": self.max_iterations,
            "agents": [asdict(a) if isinstance(a, AgentState) else a for a in self.agents],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "checkpoint_path": self.checkpoint_path,
            "phase": self.phase,
            "process_pids": self.process_pids,
            "last_heartbeat": self.last_heartbeat,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RalphState":
        """Create state from dictionary.

        Handles both formats:
        - Original RalphState format (agents as list)
        - guards.py format (agents as integer count)
        """
        # Handle agents field - can be int (count) or list (AgentState objects)
        agents_data = data.get("agents", [])
        if isinstance(agents_data, int):
            # guards.py format: agents is a count, create empty list
            agents = []
            total_agents = agents_data
        else:
            # Original format: agents is a list
            agents = [
                AgentState(**a) if isinstance(a, dict) else a
                for a in agents_data
            ]
            total_agents = data.get("total_agents", len(agents) or 3)

        # Handle camelCase vs snake_case keys (guards.py uses camelCase)
        return cls(
            session_id=data.get("session_id", "unknown"),
            task=data.get("task"),
            total_agents=total_agents,
            max_iterations=data.get("max_iterations") or data.get("maxIterations", 3),
            agents=agents,
            started_at=data.get("started_at") or data.get("startedAt"),
            completed_at=data.get("completed_at") or data.get("completedAt"),
            checkpoint_path=data.get("checkpoint_path") or data.get("planFile"),
            # Stale session detection fields with backward-compatible defaults
            phase=data.get("phase", "implementation"),
            process_pids=data.get("process_pids", []),
            last_heartbeat=data.get("last_heartbeat") or data.get("lastHeartbeat"),
        )


# =============================================================================
# Work-Stealing Queue
# =============================================================================

@dataclass
class QueueTask:
    """Task in the work-stealing queue."""
    id: str
    status: str = "pending"
    blocked_by: list = field(default_factory=list)
    claimed_by: Optional[str] = None
    iterations: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "blockedBy": self.blocked_by,
            "claimed_by": self.claimed_by,
            "iterations": self.iterations,
            "started_at": self.started_at,
            "completed_at": self.completed_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QueueTask":
        return cls(
            id=data["id"],
            status=data.get("status", "pending"),
            blocked_by=data.get("blockedBy", []),
            claimed_by=data.get("claimed_by"),
            iterations=data.get("iterations", 0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at")
        )


@dataclass
class TaskQueue:
    """Work-stealing task queue tied to a plan file."""
    plan_id: str
    plan_file: str
    created_at: str
    tasks: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "plan_file": self.plan_file,
            "created_at": self.created_at,
            "tasks": [t.to_dict() if isinstance(t, QueueTask) else t for t in self.tasks]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskQueue":
        return cls(
            plan_id=data["plan_id"],
            plan_file=data["plan_file"],
            created_at=data["created_at"],
            tasks=[QueueTask.from_dict(t) if isinstance(t, dict) else t for t in data.get("tasks", [])]
        )


class WorkStealingQueue:
    """
    File-based work-stealing queue with atomic task claiming.

    Location: {project}/.claude/task-queue-{plan-id}.json

    Uses file locking to prevent race conditions when multiple
    agents attempt to claim tasks simultaneously.
    """

    QUEUE_DIR = ".claude"
    LOCK_SUFFIX = ".lock"

    def __init__(self, plan_id: str, plan_file: str, base_dir: Optional[Path] = None):
        self.plan_id = plan_id
        self.plan_file = plan_file
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.queue_path = self.base_dir / self.QUEUE_DIR / f"task-queue-{plan_id}.json"
        self.lock_path = self.base_dir / self.QUEUE_DIR / f"task-queue-{plan_id}{self.LOCK_SUFFIX}"

    def _ensure_dir(self) -> None:
        """Ensure queue directory exists."""
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)

    def _acquire_lock(self) -> int:
        """Acquire file lock for atomic operations."""
        import fcntl
        self._ensure_dir()
        fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _release_lock(self, fd: int) -> None:
        """Release file lock."""
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def load(self) -> TaskQueue:
        """Load queue from file, creating if needed."""
        if self.queue_path.exists():
            try:
                with open(self.queue_path) as f:
                    return TaskQueue.from_dict(json.load(f))
            except (json.JSONDecodeError, KeyError):
                pass

        # Create new queue
        return TaskQueue(
            plan_id=self.plan_id,
            plan_file=self.plan_file,
            created_at=datetime.now().isoformat(),
            tasks=[]
        )

    def save(self, queue: TaskQueue) -> None:
        """Save queue to file."""
        self._ensure_dir()
        with open(self.queue_path, "w") as f:
            json.dump(queue.to_dict(), f, indent=2)

    def claim_next_task(self, agent_id: str) -> Optional[QueueTask]:
        """
        Atomically claim the next available task.

        A task is available if:
        - status == "pending"
        - claimed_by is None
        - all blockedBy tasks are completed

        Args:
            agent_id: ID of the agent claiming the task.

        Returns:
            The claimed QueueTask, or None if no tasks available.
        """
        fd = self._acquire_lock()
        try:
            queue = self.load()

            # Build set of completed task IDs
            completed_ids = {t.id for t in queue.tasks if t.status == "completed"}

            for task in queue.tasks:
                if task.status != "pending" or task.claimed_by:
                    continue

                # Check if all blockers are complete
                blockers_done = all(b in completed_ids for b in task.blocked_by)
                if not blockers_done:
                    continue

                # Claim the task
                task.claimed_by = agent_id
                task.status = "in_progress"
                task.started_at = datetime.now().isoformat()
                task.iterations += 1

                self.save(queue)
                return task

            return None

        finally:
            self._release_lock(fd)

    def complete_task(self, task_id: str) -> bool:
        """
        Mark a task as completed.

        Args:
            task_id: ID of the task to complete.

        Returns:
            True if task was found and completed, False otherwise.
        """
        fd = self._acquire_lock()
        try:
            queue = self.load()

            for task in queue.tasks:
                if task.id == task_id:
                    task.status = "completed"
                    task.completed_at = datetime.now().isoformat()
                    self.save(queue)
                    return True

            return False

        finally:
            self._release_lock(fd)

    def release_task(self, task_id: str) -> bool:
        """
        Release a task back to pending (e.g., on agent failure).

        Args:
            task_id: ID of the task to release.

        Returns:
            True if task was found and released, False otherwise.
        """
        fd = self._acquire_lock()
        try:
            queue = self.load()

            for task in queue.tasks:
                if task.id == task_id:
                    task.status = "pending"
                    task.claimed_by = None
                    self.save(queue)
                    return True

            return False

        finally:
            self._release_lock(fd)

    def add_task(self, task_id: str, blocked_by: list | None = None) -> QueueTask:
        """
        Add a new task to the queue.

        Args:
            task_id: Unique task identifier.
            blocked_by: List of task IDs that must complete first.

        Returns:
            The created QueueTask.
        """
        fd = self._acquire_lock()
        try:
            queue = self.load()

            task = QueueTask(
                id=task_id,
                status="pending",
                blocked_by=blocked_by or []
            )
            queue.tasks.append(task)
            self.save(queue)
            return task

        finally:
            self._release_lock(fd)

    def get_status(self) -> dict:
        """Get queue status summary."""
        queue = self.load()

        status_counts = {"pending": 0, "in_progress": 0, "completed": 0}
        for task in queue.tasks:
            status_counts[task.status] = status_counts.get(task.status, 0) + 1

        return {
            "plan_id": queue.plan_id,
            "total_tasks": len(queue.tasks),
            **status_counts
        }


# =============================================================================
# Review Agent Discovery
# =============================================================================

def discover_review_agents(agents_dir: str = "/usr/share/claude/agents") -> list[str]:
    """
    Auto-discover all *-reviewer.md agents in the agents directory.

    Args:
        agents_dir: Path to agents directory.

    Returns:
        List of specialty names (e.g., ["security", "performance", "a11y"]).
    """
    import glob as glob_module

    agents_path = Path(agents_dir)
    if not agents_path.exists():
        return ["general"]

    pattern = str(agents_path / "*-reviewer.md")
    agent_files = glob_module.glob(pattern)

    specialties = []
    for agent_file in agent_files:
        # Extract specialty from filename: security-reviewer.md -> security
        filename = Path(agent_file).stem  # security-reviewer
        specialty = filename.replace("-reviewer", "")
        specialties.append(specialty)

    return specialties if specialties else ["general"]


def assign_review_specialty(agent_id: int, specialties: list[str] | None = None) -> str:
    """
    Assign a review specialty to an agent using round-robin.

    Args:
        agent_id: Numeric agent identifier.
        specialties: List of available specialties (auto-discovered if None).

    Returns:
        Specialty name for this agent.
    """
    if specialties is None:
        specialties = discover_review_agents()

    if not specialties:
        return "general"

    return specialties[agent_id % len(specialties)]


def get_review_agent_path(specialty: str, agents_dir: str = "/usr/share/claude/agents") -> Optional[str]:
    """
    Get the full path to a review agent file.

    Args:
        specialty: The specialty name (e.g., "security").
        agents_dir: Path to agents directory.

    Returns:
        Full path to agent file, or None if not found.
    """
    agent_path = Path(agents_dir) / f"{specialty}-reviewer.md"
    return str(agent_path) if agent_path.exists() else None


class RalphProtocol:
    """
    Unified Ralph Protocol implementation for autonomous agent loops.

    Manages state persistence, hook integration, and agent orchestration
    to ensure reliable autonomous execution of Claude agents.
    """

    # New nested structure
    STATE_FILE = ".claude/ralph/state.json"
    ACTIVITY_LOG = ".claude/ralph/activity.log"
    CHECKPOINT_DIR = ".claude/ralph/checkpoints"

    # Legacy flat structure (for migration)
    LEGACY_STATE_FILE = ".claude/ralph-state.json"
    LEGACY_ACTIVITY_LOG = ".claude/ralph-activity.log"
    LEGACY_CHECKPOINT_DIR = ".claude/ralph-checkpoints"

    RALPH_COMPLETE_SIGNAL = "RALPH_COMPLETE"
    EXIT_SIGNAL = "EXIT_SIGNAL"

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize Ralph Protocol.

        Args:
            base_dir: Base directory for state files. Defaults to current directory.
        """
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.state_path = self.base_dir / self.STATE_FILE
        self.activity_log_path = self.base_dir / self.ACTIVITY_LOG
        self.checkpoint_dir = self.base_dir / self.CHECKPOINT_DIR
        self._state_lock = asyncio.Lock()  # Prevent concurrent state access

        # Migrate legacy files on initialization
        self._migrate_legacy_files()

    def _migrate_legacy_files(self) -> None:
        """Migrate legacy flat structure to nested .claude/ralph/."""
        # Core Ralph file migrations
        migrations = [
            (self.LEGACY_STATE_FILE, self.STATE_FILE),
            (self.LEGACY_ACTIVITY_LOG, self.ACTIVITY_LOG),
        ]
        for legacy, new in migrations:
            legacy_path = self.base_dir / legacy
            new_path = self.base_dir / new
            if legacy_path.exists() and not new_path.exists():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                legacy_path.rename(new_path)

        # Migrate checkpoint directory
        legacy_cp = self.base_dir / self.LEGACY_CHECKPOINT_DIR
        new_cp = self.base_dir / self.CHECKPOINT_DIR
        if legacy_cp.exists() and not new_cp.exists():
            new_cp.parent.mkdir(parents=True, exist_ok=True)
            legacy_cp.rename(new_cp)

        # Migrate guardian files to .claude/ralph/guardian/
        guardian_migrations = [
            (".claude/guardian-config.json", ".claude/ralph/guardian/config.json"),
            (".claude/plan-digest.json", ".claude/ralph/guardian/digest.json"),
            (".claude/guardian-log.json", ".claude/ralph/guardian/log.json"),
            (".claude/guardian-counter", ".claude/ralph/guardian/counter"),
        ]
        for legacy, new in guardian_migrations:
            legacy_path = self.base_dir / legacy
            new_path = self.base_dir / new
            if legacy_path.exists() and not new_path.exists():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                legacy_path.rename(new_path)

    # =========================================================================
    # State Management
    # =========================================================================

    def state_exists(self) -> bool:
        """Check if ralph-state.json exists."""
        return self.state_path.exists()

    def read_state(self) -> Optional[RalphState]:
        """
        Read and parse the current Ralph state from JSON.

        Returns:
            RalphState object if state exists, None otherwise.
        """
        if not self.state_exists():
            return None

        try:
            with open(self.state_path, 'r') as f:
                data = json.load(f)
            return RalphState.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            self.log_activity(f"Error reading state: {e}", level="ERROR")
            return None

    def write_state(self, state: RalphState) -> bool:
        """
        Write Ralph state to JSON file.

        Args:
            state: RalphState object to persist.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Ensure .claude directory exists
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_path, 'w') as f:
                json.dump(state.to_dict(), f, indent=2)
            self.log_activity(f"State written: {state.session_id}")
            return True
        except IOError as e:
            self.log_activity(f"Error writing state: {e}", level="ERROR")
            return False

    def create_checkpoint(self, state: RalphState) -> Optional[str]:
        """
        Create a checkpoint of the current state.

        Args:
            state: Current state to checkpoint.

        Returns:
            Checkpoint path if successful, None otherwise.
        """
        self.checkpoint_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_path = self.checkpoint_dir / f"checkpoint_{state.session_id}_{timestamp}.json"

        try:
            with open(checkpoint_path, 'w') as f:
                json.dump(state.to_dict(), f, indent=2)
            state.checkpoint_path = str(checkpoint_path)
            self.log_activity(f"Checkpoint created: {checkpoint_path}")
            return str(checkpoint_path)
        except IOError as e:
            self.log_activity(f"Error creating checkpoint: {e}", level="ERROR")
            return None

    def restore_from_checkpoint(self, checkpoint_path: str) -> Optional[RalphState]:
        """
        Restore state from a checkpoint file.

        Args:
            checkpoint_path: Path to checkpoint file.

        Returns:
            Restored RalphState if successful, None otherwise.
        """
        try:
            with open(checkpoint_path, 'r') as f:
                data = json.load(f)
            state = RalphState.from_dict(data)
            self.log_activity(f"Restored from checkpoint: {checkpoint_path}")
            return state
        except (IOError, json.JSONDecodeError) as e:
            self.log_activity(f"Error restoring checkpoint: {e}", level="ERROR")
            return None

    # =========================================================================
    # Transcript and Signal Parsing
    # =========================================================================

    def read_transcript(self, stdin_content: Optional[str] = None) -> dict:
        """
        Parse hook stdin content for transcript data.

        Args:
            stdin_content: Raw stdin content from hook. If None, reads from sys.stdin.

        Returns:
            Parsed transcript dictionary with messages and context.
        """
        if stdin_content is None:
            if sys.stdin.isatty():
                return {"messages": [], "context": {}}
            stdin_content = sys.stdin.read()

        if not stdin_content.strip():
            return {"messages": [], "context": {}}

        try:
            data = json.loads(stdin_content)
            return {
                "messages": data.get("messages", []),
                "context": data.get("context", {}),
                "raw": data
            }
        except json.JSONDecodeError:
            # Fallback: treat as plain text transcript
            return {
                "messages": [{"role": "unknown", "content": stdin_content}],
                "context": {},
                "raw": stdin_content
            }

    def check_completion(self, transcript: dict) -> bool:
        """
        Verify if RALPH_COMPLETE signal is present in transcript.

        Args:
            transcript: Parsed transcript dictionary.

        Returns:
            True if RALPH_COMPLETE signal found, False otherwise.
        """
        messages = transcript.get("messages", [])
        raw = transcript.get("raw", "")

        # Check in messages
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and self.RALPH_COMPLETE_SIGNAL in content:
                return True

        # Check in raw content
        if isinstance(raw, str) and self.RALPH_COMPLETE_SIGNAL in raw:
            return True

        return False

    def should_exit(self, transcript: dict) -> bool:
        """
        Verify if EXIT_SIGNAL is present in transcript.

        Args:
            transcript: Parsed transcript dictionary.

        Returns:
            True if EXIT_SIGNAL found, False otherwise.
        """
        messages = transcript.get("messages", [])
        raw = transcript.get("raw", "")

        # Check in messages
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str) and self.EXIT_SIGNAL in content:
                return True

        # Check in raw content
        if isinstance(raw, str) and self.EXIT_SIGNAL in raw:
            return True

        return False

    # =========================================================================
    # Logging
    # =========================================================================

    def log_activity(self, message: str, level: str = "INFO") -> None:
        """
        Append activity entry to ralph-activity.log.

        Args:
            message: Log message.
            level: Log level (INFO, WARN, ERROR, DEBUG).
        """
        timestamp = datetime.now().isoformat()
        log_entry = f"[{timestamp}] [{level}] {message}\n"

        try:
            with open(self.activity_log_path, 'a') as f:
                f.write(log_entry)
        except IOError:
            # Silently fail logging - don't break execution
            pass

    # =========================================================================
    # Git State Detection
    # =========================================================================

    def _detect_unpushed_commits(self) -> tuple[bool, int, str]:
        """
        Detect if there are unpushed commits in the current branch.

        Returns:
            Tuple of (has_unpushed: bool, count: int, branch: str).
        """
        try:
            # Get current branch name
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self.base_dir),
                timeout=10
            )
            if result.returncode != 0:
                return (False, 0, "")

            branch = result.stdout.strip()
            if not branch or branch == "HEAD":
                # Detached HEAD state
                return (False, 0, "HEAD")

            # Check if branch has upstream
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
                capture_output=True,
                text=True,
                cwd=str(self.base_dir),
                timeout=10
            )

            if result.returncode != 0:
                # No upstream configured - check if any remote exists
                result = subprocess.run(
                    ["git", "remote"],
                    capture_output=True,
                    text=True,
                    cwd=str(self.base_dir),
                    timeout=10
                )
                if result.returncode != 0 or not result.stdout.strip():
                    # No remotes configured - local-only repo, allow exit
                    return (False, 0, branch)

                # Has remote but no tracking - count unpushed commits
                result = subprocess.run(
                    ["git", "rev-list", "--count", branch, "--not", "--remotes"],
                    capture_output=True,
                    text=True,
                    cwd=str(self.base_dir),
                    timeout=10
                )
                if result.returncode == 0:
                    count = int(result.stdout.strip())
                    if count > 0:
                        return (True, count, branch)
                return (False, 0, branch)

            upstream = result.stdout.strip()

            # Count commits ahead of upstream
            result = subprocess.run(
                ["git", "rev-list", "--count", f"{upstream}..HEAD"],
                capture_output=True,
                text=True,
                cwd=str(self.base_dir),
                timeout=10
            )

            if result.returncode != 0:
                return (False, 0, branch)

            count = int(result.stdout.strip())
            return (count > 0, count, branch)

        except (subprocess.TimeoutExpired, subprocess.SubprocessError, ValueError) as e:
            self.log_activity(f"Error detecting unpushed commits: {e}", level="WARN")
            return (False, 0, "")

    # =========================================================================
    # Stale Session Detection
    # =========================================================================

    # Thresholds for stale session detection
    STALE_SESSION_HOURS = 4  # Sessions older than this are considered stale
    STALE_SESSION_STARTUP_HOURS = 24  # More lenient threshold for session start cleanup

    def _check_process_alive(self, pid: int) -> bool:
        """
        Check if a process is alive using /proc filesystem (Linux).

        Args:
            pid: Process ID to check.

        Returns:
            True if process exists and is a Claude process, False otherwise.
        """
        try:
            # Check if process exists
            os.kill(pid, 0)  # Signal 0 = check existence only
            # Verify it's a Claude process by checking /proc/PID/cmdline
            cmdline_path = Path(f"/proc/{pid}/cmdline")
            if cmdline_path.exists():
                cmdline = cmdline_path.read_text()
                return 'claude' in cmdline.lower()
            return True  # Process exists but can't verify cmdline
        except (OSError, PermissionError):
            return False

    def _check_session_stale(self, started_at: str, threshold_hours: float = None) -> tuple:
        """
        Check if a session is stale based on age.

        Args:
            started_at: ISO timestamp string of session start.
            threshold_hours: Hours threshold (defaults to STALE_SESSION_HOURS).

        Returns:
            Tuple of (is_stale: bool, age_hours: float, reason: str).
        """
        if threshold_hours is None:
            threshold_hours = self.STALE_SESSION_HOURS

        try:
            # Parse ISO timestamp
            start_time = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            # Handle timezone-naive vs timezone-aware
            now = datetime.now()
            if start_time.tzinfo is not None:
                now = datetime.now(start_time.tzinfo)
            else:
                start_time = start_time.replace(tzinfo=None)

            age = now - start_time
            age_hours = age.total_seconds() / 3600

            if age_hours > threshold_hours:
                return (True, age_hours, f"Session age {age_hours:.1f}h exceeds {threshold_hours}h threshold")
            return (False, age_hours, "Session within age threshold")
        except (ValueError, AttributeError, TypeError) as e:
            # Can't parse timestamp, don't consider stale (fail-safe)
            return (False, 0, f"Could not parse timestamp: {e}")

    def _check_processes_alive(self, process_pids: list) -> tuple:
        """
        Check if any tracked processes are still running.

        Args:
            process_pids: List of PIDs to check.

        Returns:
            Tuple of (any_alive: bool, alive_count: int, dead_count: int).
        """
        if not process_pids:
            return (False, 0, 0)  # No PIDs tracked = can't determine

        alive_count = 0
        dead_count = 0

        for pid in process_pids:
            if self._check_process_alive(pid):
                alive_count += 1
            else:
                dead_count += 1

        return (alive_count > 0, alive_count, dead_count)

    def _check_all_tasks_completed(self) -> bool:
        """
        Check if all tasks in task list are completed.

        This handles the case where work is done in the main conversation
        without spawning agents - if all tasks show completed, allow exit.

        Returns:
            True if task list exists and all tasks are completed.
        """
        try:
            # Find task queue file for this project
            state = self.read_state()
            if not state:
                return False

            # Look for task queue file
            # checkpoint_path stores the plan file path (from planFile in JSON)
            plan_file = state.checkpoint_path or ""
            if plan_file:
                plan_name = Path(plan_file).stem
                queue_file = self.base_dir / ".claude" / f"task-queue-{plan_name}.json"
            else:
                # Try to find any task queue file
                claude_dir = self.base_dir / ".claude"
                if not claude_dir.exists():
                    return False
                queue_files = list(claude_dir.glob("task-queue-*.json"))
                if not queue_files:
                    return False
                queue_file = queue_files[0]  # Use most recent

            if not queue_file.exists():
                return False

            with open(queue_file, 'r') as f:
                queue_data = json.load(f)

            tasks = queue_data.get("tasks", [])
            if not tasks:
                return False

            # Check if all tasks are completed
            for task in tasks:
                status = task.get("status", "pending")
                if status not in ("completed", "deleted"):
                    return False

            return True

        except (json.JSONDecodeError, OSError, AttributeError):
            return False

    # =========================================================================
    # Hook Handlers
    # =========================================================================

    def handle_hook_stop(self, stdin_content: Optional[str] = None) -> dict:
        """
        Hook-stop handler: Block exit unless Ralph loop is complete OR session is stale.

        Decision tree:
        1. No state file → Allow exit
        2. State file exists:
            a. Session age > 4h → Auto-cleanup + Allow (stale)
            b. No running processes → Auto-cleanup + Allow (orphaned)
            c. Phase == complete → Cleanup + Allow
            d. Valid signals in transcript → Cleanup + Allow
            e. Otherwise → Block with reminder

        Args:
            stdin_content: Raw stdin from hook.

        Returns:
            Hook response dictionary with decision.
        """
        # CHECK 1: No state file = allow exit
        if not self.state_exists():
            return {"decision": "approve", "reason": "No active Ralph session"}

        # Read raw state file to check all fields
        try:
            with open(self.state_path, 'r') as f:
                raw_state = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"decision": "approve", "reason": "State file unreadable, allowing exit"}

        # CHECK 2: Session age > threshold = stale session (auto-cleanup)
        started_at = raw_state.get("startedAt") or raw_state.get("started_at")
        if started_at:
            is_stale, age_hours, stale_reason = self._check_session_stale(started_at)
            if is_stale:
                self.log_activity(f"Exit allowed: {stale_reason}", level="WARN")
                cleanup_results = self.cleanup_ralph_session(keep_activity_log=True)
                return {
                    "decision": "approve",
                    "reason": f"Stale session detected (age: {age_hours:.1f}h)",
                    "cleanup": cleanup_results,
                    "stale_reason": "session_age"
                }

        # CHECK 3: Process liveness (if PIDs tracked)
        process_pids = raw_state.get("process_pids", [])
        if process_pids:
            any_alive, alive_count, dead_count = self._check_processes_alive(process_pids)
            if not any_alive:
                self.log_activity(
                    f"Exit allowed: No running processes (0/{len(process_pids)} alive)",
                    level="WARN"
                )
                cleanup_results = self.cleanup_ralph_session(keep_activity_log=True)
                return {
                    "decision": "approve",
                    "reason": f"No running Ralph processes ({dead_count} dead PIDs)",
                    "cleanup": cleanup_results,
                    "stale_reason": "no_processes"
                }

        # CHECK 4: Phase completion (primary completion check)
        phase = raw_state.get("phase", "")
        completed_at = raw_state.get("completedAt") or raw_state.get("completed_at")

        if phase == "complete" or completed_at:
            self.log_activity("Exit allowed: Ralph loop marked complete in state file")
            cleanup_results = self.cleanup_ralph_session(keep_activity_log=True)
            return {
                "decision": "approve",
                "reason": "Ralph protocol complete",
                "cleanup": cleanup_results
            }

        # CHECK 5: Transcript signals (fallback for backward compatibility)
        transcript = self.read_transcript(stdin_content)
        has_complete = self.check_completion(transcript)
        has_exit = self.should_exit(transcript)

        # CHECK 6: Unpushed commits check (before allowing RALPH_COMPLETE)
        # If agent signals completion but hasn't pushed, block exit
        if has_complete:
            has_unpushed, unpushed_count, branch = self._detect_unpushed_commits()
            if has_unpushed:
                self.log_activity(
                    f"Exit blocked: {unpushed_count} unpushed commit(s) on branch '{branch}'",
                    level="WARN"
                )
                return {
                    "decision": "block",
                    "reason": f"Unpushed commits detected ({unpushed_count} on '{branch}')",
                    "inject_message": f"""🚫 UNPUSHED COMMITS DETECTED

You have {unpushed_count} unpushed commit(s) on branch '{branch}'.

Before completing the Ralph session, you MUST push your commits:

```bash
git push origin {branch}
```

After pushing, output the completion signals again:

RALPH_COMPLETE
EXIT_SIGNAL
"""
                }

        if has_complete and has_exit:
            self.log_activity("Exit allowed: Both signals present in transcript")
            cleanup_results = self.cleanup_ralph_session(keep_activity_log=True)
            return {
                "decision": "approve",
                "reason": "Ralph protocol complete",
                "cleanup": cleanup_results
            }

        # CHECK 7: All tasks completed (work done in main conversation without agents)
        # Still require completion signals, but inject prompt to output them
        all_tasks_done = self._check_all_tasks_completed()
        if all_tasks_done and not (has_complete and has_exit):
            self.log_activity("All tasks done but missing completion signals - injecting prompt")
            # Mark phase complete in state
            try:
                if self.state_path.exists():
                    with open(self.state_path, 'r') as f:
                        state_data = json.load(f)
                    state_data["phase"] = "complete"
                    state_data["completedAt"] = datetime.now(timezone.utc).isoformat()
                    with open(self.state_path, 'w') as f:
                        json.dump(state_data, f, indent=2)
            except (json.JSONDecodeError, OSError):
                pass

            return {
                "decision": "block",
                "reason": "All tasks completed - output completion signals",
                "inject_message": f"""✅ ALL TASKS COMPLETED

All tasks in the task list are marked complete. Output the Ralph completion signals NOW:

RALPH_COMPLETE
EXIT_SIGNAL

This will properly close the Ralph session."""
            }

        # BLOCK: Valid active session, require completion
        state = self.read_state()
        missing = []
        if not has_complete:
            missing.append(self.RALPH_COMPLETE_SIGNAL)
        if not has_exit:
            missing.append(self.EXIT_SIGNAL)

        self.log_activity(f"Exit blocked: phase={phase}, missing signals: {missing}")

        return {
            "decision": "block",
            "reason": f"Ralph protocol requires completion (phase={phase})",
            "inject_message": self._generate_continuation_prompt(state) if state else ""
        }

    def handle_hook_pretool(self, stdin_content: Optional[str] = None) -> dict:
        """
        Hook-pretool handler: Inject protocol context if state missing.

        Args:
            stdin_content: Raw stdin from hook.

        Returns:
            Hook response with optional context injection.
        """
        state = self.read_state()

        if state is None:
            return {"inject_context": None}

        # Build context for tool execution
        context = {
            "ralph_active": True,
            "session_id": state.session_id,
            "task": state.task,
            "agents_complete": sum(
                1 for a in state.agents
                if (a.status if isinstance(a, AgentState) else a.get("status")) == AgentStatus.COMPLETED.value
            ),
            "total_agents": state.total_agents
        }

        return {"inject_context": context}

    def handle_hook_user_prompt(self, stdin_content: Optional[str] = None) -> dict:
        """
        Hook-user-prompt handler: Prepend Ralph instructions.

        Args:
            stdin_content: Raw stdin from hook.

        Returns:
            Hook response with optional prompt prepend.
        """
        state = self.read_state()

        if state is None:
            return {"prepend": None}

        instructions = self._generate_ralph_instructions(state)
        return {"prepend": instructions}

    def handle_hook_session_start(self, stdin_content: Optional[str] = None) -> dict:
        """
        Hook-session-start handler: Clean orphaned sessions, restore from checkpoint,
        and provide Serena integration context.

        Orphan detection:
        1. Sessions older than 24 hours → cleanup
        2. Sessions with no running processes → cleanup
        3. Sessions marked complete but not cleaned → cleanup

        Args:
            stdin_content: Raw stdin from hook.

        Returns:
            Hook response with restoration status and Serena context.
        """
        response = {"restored": False}

        # ORPHAN DETECTION: Clean stale sessions at startup
        if self.state_exists():
            try:
                with open(self.state_path, 'r') as f:
                    raw_state = json.load(f)

                should_cleanup = False
                cleanup_reason = None

                # Check 1: Session age > 24h = definitely orphaned
                started_at = raw_state.get("startedAt") or raw_state.get("started_at")
                if started_at:
                    is_stale, age_hours, _ = self._check_session_stale(
                        started_at,
                        threshold_hours=self.STALE_SESSION_STARTUP_HOURS
                    )
                    if is_stale:
                        should_cleanup = True
                        cleanup_reason = f"orphaned (age: {age_hours:.1f}h > 24h threshold)"

                # Check 2: No running processes (if PIDs tracked)
                if not should_cleanup:
                    process_pids = raw_state.get("process_pids", [])
                    if process_pids:
                        any_alive, _, _ = self._check_processes_alive(process_pids)
                        if not any_alive:
                            should_cleanup = True
                            cleanup_reason = f"no running processes (PIDs: {process_pids})"

                # Check 3: Session marked complete but not cleaned
                if not should_cleanup:
                    phase = raw_state.get("phase", "")
                    completed_at = raw_state.get("completedAt") or raw_state.get("completed_at")
                    if phase == "complete" or completed_at:
                        should_cleanup = True
                        cleanup_reason = "session marked complete but not cleaned"

                # Perform cleanup if needed
                if should_cleanup:
                    self.log_activity(
                        f"Session start: Cleaning orphaned session ({cleanup_reason})",
                        level="WARN"
                    )
                    cleanup_results = self.cleanup_ralph_session(keep_activity_log=True)
                    response["cleaned_orphaned_session"] = {
                        "reason": cleanup_reason,
                        "cleanup": cleanup_results
                    }

            except (json.JSONDecodeError, OSError):
                # State file corrupted, clean it up
                self.log_activity("Session start: Cleaning corrupted state file", level="WARN")
                self.cleanup_ralph_session(keep_activity_log=True)
                response["cleaned_orphaned_session"] = {"reason": "corrupted state file"}

        # CHECKPOINT RESTORATION (only if no active state)
        state = self.read_state()
        if state is None:
            if self.checkpoint_dir.exists():
                checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
                if checkpoints:
                    latest = checkpoints[-1]
                    restored = self.restore_from_checkpoint(str(latest))
                    if restored:
                        self.write_state(restored)
                        response = {
                            "restored": True,
                            "checkpoint": str(latest),
                            "state": restored.to_dict()
                        }

        # Generate Serena integration context
        serena_context = self._generate_serena_context()
        if serena_context:
            response["hookSpecificOutput"] = {
                "hookEventName": "SessionStart",
                "additionalContext": serena_context
            }

        return response

    def _generate_serena_context(self) -> str:
        """
        Generate Serena integration context for session start.

        Returns:
            Serena workflow guidance string if .serena/ exists, empty otherwise.
        """
        project_root = Path.cwd()
        serena_config = project_root / ".serena"

        if serena_config.exists():
            return f"""
## Serena Integration Active

Project configured: `{project_root}`

### Recommended Serena Workflow:
1. **Code exploration**: Use `mcp__serena__get_symbols_overview` before reading files
2. **Symbol search**: Use `mcp__serena__find_symbol` instead of Grep for functions/classes
3. **Reference finding**: Use `mcp__serena__find_referencing_symbols` for impact analysis
4. **Code editing**: Use `mcp__serena__replace_symbol_body` for precise edits
5. **Memory**: Use `mcp__serena__write_memory` for architectural decisions

### Serena vs Native Tools:
| Task | Use Serena | Use Native |
|------|------------|------------|
| Find function by name | `find_symbol` | - |
| Find string in file | - | `Grep` |
| Get file structure | `get_symbols_overview` | - |
| Read full file | - | `Read` |
| Edit symbol | `replace_symbol_body` | - |
| Edit specific lines | - | `Edit` |
"""
        else:
            return """
## Serena Available

Serena provides LSP-powered semantic code analysis. To enable:
- Run `mcp__serena__onboarding` for initial setup
- Or `mcp__serena__activate_project` if already configured
"""

    # =========================================================================
    # Serena Shell Command TTY Passthrough
    # =========================================================================

    def handle_serena_shell_ask(self, tool_input: dict) -> Optional[bool]:
        """
        Handle mcp__serena__execute_shell_command ask permission for subagents.

        When a Ralph subagent triggers execute_shell_command, this forwards
        the approval request to the main TTY session for user decision.

        Args:
            tool_input: The tool input containing the command.

        Returns:
            True if approved, False if denied, None to use default ask flow.
        """
        # Only intercept if we're in a subagent context
        if not os.environ.get("RALPH_SUBAGENT"):
            return None

        command = tool_input.get("command", "")
        main_tty = os.environ.get("RALPH_MAIN_TTY", "/dev/tty")

        try:
            # Write prompt to main TTY
            with open(main_tty, 'w') as tty:
                tty.write(f"\n[Ralph Subagent Request]\n")
                tty.write(f"Command: {command}\n")
                tty.write(f"Approve? [y/N]: ")
                tty.flush()

            # Read response from main TTY
            with open(main_tty, 'r') as tty:
                response = tty.readline().strip().lower()

            approved = response in ('y', 'yes')
            self.log_activity(
                f"Serena shell command {'approved' if approved else 'denied'}: {command}"
            )
            return approved

        except (IOError, OSError) as e:
            self.log_activity(f"TTY passthrough failed: {e}", level="ERROR")
            return None  # Fall back to default ask flow

    # =========================================================================
    # Agent Orchestration
    # =========================================================================

    def spawn_with_pty(self, command: list, session_token: str = "") -> tuple:
        """
        Spawn a subprocess with PTY allocation for TTY access.

        This enables subagents to have access to a real TTY, allowing
        "ask" permissions to work properly instead of auto-denying.

        Args:
            command: Command and arguments to execute.
            session_token: Optional session token for security validation.

        Returns:
            Tuple of (process, master_fd) for PTY communication.
        """
        master, slave = pty.openpty()

        env = os.environ.copy()
        env["RALPH_SUBAGENT"] = "true"
        if session_token:
            env["RALPH_SESSION_TOKEN"] = session_token
        # Inherit parent's permission mode
        env["CLAUDE_CODE_PERMISSION_MODE"] = os.environ.get(
            "CLAUDE_CODE_PERMISSION_MODE", "acceptEdits"
        )

        proc = subprocess.Popen(
            command,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True
        )
        os.close(slave)
        return proc, master

    async def spawn_agent(self, agent_state: AgentState, task: Optional[str] = None) -> bool:
        """
        Spawn a single Claude agent asynchronously.

        Args:
            agent_state: State object for this agent.
            task: Optional task description.

        Returns:
            True if agent completed successfully, False otherwise.
        """
        agent_state.status = AgentStatus.RUNNING.value
        agent_state.started_at = datetime.now().isoformat()

        # Update main state (with lock to prevent race conditions)
        async with self._state_lock:
            state = self.read_state()
            if state:
                for i, a in enumerate(state.agents):
                    a_id = a.agent_id if isinstance(a, AgentState) else a.get("agent_id")
                    if a_id == agent_state.agent_id:
                        state.agents[i] = agent_state
                        break
                self.write_state(state)
                self.create_checkpoint(state)

        self.log_activity(f"Agent {agent_state.agent_id} started")

        spawned_pid = None  # Track PID for cleanup on completion/failure
        try:
            # Build Claude command - use simple subprocess with pipe
            prompt = self._build_agent_prompt(agent_state, task)

            env = os.environ.copy()
            env["RALPH_SUBAGENT"] = "true"
            env["RALPH_AGENT_ID"] = str(agent_state.agent_id)
            env["CLAUDE_CODE_PERMISSION_MODE"] = os.environ.get(
                "CLAUDE_CODE_PERMISSION_MODE", "acceptEdits"
            )

            # Run Claude agent using asyncio subprocess for proper async handling
            loop = asyncio.get_event_loop()

            # Use asyncio.create_subprocess_exec for non-blocking execution
            proc = await asyncio.create_subprocess_exec(
                "claude", "--print", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            # Track PID for liveness detection
            spawned_pid = proc.pid
            if spawned_pid:
                async with self._state_lock:
                    state = self.read_state()
                    if state:
                        if spawned_pid not in state.process_pids:
                            state.process_pids.append(spawned_pid)
                        state.last_heartbeat = datetime.now().isoformat()
                        self.write_state(state)
                self.log_activity(f"Agent {agent_state.agent_id} spawned with PID {spawned_pid}")

            # Wait for completion with 15-minute timeout per agent
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=900  # 15 minutes
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                agent_state.status = AgentStatus.FAILED.value
                self.log_activity(f"Agent {agent_state.agent_id} timed out after 15 minutes", level="ERROR")
                agent_state.completed_at = datetime.now().isoformat()
                return False

            if proc.returncode == 0:
                agent_state.status = AgentStatus.COMPLETED.value
                agent_state.ralph_complete = True
                agent_state.exit_signal = True
                self.log_activity(f"Agent {agent_state.agent_id} completed successfully")
            else:
                agent_state.status = AgentStatus.FAILED.value
                error_msg = stderr.decode().strip() if stderr else stdout.decode().strip()[:200]
                self.log_activity(f"Agent {agent_state.agent_id} failed (exit {proc.returncode}): {error_msg}", level="ERROR")

        except Exception as e:
            agent_state.status = AgentStatus.FAILED.value
            self.log_activity(f"Agent {agent_state.agent_id} error: {e}", level="ERROR")

        agent_state.completed_at = datetime.now().isoformat()

        # Update final state (with lock to prevent race conditions)
        async with self._state_lock:
            state = self.read_state()
            if state:
                for i, a in enumerate(state.agents):
                    a_id = a.agent_id if isinstance(a, AgentState) else a.get("agent_id")
                    if a_id == agent_state.agent_id:
                        state.agents[i] = agent_state
                        break
                # Remove PID from tracking list (process completed)
                if spawned_pid and spawned_pid in state.process_pids:
                    state.process_pids.remove(spawned_pid)
                state.last_heartbeat = datetime.now().isoformat()
                self.write_state(state)

        return agent_state.status == AgentStatus.COMPLETED.value

    async def run_loop(
        self,
        num_agents: int,
        max_iterations: int,
        task: Optional[str] = None,
        review_agents: int = 5,
        review_iterations: int = 2,
        skip_review: bool = False,
        plan_file: Optional[str] = None
    ) -> RalphState:
        """
        Run the full Ralph loop with N agents × M iterations.

        Args:
            num_agents: Number of concurrent agents.
            max_iterations: Maximum iterations per agent.
            task: Optional task description.
            review_agents: Number of review agents (default 5).
            review_iterations: Iterations per review agent (default 2).
            skip_review: Whether to skip post-implementation review.
            plan_file: Path to the plan file being executed.

        Returns:
            Final RalphState after execution.
        """
        # Initialize state
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        agents = [
            AgentState(
                agent_id=i,
                max_iterations=max_iterations,
                status=AgentStatus.PENDING.value
            )
            for i in range(num_agents)
        ]

        state = RalphState(
            session_id=session_id,
            task=task,
            total_agents=num_agents,
            max_iterations=max_iterations,
            agents=agents,
            started_at=datetime.now().isoformat()
        )

        self.write_state(state)
        self.create_checkpoint(state)
        self.log_activity(f"Ralph loop started: {num_agents} agents × {max_iterations} iterations")

        # Spawn agents concurrently
        tasks = [
            self.spawn_agent(agent, task)
            for agent in agents
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Update final state
        state = self.read_state()
        if state:
            state.completed_at = datetime.now().isoformat()
            self.write_state(state)

        successful = sum(1 for r in results if r is True)
        self.log_activity(f"Ralph loop completed: {successful}/{num_agents} agents successful")

        return state

    # =========================================================================
    # CLI Commands
    # =========================================================================

    def cmd_status(self) -> None:
        """Show current Ralph state."""
        state = self.read_state()

        if state is None:
            print("No active Ralph session")
            return

        print(f"Session ID: {state.session_id}")
        print(f"Task: {state.task or 'None'}")
        print(f"Started: {state.started_at}")
        print(f"Agents: {state.total_agents} × {state.max_iterations} iterations")
        print()
        print("Agent Status:")
        for agent in state.agents:
            if isinstance(agent, AgentState):
                a = agent
            else:
                a = AgentState(**agent)
            status_icon = {
                AgentStatus.PENDING.value: "⏳",
                AgentStatus.RUNNING.value: "🔄",
                AgentStatus.COMPLETED.value: "✅",
                AgentStatus.FAILED.value: "❌"
            }.get(a.status, "❓")
            print(f"  Agent {a.agent_id}: {status_icon} {a.status} (iteration {a.current_iteration}/{a.max_iterations})")

    def cmd_resume(self) -> None:
        """Resume from latest checkpoint."""
        if not self.checkpoint_dir.exists():
            print("No checkpoints found")
            return

        checkpoints = sorted(self.checkpoint_dir.glob("checkpoint_*.json"))
        if not checkpoints:
            print("No checkpoints found")
            return

        latest = checkpoints[-1]
        print(f"Resuming from: {latest}")

        state = self.restore_from_checkpoint(str(latest))
        if state:
            self.write_state(state)
            print(f"Restored session: {state.session_id}")

            # Find incomplete agents and resume
            incomplete = [
                AgentState(**a) if isinstance(a, dict) else a
                for a in state.agents
                if (a.get("status") if isinstance(a, dict) else a.status) != AgentStatus.COMPLETED.value
            ]

            if incomplete:
                print(f"Resuming {len(incomplete)} incomplete agents...")
                asyncio.run(self._resume_agents(incomplete, state.task))
            else:
                print("All agents already completed")

    async def _resume_agents(self, agents: list, task: Optional[str]) -> None:
        """Resume incomplete agents."""
        tasks = [self.spawn_agent(agent, task) for agent in agents]
        await asyncio.gather(*tasks, return_exceptions=True)

    def cleanup_ralph_session(self, keep_activity_log: bool = True) -> dict:
        """
        Clean up Ralph session files after successful completion.

        Args:
            keep_activity_log: If True, preserve activity log for debugging.

        Returns:
            Dictionary with cleanup results.
        """
        results = {"deleted": [], "preserved": [], "errors": []}

        def safe_remove(path: Path) -> bool:
            try:
                if path.exists():
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                    results["deleted"].append(str(path))
                    return True
            except OSError as e:
                results["errors"].append(f"{path}: {e}")
            return False

        # Always remove state file
        safe_remove(self.state_path)

        # Activity log based on config
        if keep_activity_log:
            if self.activity_log_path.exists():
                results["preserved"].append(str(self.activity_log_path))
        else:
            safe_remove(self.activity_log_path)

        # Remove checkpoints directory
        safe_remove(self.checkpoint_dir)

        # Remove guardian files and other ralph session files
        ralph_dir = self.base_dir / ".claude" / "ralph"
        guardian_dir = ralph_dir / "guardian"
        safe_remove(guardian_dir)
        safe_remove(ralph_dir / "plan-digest.json")
        safe_remove(ralph_dir / "loop.local.md")
        safe_remove(ralph_dir / "pending.json")

        # Remove task queue files
        claude_dir = self.base_dir / ".claude"
        for queue_file in claude_dir.glob("task-queue-*.json"):
            safe_remove(queue_file)
        for lock_file in claude_dir.glob("task-queue-*.lock"):
            safe_remove(lock_file)

        # Remove ralph directory if empty (except activity log)
        if ralph_dir.exists():
            remaining = list(ralph_dir.iterdir())
            if not remaining or (len(remaining) == 1 and remaining[0].name == "activity.log"):
                pass  # Keep directory if only activity log
            elif not remaining:
                safe_remove(ralph_dir)

        self.log_activity(f"Session cleanup: {len(results['deleted'])} deleted, {len(results['preserved'])} preserved")
        return results

    def cmd_cleanup(self) -> None:
        """Clean up state files (manual command)."""
        results = self.cleanup_ralph_session(keep_activity_log=False)
        print(f"Cleanup complete: {len(results['deleted'])} files removed")

    def auto_cleanup(self, max_age_days: int = 7) -> dict:
        """
        Auto-clean Ralph files older than max_age_days.

        Cleans:
        - Checkpoints older than max_age_days
        - Activity log entries older than max_age_days
        - Guardian logs older than max_age_days
        - Orphaned task-queue files (no matching plan)

        Args:
            max_age_days: Maximum age in days before cleanup.

        Returns:
            dict with cleanup statistics
        """
        from datetime import timedelta

        stats = {"checkpoints": 0, "logs_trimmed": False, "queues": 0, "guardian": 0}
        cutoff = datetime.now() - timedelta(days=max_age_days)

        # Clean old checkpoints
        if self.checkpoint_dir.exists():
            for cp in self.checkpoint_dir.glob("checkpoint_*.json"):
                try:
                    mtime = datetime.fromtimestamp(cp.stat().st_mtime)
                    if mtime < cutoff:
                        cp.unlink()
                        stats["checkpoints"] += 1
                except OSError:
                    pass

        # Trim activity log (keep last 1000 lines)
        if self.activity_log_path.exists():
            try:
                lines = self.activity_log_path.read_text().splitlines()
                if len(lines) > 1000:
                    self.activity_log_path.write_text("\n".join(lines[-1000:]) + "\n")
                    stats["logs_trimmed"] = True
            except OSError:
                pass

        # Trim guardian log (keep last 100 entries)
        guardian_log = self.base_dir / ".claude" / "ralph" / "guardian" / "log.json"
        if guardian_log.exists():
            try:
                with open(guardian_log) as f:
                    log_data = json.load(f)
                checks = log_data.get("checks", [])
                if len(checks) > 100:
                    log_data["checks"] = checks[-100:]
                    with open(guardian_log, "w") as f:
                        json.dump(log_data, f, indent=2)
                    stats["guardian"] = len(checks) - 100
            except (OSError, json.JSONDecodeError):
                pass

        # Clean orphaned task queues (no matching plan file)
        claude_dir = self.base_dir / ".claude"
        plans_dir = self.base_dir / "plans"
        if claude_dir.exists():
            for queue_file in claude_dir.glob("task-queue-*.json"):
                plan_id = queue_file.stem.replace("task-queue-", "")
                plan_file = plans_dir / f"{plan_id}.md"
                if not plan_file.exists():
                    try:
                        queue_file.unlink()
                        # Also remove lock file
                        lock_file = claude_dir / f"task-queue-{plan_id}.lock"
                        if lock_file.exists():
                            lock_file.unlink()
                        stats["queues"] += 1
                    except OSError:
                        pass

        self.log_activity(f"Auto-cleanup: {stats}")
        return stats

    def cmd_auto_cleanup(self, max_age_days: int = 7) -> None:
        """Run auto-cleanup from CLI."""
        stats = self.auto_cleanup(max_age_days)
        print(f"Auto-cleanup complete:")
        print(f"  Checkpoints removed: {stats['checkpoints']}")
        print(f"  Activity log trimmed: {stats['logs_trimmed']}")
        print(f"  Guardian log entries trimmed: {stats['guardian']}")
        print(f"  Orphaned queues removed: {stats['queues']}")

    # =========================================================================
    # Private Helpers
    # =========================================================================

    def _generate_continuation_prompt(self, state: RalphState) -> str:
        """Generate prompt for blocked exit continuation."""
        return f"""
[RALPH PROTOCOL - CONTINUATION REQUIRED]

You are in an active Ralph autonomous loop session.
Session: {state.session_id}
Task: {state.task or 'Complete assigned work'}

You must complete your iteration before exit. When finished:
1. Output: {self.RALPH_COMPLETE_SIGNAL}
2. Output: {self.EXIT_SIGNAL}

Continue working on the task.
"""

    def _generate_ralph_instructions(self, state: RalphState) -> str:
        """Generate Ralph protocol instructions for agent."""
        return f"""
[RALPH PROTOCOL ACTIVE]
Session: {state.session_id}
Mode: Autonomous Loop ({state.total_agents} agents × {state.max_iterations} iterations)
Task: {state.task or 'Complete assigned work'}

INSTRUCTIONS:
- Work autonomously to complete the task
- Do NOT ask for user confirmation
- Make decisions independently
- When work is complete, output EXACTLY:
  {self.RALPH_COMPLETE_SIGNAL}
  {self.EXIT_SIGNAL}
"""

    def _build_agent_prompt(self, agent: AgentState, task: Optional[str]) -> str:
        """Build the initial prompt for an agent."""
        return f"""
You are Agent {agent.agent_id} in a Ralph Protocol autonomous loop.

TASK: {task or 'Complete the assigned development work'}

ITERATION: {agent.current_iteration + 1} of {agent.max_iterations}

RULES:
1. Work autonomously - do not ask for confirmation
2. Make independent decisions
3. Complete your iteration fully
4. When done, output:
   {self.RALPH_COMPLETE_SIGNAL}
   {self.EXIT_SIGNAL}

Begin working now.
"""


def print_usage():
    """Print CLI usage information."""
    print("""
Ralph Protocol - Autonomous Agent Loop Manager

Usage:
    ralph.py loop N M [OPTIONS] [task]  - Run N agents × M iterations
    ralph.py status                     - Show current Ralph state
    ralph.py resume                     - Resume from latest checkpoint
    ralph.py cleanup                    - Clean up all state files
    ralph.py cleanup --auto             - Auto-cleanup old files (default: 7 days)
    ralph.py cleanup --auto --max-age N - Auto-cleanup files older than N days
    ralph.py hook-stop                  - Handle hook-stop (reads stdin)
    ralph.py hook-pretool               - Handle hook-pretool (reads stdin)
    ralph.py hook-user-prompt           - Handle hook-user-prompt (reads stdin)
    ralph.py hook-session               - Handle hook-session-start (reads stdin)

Loop Options:
    --review-agents RN      Number of post-review agents (default: 5)
    --review-iterations RM  Iterations per review agent (default: 2)
    --skip-review           Skip post-implementation review
    --plan FILE             Path to plan file being executed

Cleanup Options:
    --auto                  Run age-based cleanup instead of full cleanup
    --max-age N             Days threshold for auto-cleanup (default: 7)

Examples:
    ralph.py loop 3 3 "Implement feature X"
    ralph.py loop 50 15 --review-agents 15 --review-iterations 10 "Big feature"
    ralph.py loop 10 5 --skip-review "Quick fix"
    ralph.py loop 30 10 --plan /path/to/plan.md "Execute plan"
    ralph.py status
    ralph.py resume
    ralph.py cleanup --auto --max-age 3
""")


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]
    protocol = RalphProtocol()

    if command == "loop":
        if len(sys.argv) < 4:
            print("Usage: ralph.py loop N M [OPTIONS] [task]")
            sys.exit(1)

        try:
            num_agents = int(sys.argv[2])
            max_iterations = int(sys.argv[3])
        except ValueError:
            print("Error: N and M must be integers")
            sys.exit(1)

        # Parse options and task from remaining args
        review_agents = 5
        review_iterations = 2
        skip_review = False
        plan_file = None
        task_parts = []

        i = 4
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--review-agents" and i + 1 < len(sys.argv):
                review_agents = int(sys.argv[i + 1])
                i += 2
            elif arg == "--review-iterations" and i + 1 < len(sys.argv):
                review_iterations = int(sys.argv[i + 1])
                i += 2
            elif arg == "--skip-review":
                skip_review = True
                i += 1
            elif arg == "--plan" and i + 1 < len(sys.argv):
                plan_file = sys.argv[i + 1]
                i += 2
            else:
                task_parts.append(arg)
                i += 1

        task = " ".join(task_parts) if task_parts else None

        print(f"Starting Ralph loop: {num_agents} agents × {max_iterations} iterations")
        if not skip_review:
            print(f"Post-review: {review_agents} agents × {review_iterations} iterations")
        else:
            print("Post-review: SKIPPED")
        if plan_file:
            print(f"Plan file: {plan_file}")
        if task:
            print(f"Task: {task}")

        asyncio.run(protocol.run_loop(
            num_agents,
            max_iterations,
            task,
            review_agents=review_agents,
            review_iterations=review_iterations,
            skip_review=skip_review,
            plan_file=plan_file
        ))

    elif command == "status":
        protocol.cmd_status()

    elif command == "resume":
        protocol.cmd_resume()

    elif command == "cleanup":
        # Check for --auto flag
        if "--auto" in sys.argv:
            max_age = 7
            if "--max-age" in sys.argv:
                try:
                    idx = sys.argv.index("--max-age")
                    if idx + 1 < len(sys.argv):
                        max_age = int(sys.argv[idx + 1])
                except (ValueError, IndexError):
                    pass
            protocol.cmd_auto_cleanup(max_age)
        else:
            protocol.cmd_cleanup()

    elif command == "hook-stop":
        result = protocol.handle_hook_stop()
        print(json.dumps(result))

    elif command == "hook-pretool":
        result = protocol.handle_hook_pretool()
        print(json.dumps(result))

    elif command == "hook-user-prompt":
        result = protocol.handle_hook_user_prompt()
        print(json.dumps(result))

    elif command == "hook-session":
        result = protocol.handle_hook_session_start()
        print(json.dumps(result))

    elif command == "hook-session-start":
        # Alias for hook-session (wrapper sends session-start -> hook-session-start)
        result = protocol.handle_hook_session_start()
        print(json.dumps(result))

    elif command == "hook-pre-compact":
        # PreCompact handler - create checkpoint before context compaction
        result = protocol.create_checkpoint(protocol.read_state()) if protocol.state_exists() else None
        print(json.dumps({"checkpoint_created": result is not None}))

    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
