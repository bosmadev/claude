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
import sys
if sys.platform != "win32":
    import fcntl
import json
import os
if sys.platform != "win32":
    import pty
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from zoneinfo import ZoneInfo


class SpawnBackend(str, Enum):
    """Agent spawning backend."""
    TASK = "task"
    SUBPROCESS = "subprocess"
    AUTO = "auto"  # Task for <=10, subprocess overflow


class MessageType(str, Enum):
    """Inter-agent message types for Hybrid Gamma communication."""
    TASK_COMPLETED = "task_completed"
    IDLE_NOTIFICATION = "idle_notification"
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_APPROVED = "shutdown_approved"
    PHASE_CHANGE = "phase_change"
    PLAN_APPROVAL_REQUEST = "plan_approval_request"
    REVIEW_COMPLETED = "review_completed"
    DELEGATION = "delegation"
    PERMISSION_REQUEST = "permission_request"
    HEARTBEAT = "heartbeat"


@dataclass
class AgentMessage:
    """Inter-agent message for inbox-based communication."""
    msg_id: str
    msg_type: str
    from_agent: str
    to_agent: str  # "*" for broadcast
    payload: dict = field(default_factory=dict)
    created_at: str = ""
    ttl_seconds: int = 300  # 5 minute default TTL
    acked: bool = False

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "msg_type": self.msg_type,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "payload": self.payload,
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
            "acked": self.acked,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentMessage":
        return cls(
            msg_id=data["msg_id"],
            msg_type=data["msg_type"],
            from_agent=data["from_agent"],
            to_agent=data["to_agent"],
            payload=data.get("payload", {}),
            created_at=data.get("created_at", ""),
            ttl_seconds=data.get("ttl_seconds", 300),
            acked=data.get("acked", False),
        )

    def is_expired(self) -> bool:
        if not self.created_at:
            return False
        try:
            created = datetime.fromisoformat(self.created_at)
            # Normalize to naive datetime to avoid mixed tz comparison
            if created.tzinfo is not None:
                created = created.replace(tzinfo=None)
            age = (datetime.now() - created).total_seconds()
            return age > self.ttl_seconds
        except (ValueError, TypeError):
            return False


@dataclass
class TeamConfig:
    """Team configuration for a Ralph session."""
    session_id: str
    leader_agent: str = "agent-0"
    agents: list = field(default_factory=list)
    backend: str = SpawnBackend.AUTO.value
    created_at: str = ""
    env_vars: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "leader_agent": self.leader_agent,
            "agents": self.agents,
            "backend": self.backend,
            "created_at": self.created_at,
            "env_vars": self.env_vars,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TeamConfig":
        return cls(
            session_id=data["session_id"],
            leader_agent=data.get("leader_agent", "agent-0"),
            agents=data.get("agents", []),
            backend=data.get("backend", SpawnBackend.AUTO.value),
            created_at=data.get("created_at", ""),
            env_vars=data.get("env_vars", {}),
        )


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
        self._ensure_dir()
        fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _release_lock(self, fd: int) -> None:
        """Release file lock."""
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
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

    def reclaim_stale_tasks(self, timeout_seconds: int = 300) -> list[str]:
        """
        Auto-unclaim in_progress tasks older than timeout.

        Crashed agent's work gets re-assigned to next available agent.

        Args:
            timeout_seconds: Max age in seconds before reclaiming (default 5 min).

        Returns:
            List of reclaimed task IDs.
        """
        fd = self._acquire_lock()
        try:
            queue = self.load()
            reclaimed = []
            now = datetime.now()

            for task in queue.tasks:
                if task.status != "in_progress" or not task.started_at:
                    continue
                try:
                    started = datetime.fromisoformat(task.started_at)
                    # Normalize to naive datetime to avoid mixed tz comparison
                    if started.tzinfo is not None:
                        started = started.replace(tzinfo=None)
                    age = (now - started).total_seconds()
                    if age > timeout_seconds:
                        task.status = "pending"
                        task.claimed_by = None
                        reclaimed.append(task.id)
                except (ValueError, TypeError):
                    continue

            if reclaimed:
                self.save(queue)

            return reclaimed

        finally:
            self._release_lock(fd)


# =============================================================================
# Agent Inbox (Hybrid Gamma Inter-Agent Communication)
# =============================================================================

class AgentInbox:
    """
    File-based per-agent inbox for Hybrid Gamma inter-agent communication.

    Location: {project}/.claude/ralph/team-{session}/inbox/{agent-id}.json

    Each agent has its own inbox file. Messages are JSON arrays with TTL
    and ACK tracking. Uses file locking for atomic operations.
    """

    def __init__(self, session_id: str, agent_id: str, base_dir: Optional[Path] = None):
        self.session_id = session_id
        self.agent_id = agent_id
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.team_dir = self.base_dir / ".claude" / "ralph" / f"team-{session_id}"
        self.inbox_dir = self.team_dir / "inbox"
        self.inbox_path = self.inbox_dir / f"{agent_id}.json"
        self.config_path = self.team_dir / "config.json"
        self.relay_path = self.team_dir / "relay.json"
        self.heartbeat_dir = self.team_dir / "heartbeat"

    def _ensure_dirs(self) -> None:
        """Ensure all team directories exist."""
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_dir.mkdir(parents=True, exist_ok=True)

    def _lock_file(self, path: Path) -> int:
        """Acquire lock for file operations."""
        lock_path = path.with_suffix(".lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    def _unlock_file(self, fd: int) -> None:
        """Release file lock."""
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def read_messages(self) -> list[AgentMessage]:
        """Read all non-expired messages from inbox."""
        self._ensure_dirs()
        if not self.inbox_path.exists():
            return []
        try:
            with open(self.inbox_path) as f:
                data = json.load(f)
            messages = [AgentMessage.from_dict(m) for m in data]
            return [m for m in messages if not m.is_expired()]
        except (json.JSONDecodeError, OSError):
            return []

    def send_message(self, to_agent: str, msg_type: str, payload: dict | None = None) -> AgentMessage:
        """
        Send a message to another agent's inbox.

        Args:
            to_agent: Target agent ID or "*" for broadcast.
            msg_type: MessageType value.
            payload: Optional message payload.

        Returns:
            The sent AgentMessage.
        """
        import uuid
        self._ensure_dirs()

        msg = AgentMessage(
            msg_id=str(uuid.uuid4())[:8],
            msg_type=msg_type,
            from_agent=self.agent_id,
            to_agent=to_agent,
            payload=payload or {},
            created_at=datetime.now().isoformat(),
        )

        if to_agent == "*":
            # Broadcast: write to all inboxes in team
            for inbox_file in self.inbox_dir.glob("*.json"):
                if inbox_file.stem == self.agent_id:
                    continue  # Don't send to self
                self._append_to_inbox(inbox_file, msg)
        else:
            target_path = self.inbox_dir / f"{to_agent}.json"
            self._append_to_inbox(target_path, msg)

        return msg

    def _append_to_inbox(self, path: Path, msg: AgentMessage) -> None:
        """Atomically append a message to an inbox file."""
        fd = self._lock_file(path)
        try:
            messages = []
            if path.exists():
                try:
                    with open(path) as f:
                        messages = json.load(f)
                except (json.JSONDecodeError, OSError):
                    messages = []

            messages.append(msg.to_dict())

            # Prune expired messages
            now = datetime.now()
            messages = [
                m for m in messages
                if not AgentMessage.from_dict(m).is_expired()
            ]

            with open(path, "w") as f:
                json.dump(messages, f, indent=2)
        finally:
            self._unlock_file(fd)

    def ack_message(self, msg_id: str) -> bool:
        """Mark a message as acknowledged."""
        fd = self._lock_file(self.inbox_path)
        try:
            if not self.inbox_path.exists():
                return False
            with open(self.inbox_path) as f:
                messages = json.load(f)
            for m in messages:
                if m.get("msg_id") == msg_id:
                    m["acked"] = True
                    with open(self.inbox_path, "w") as f:
                        json.dump(messages, f, indent=2)
                    return True
            return False
        except (json.JSONDecodeError, OSError):
            return False
        finally:
            self._unlock_file(fd)

    def write_heartbeat(self) -> None:
        """Write heartbeat file for liveness detection."""
        self._ensure_dirs()
        hb_path = self.heartbeat_dir / f"{self.agent_id}.json"
        hb_data = {
            "agent_id": self.agent_id,
            "timestamp": datetime.now().isoformat(),
            "session_id": self.session_id,
        }
        try:
            with open(hb_path, "w") as f:
                json.dump(hb_data, f)
        except OSError:
            pass

    def check_heartbeat(self, agent_id: str, timeout_seconds: int = 300) -> bool:
        """
        Check if an agent's heartbeat is recent.

        Args:
            agent_id: Agent to check.
            timeout_seconds: Max heartbeat age (default 5 min).

        Returns:
            True if heartbeat is recent, False if stale/missing.
        """
        hb_path = self.heartbeat_dir / f"{agent_id}.json"
        if not hb_path.exists():
            return False
        try:
            with open(hb_path) as f:
                data = json.load(f)
            ts = datetime.fromisoformat(data["timestamp"])
            return (datetime.now() - ts).total_seconds() < timeout_seconds
        except (json.JSONDecodeError, OSError, KeyError, ValueError):
            return False

    def write_team_config(self, config: TeamConfig) -> None:
        """Write team configuration."""
        self._ensure_dirs()
        with open(self.config_path, "w") as f:
            json.dump(config.to_dict(), f, indent=2)

    def read_team_config(self) -> Optional[TeamConfig]:
        """Read team configuration."""
        if not self.config_path.exists():
            return None
        try:
            with open(self.config_path) as f:
                return TeamConfig.from_dict(json.load(f))
        except (json.JSONDecodeError, OSError):
            return None

    def write_relay(self, data: dict) -> None:
        """Write to shared relay file (leader coordination)."""
        fd = self._lock_file(self.relay_path)
        try:
            existing = {}
            if self.relay_path.exists():
                try:
                    with open(self.relay_path) as f:
                        existing = json.load(f)
                except (json.JSONDecodeError, OSError):
                    pass
            existing.update(data)
            existing["updated_at"] = datetime.now().isoformat()
            with open(self.relay_path, "w") as f:
                json.dump(existing, f, indent=2)
        finally:
            self._unlock_file(fd)

    def read_relay(self) -> dict:
        """Read shared relay file."""
        if not self.relay_path.exists():
            return {}
        try:
            with open(self.relay_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def cleanup_team(self) -> None:
        """Remove team directory (teardown)."""
        if self.team_dir.exists():
            shutil.rmtree(self.team_dir, ignore_errors=True)

    def request_shutdown(self) -> None:
        """Leader sends shutdown request to all agents."""
        self.send_message("*", MessageType.SHUTDOWN_REQUEST.value, {
            "reason": "session_complete",
            "grace_seconds": 30,
        })

    def approve_shutdown(self) -> None:
        """Agent approves shutdown request."""
        self.send_message("agent-0", MessageType.SHUTDOWN_APPROVED.value, {
            "agent_id": self.agent_id,
        })


# =============================================================================
# Agent Config Discovery
# =============================================================================

def _get_agents_dir() -> str:
    """Get default agents directory, cross-platform."""
    _home = os.environ.get("CLAUDE_HOME", "C:/Users/Dennis/.claude" if sys.platform == "win32" else "/usr/share/claude")
    return str(Path(_home) / "agents")


def discover_agent_configs(agents_dir: str | None = None) -> dict[str, str]:
    """
    Discover ALL agent config files (not just reviewers).

    Returns:
        Dict mapping config name to file path.
        e.g. {"security-reviewer": "/usr/share/claude/agents/security-reviewer.md"}
    """
    if agents_dir is None:
        agents_dir = _get_agents_dir()

    agents_path = Path(agents_dir)
    if not agents_path.exists():
        return {}

    configs = {}
    for agent_file in sorted(agents_path.glob("*.md")):
        configs[agent_file.stem] = str(agent_file)

    return configs


def load_agent_config(config_path: str) -> str:
    """Load an agent config file content."""
    try:
        return Path(config_path).read_text(encoding="utf-8")
    except OSError:
        return ""


# =============================================================================
# Review Agent Discovery
# =============================================================================

def discover_review_agents(agents_dir: str | None = None) -> list[str]:
    """
    Auto-discover all *-reviewer.md agents in the agents directory.

    Args:
        agents_dir: Path to agents directory.

    Returns:
        List of specialty names (e.g., ["security", "performance", "a11y"]).
    """
    if agents_dir is None:
        agents_dir = _get_agents_dir()
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


def get_review_agent_path(specialty: str, agents_dir: str | None = None) -> Optional[str]:
    """
    Get the full path to a review agent file.

    Args:
        specialty: The specialty name (e.g., "security").
        agents_dir: Path to agents directory.

    Returns:
        Full path to agent file, or None if not found.
    """
    if agents_dir is None:
        agents_dir = _get_agents_dir()
    agent_path = Path(agents_dir) / f"{specialty}-reviewer.md"
    return str(agent_path) if agent_path.exists() else None


# =============================================================================
# Daily Cost Tracking
# =============================================================================

def _get_daily_cost_dir() -> Path:
    """Get path to daily cost directory."""
    return Path.home() / ".claude" / "daily-cost"


def record_daily_cost(cost_usd: float) -> None:
    """
    Record agent cost to a per-agent file in the daily cost directory.

    The statusline sums all .cost files for today's date to show
    a cross-session daily total.

    Args:
        cost_usd: Cost in USD for this agent run.
    """
    cet = ZoneInfo("Europe/Berlin")
    today = datetime.now(cet).strftime("%Y-%m-%d")
    cost_dir = _get_daily_cost_dir()
    cost_dir.mkdir(parents=True, exist_ok=True)

    # Write to a ralph-specific accumulator file (one per day)
    ralph_path = cost_dir / f"{today}-ralph.cost"
    lock_path = ralph_path.with_suffix(".lock")

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)

        # Read existing accumulated cost
        existing = 0.0
        if ralph_path.exists():
            try:
                existing = float(ralph_path.read_text(encoding="utf-8").strip())
            except (ValueError, OSError, UnicodeDecodeError):
                pass

        # Accumulate and write
        new_total = round(existing + cost_usd, 4)
        ralph_path.write_text(str(new_total))

    finally:
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


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
    PROGRESS_FILE = ".claude/ralph/progress.json"

    # Legacy flat structure (for migration)
    LEGACY_STATE_FILE = ".claude/ralph-state.json"
    LEGACY_ACTIVITY_LOG = ".claude/ralph-activity.log"
    LEGACY_CHECKPOINT_DIR = ".claude/ralph-checkpoints"

    RALPH_COMPLETE_SIGNAL = "RALPH_COMPLETE"
    EXIT_SIGNAL = "EXIT_SIGNAL"

    # ANSI colors for terminal progress output
    _C_GREEN = "\033[32m"
    _C_RED = "\033[31m"
    _C_YELLOW = "\033[33m"
    _C_CYAN = "\033[36m"
    _C_DIM = "\033[2m"
    _C_BOLD = "\033[1m"
    _C_RESET = "\033[0m"

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
        self.progress_path = self.base_dir / self.PROGRESS_FILE
        self._state_lock = asyncio.Lock()  # Prevent concurrent state access
        self._loop_start_time: Optional[datetime] = None
        self._completed_count = 0
        self._failed_count = 0
        self._total_cost = 0.0
        self._total_agents_in_loop = 0

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
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
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

    def _elapsed_str(self) -> str:
        """Format elapsed time since loop start as 'Xm Ys'."""
        if not self._loop_start_time:
            return "0s"
        delta = datetime.now() - self._loop_start_time
        total_secs = int(delta.total_seconds())
        if total_secs < 60:
            return f"{total_secs}s"
        minutes, secs = divmod(total_secs, 60)
        if minutes < 60:
            return f"{minutes}m {secs}s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes}m"

    def _progress_str(self) -> str:
        """Format progress counter like '[2/10]'."""
        done = self._completed_count + self._failed_count
        return f"[{done}/{self._total_agents_in_loop}]"

    def _print_progress(self, event: str, agent_id: int, detail: str = "") -> None:
        """
        Print a real-time progress line to stdout and update progress file.

        Each line is self-contained so the user can see progress accumulate.
        Format: [elapsed] event Agent N [done/total] detail
        """
        elapsed = self._elapsed_str()
        progress = self._progress_str()
        detail_str = f"  {detail}" if detail else ""

        # Color-code by event type
        if event == "STARTED":
            icon = f"{self._C_CYAN}>>>{self._C_RESET}"
            event_fmt = f"{self._C_CYAN}{event}{self._C_RESET}"
        elif event == "DONE":
            icon = f"{self._C_GREEN}>>>{self._C_RESET}"
            event_fmt = f"{self._C_GREEN}{event}{self._C_RESET}"
        elif event == "FAILED":
            icon = f"{self._C_RED}>>>{self._C_RESET}"
            event_fmt = f"{self._C_RED}{event}{self._C_RESET}"
        elif event == "TIMEOUT":
            icon = f"{self._C_YELLOW}>>>{self._C_RESET}"
            event_fmt = f"{self._C_YELLOW}{event}{self._C_RESET}"
        else:
            icon = ">>>"
            event_fmt = event

        line = (
            f"{icon} {self._C_DIM}{elapsed:>8}{self._C_RESET}  "
            f"{event_fmt} Agent {agent_id} {progress}{detail_str}"
        )
        print(line, flush=True)

        # Write progress file for external consumers (statusline, etc.)
        self._write_progress_file()

    def _write_progress_file(self) -> None:
        """Write current progress to a JSON file for external tools."""
        try:
            done = self._completed_count + self._failed_count
            progress_data = {
                "total": self._total_agents_in_loop,
                "completed": self._completed_count,
                "failed": self._failed_count,
                "done": done,
                "cost_usd": round(self._total_cost, 4),
                "elapsed_str": self._elapsed_str(),
                "started_at": self._loop_start_time.isoformat() if self._loop_start_time else None,
                "updated_at": datetime.now().isoformat(),
            }
            self.progress_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.progress_path, 'w') as f:
                json.dump(progress_data, f)
        except IOError:
            pass

    def _print_summary(self, successful: int, failed: int, exceptions: list) -> None:
        """Print a final summary banner after all agents complete."""
        elapsed = self._elapsed_str()
        total = self._total_agents_in_loop
        cost_str = f"${self._total_cost:.2f}" if self._total_cost > 0 else "n/a"

        # Horizontal rule
        bar = f"{self._C_DIM}{'=' * 60}{self._C_RESET}"
        print(f"\n{bar}", flush=True)
        print(f"{self._C_BOLD}  Ralph Loop Complete{self._C_RESET}", flush=True)
        print(bar, flush=True)

        # Color the success/fail counts
        ok_str = f"{self._C_GREEN}{successful}{self._C_RESET}"
        fail_str = f"{self._C_RED}{failed}{self._C_RESET}" if failed > 0 else f"{self._C_DIM}0{self._C_RESET}"

        print(f"  Agents:   {ok_str} succeeded, {fail_str} failed  ({total} total)", flush=True)
        print(f"  Cost:     {cost_str}", flush=True)
        print(f"  Duration: {elapsed}", flush=True)

        if exceptions:
            print(f"\n  {self._C_RED}Errors:{self._C_RESET}", flush=True)
            for exc in exceptions[:5]:
                print(f"    - {exc}", flush=True)

        print(bar, flush=True)
        print(flush=True)

    def _cleanup_progress_file(self) -> None:
        """Remove progress file after loop completes."""
        try:
            if self.progress_path.exists():
                self.progress_path.unlink()
        except IOError:
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
        Check if a process is alive and is a Claude-related process.

        Uses platform-specific methods:
        - Windows: tasklist command to query process by PID
        - Linux: /proc filesystem to read process cmdline

        Args:
            pid: Process ID to check.

        Returns:
            True if process exists and is a Claude process, False otherwise.
        """
        if sys.platform == "win32":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True, text=True, timeout=5
                )
                if str(pid) in result.stdout:
                    # Check if it's a Claude-related process
                    output_lower = result.stdout.lower()
                    return "claude" in output_lower or "python" in output_lower or "node" in output_lower
                return False
            except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
                return True  # Assume alive on error
        else:
            try:
                # Check if process exists
                os.kill(pid, 0)  # Signal 0 = check existence only
                # Verify it's a Claude process by checking /proc/PID/cmdline
                cmdline_path = Path(f"/proc/{pid}/cmdline")
                if cmdline_path.exists():
                    cmdline = cmdline_path.read_text(encoding="utf-8")
                    return 'claude' in cmdline.lower()
                return True  # Process exists but can't verify cmdline
            except (OSError, PermissionError, UnicodeDecodeError):
                return False

    def _check_session_stale(self, started_at: str, threshold_hours: Optional[float] = None) -> tuple:
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
        1.5. Not a subagent (no RALPH_SUBAGENT env) → Allow exit (orchestrator)
        2. State file exists (subagent only):
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

        # CHECK 1.5: Parent/orchestrator session = allow exit
        # The parent orchestrator manages the loop and must be free to exit.
        if not os.environ.get("RALPH_SUBAGENT"):
            self.log_activity("Exit allowed: Parent/orchestrator session (not a subagent)")
            return {"decision": "approve", "reason": "Parent/orchestrator session - not blocked"}

        # CHECK 1.6: Batch subagents (claude --print) managed by ralph.py orchestrator.
        # ralph.py tracks completion via subprocess exit code + output parsing.
        # Blocking exit for batch agents causes deadlock since they can't be
        # interactively prompted to output completion signals.
        if os.environ.get("RALPH_SUBAGENT") == "true":
            self.log_activity("Exit allowed: Batch subagent (lifecycle managed by orchestrator)")
            return {"decision": "approve", "reason": "Batch subagent - orchestrator manages lifecycle"}

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
                cleanup_results = self.cleanup_ralph_session(keep_activity_log=False)
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
                cleanup_results = self.cleanup_ralph_session(keep_activity_log=False)
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
            cleanup_results = self.cleanup_ralph_session(keep_activity_log=False)
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
        # Skip push gate if agent made no commits (review agents, read-only agents)
        # Compare current HEAD with RALPH_INITIAL_HEAD set at agent spawn time
        if has_complete:
            initial_head = os.environ.get("RALPH_INITIAL_HEAD", "")
            current_head = ""
            try:
                head_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True,
                    cwd=str(self.base_dir), timeout=5
                )
                if head_result.returncode == 0:
                    current_head = head_result.stdout.strip()
            except Exception:
                pass

            # If HEAD unchanged since spawn, agent made no commits → skip push gate
            agent_made_commits = (initial_head != current_head) if (initial_head and current_head) else True
            has_unpushed, unpushed_count, branch = self._detect_unpushed_commits()
            if has_unpushed and agent_made_commits:
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
            cleanup_results = self.cleanup_ralph_session(keep_activity_log=False)
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
                    cleanup_results = self.cleanup_ralph_session(keep_activity_log=False)
                    response["cleaned_orphaned_session"] = {
                        "reason": cleanup_reason,
                        "cleanup": cleanup_results
                    }

            except (json.JSONDecodeError, OSError):
                # State file corrupted, clean it up
                self.log_activity("Session start: Cleaning corrupted state file", level="WARN")
                self.cleanup_ralph_session(keep_activity_log=False)
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
        project_root = self.base_dir
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
            On Windows, master_fd is None (no PTY support).
        """
        env = os.environ.copy()
        env["RALPH_SUBAGENT"] = "true"
        if session_token:
            env["RALPH_SESSION_TOKEN"] = session_token
        # Inherit parent's permission mode
        env["CLAUDE_CODE_PERMISSION_MODE"] = os.environ.get(
            "CLAUDE_CODE_PERMISSION_MODE", "acceptEdits"
        )

        if sys.platform == "win32":
            # Windows: no PTY support, use subprocess pipes
            proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
            return proc, None  # No master fd on Windows
        else:
            import pty
            master, slave = pty.openpty()
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

    # Maximum concurrent agents to prevent resource exhaustion
    MAX_CONCURRENT_AGENTS = 5

    async def spawn_agent(
        self,
        agent_state: AgentState,
        task: Optional[str] = None,
        semaphore: Optional[asyncio.Semaphore] = None
    ) -> bool:
        """
        Spawn a single Claude agent asynchronously with concurrency control.

        Args:
            agent_state: State object for this agent.
            task: Optional task description.
            semaphore: Optional semaphore for concurrency limiting.

        Returns:
            True if agent completed successfully, False otherwise.
        """
        # Acquire semaphore if provided (limits concurrent agents)
        if semaphore:
            await semaphore.acquire()

        try:
            return await self._spawn_agent_impl(agent_state, task)
        finally:
            if semaphore:
                semaphore.release()

    async def _spawn_agent_impl(self, agent_state: AgentState, task: Optional[str] = None) -> bool:
        """Internal implementation of agent spawning via subprocess.

        Spawns a separate `claude --print` process for each agent.
        Each process has its own context window and MCP servers.
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

        return await self._spawn_agent_subprocess(agent_state, task)

    async def _spawn_agent_subprocess(self, agent_state: AgentState, task: Optional[str] = None) -> bool:
        """Spawn agent as an independent subprocess with its own context window."""
        self.log_activity(f"Agent {agent_state.agent_id} started")
        self._print_progress("STARTED", agent_state.agent_id)

        spawned_pid = None
        proc = None
        try:
            prompt = self._build_agent_prompt(agent_state, task)

            env = os.environ.copy()
            # Core Ralph env vars
            env["RALPH_SUBAGENT"] = "true"
            env["RALPH_AGENT_ID"] = str(agent_state.agent_id)
            env["CLAUDE_CODE_PERMISSION_MODE"] = os.environ.get(
                "CLAUDE_CODE_PERMISSION_MODE", "acceptEdits"
            )

            # Gist-compatible env vars (Step 6)
            state = self.read_state()
            session_id = state.session_id if state else "unknown"
            env["CLAUDE_CODE_TEAM_NAME"] = os.environ.get(
                "CLAUDE_CODE_TEAM_NAME", f"ralph-{session_id}"
            )
            env["CLAUDE_CODE_AGENT_ID"] = f"agent-{agent_state.agent_id}"
            env["CLAUDE_CODE_AGENT_NAME"] = f"Ralph Agent {agent_state.agent_id}"
            env["RALPH_AGENT_TYPE"] = "implementation"  # or "review", "leader"
            env["RALPH_PARENT_SESSION_ID"] = session_id

            # Record HEAD at agent start for push gate comparison
            # Review agents that make no commits won't be blocked on exit
            try:
                head_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True,
                    cwd=str(self.base_dir), timeout=5
                )
                if head_result.returncode == 0:
                    env["RALPH_INITIAL_HEAD"] = head_result.stdout.strip()
            except Exception:
                pass

            # Use start_new_session to detach from parent process group
            # --output-format json gives us total_cost_usd in the result
            proc = await asyncio.create_subprocess_exec(
                "claude", "--print", "--output-format", "json", "-p", prompt,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True
            )

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

            stdout_chunks = []
            stderr_chunks = []

            async def read_stream(stream, chunks, max_size=1024*1024):
                total = 0
                while True:
                    chunk = await stream.read(8192)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total <= max_size:
                        chunks.append(chunk)

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        read_stream(proc.stdout, stdout_chunks),
                        read_stream(proc.stderr, stderr_chunks),
                        proc.wait()
                    ),
                    timeout=900
                )
            except asyncio.TimeoutError:
                self.log_activity(f"Agent {agent_state.agent_id} timed out, terminating...", level="WARN")
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=10)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                agent_state.status = AgentStatus.FAILED.value
                agent_state.completed_at = datetime.now().isoformat()
                self._failed_count += 1
                self._print_progress("TIMEOUT", agent_state.agent_id, "killed after 15m")
                await self._update_final_state(agent_state, spawned_pid)
                return False
            except asyncio.CancelledError:
                self.log_activity(f"Agent {agent_state.agent_id} cancelled, cleaning up...", level="WARN")
                if proc and proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        proc.kill()
                raise

            # Parse JSON result for cost data (--output-format json)
            stdout_text = b"".join(stdout_chunks).decode(errors="replace").strip()
            stderr_text = b"".join(stderr_chunks).decode(errors="replace").strip()

            if proc.returncode == 0:
                agent_state.status = AgentStatus.COMPLETED.value
                agent_state.ralph_complete = True
                agent_state.exit_signal = True

                # Extract cost from JSON result
                cost_usd = 0
                num_turns = 0
                try:
                    result_json = json.loads(stdout_text)
                    cost_usd = result_json.get("total_cost_usd", 0) or 0
                    num_turns = result_json.get("num_turns", 0) or 0
                    if cost_usd > 0:
                        self.log_activity(
                            f"Agent {agent_state.agent_id} completed (${cost_usd:.4f}, {num_turns} turns)"
                        )
                        try:
                            record_daily_cost(cost_usd)
                        except Exception as e:
                            self.log_activity(f"Failed to record cost: {e}", level="WARN")
                    else:
                        self.log_activity(f"Agent {agent_state.agent_id} completed successfully")
                except (json.JSONDecodeError, TypeError):
                    self.log_activity(f"Agent {agent_state.agent_id} completed successfully")

                self._completed_count += 1
                self._total_cost += cost_usd
                detail_parts = []
                if cost_usd > 0:
                    detail_parts.append(f"${cost_usd:.2f}")
                if num_turns > 0:
                    detail_parts.append(f"{num_turns} turns")
                self._print_progress("DONE", agent_state.agent_id, ", ".join(detail_parts) if detail_parts else "")
            else:
                agent_state.status = AgentStatus.FAILED.value
                error_msg = stderr_text[:200] if stderr_text else stdout_text[:200]
                self.log_activity(
                    f"Agent {agent_state.agent_id} failed (exit {proc.returncode}): {error_msg}",
                    level="ERROR"
                )
                self._failed_count += 1
                self._print_progress("FAILED", agent_state.agent_id, f"exit {proc.returncode}")

        except asyncio.CancelledError:
            agent_state.status = AgentStatus.FAILED.value
            self._failed_count += 1
            raise
        except Exception as e:
            agent_state.status = AgentStatus.FAILED.value
            self._failed_count += 1
            self.log_activity(f"Agent {agent_state.agent_id} error: {e}", level="ERROR")

        agent_state.completed_at = datetime.now().isoformat()
        await self._update_final_state(agent_state, spawned_pid)
        return agent_state.status == AgentStatus.COMPLETED.value

    async def _update_final_state(self, agent_state: AgentState, spawned_pid: Optional[int] = None) -> bool:
        """Update final agent state after completion/failure."""
        async with self._state_lock:
            state = self.read_state()
            if state:
                for i, a in enumerate(state.agents):
                    a_id = a.agent_id if isinstance(a, AgentState) else a.get("agent_id")
                    if a_id == agent_state.agent_id:
                        state.agents[i] = agent_state
                        break
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
        plan_file: Optional[str] = None,
        max_concurrent: Optional[int] = None,
        backend: str = SpawnBackend.AUTO.value,
    ) -> RalphState:
        """
        Run the full Ralph loop with N agents × M iterations.

        Uses a semaphore to limit concurrent agents and prevent resource exhaustion.
        Supports multiple spawn backends: task (Claude Task tool), subprocess, or auto.

        Args:
            num_agents: Number of agents to spawn.
            max_iterations: Maximum iterations per agent.
            task: Optional task description.
            review_agents: Number of review agents (default 5).
            review_iterations: Iterations per review agent (default 2).
            skip_review: Whether to skip post-implementation review.
            plan_file: Path to the plan file being executed.
            max_concurrent: Maximum concurrent agents (default: MAX_CONCURRENT_AGENTS).
            backend: Spawn backend - "task", "subprocess", or "auto".

        Returns:
            Final RalphState after execution.
        """
        # Initialize progress tracking
        self._loop_start_time = datetime.now()
        self._completed_count = 0
        self._failed_count = 0
        self._total_cost = 0.0
        self._total_agents_in_loop = num_agents

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

        # Determine concurrency limit
        concurrent_limit = max_concurrent or self.MAX_CONCURRENT_AGENTS
        concurrent_limit = min(concurrent_limit, num_agents)  # Don't exceed agent count

        self.log_activity(
            f"Ralph loop started: {num_agents} agents × {max_iterations} iterations "
            f"(max {concurrent_limit} concurrent)"
        )

        # Print startup banner to stdout
        print(flush=True)
        print(
            f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
            flush=True
        )
        print(
            f"  {self._C_BOLD}Ralph Loop{self._C_RESET}  "
            f"{num_agents} agents x {max_iterations} iterations  "
            f"{self._C_DIM}(max {concurrent_limit} concurrent){self._C_RESET}",
            flush=True
        )
        if task:
            # Truncate long tasks for the banner
            task_display = task[:70] + "..." if len(task) > 70 else task
            print(f"  {self._C_DIM}Task:{self._C_RESET} {task_display}", flush=True)
        print(
            f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
            flush=True
        )
        print(flush=True)

        # Write initial progress file
        self._write_progress_file()

        # Initialize team infrastructure for Hybrid Gamma
        inbox = AgentInbox(session_id, "agent-0", self.base_dir)
        team_config = TeamConfig(
            session_id=session_id,
            leader_agent="agent-0",
            agents=[{"id": f"agent-{i}", "status": "pending"} for i in range(num_agents)],
            backend=backend,
            created_at=datetime.now().isoformat(),
            env_vars={"CLAUDE_CODE_TEAM_NAME": f"ralph-{session_id}"},
        )
        try:
            inbox.write_team_config(team_config)
            for i in range(num_agents):
                agent_inbox = inbox.inbox_dir / f"agent-{i}.json"
                if not agent_inbox.exists():
                    agent_inbox.parent.mkdir(parents=True, exist_ok=True)
                    with open(agent_inbox, "w") as f:
                        json.dump([], f)
        except OSError:
            pass  # Non-fatal: agents work without inbox

        # Batching strategy (Step 4):
        # For <=10 agents: single batch with semaphore
        # For >10 agents: batch in groups of BATCH_SIZE
        BATCH_SIZE = 10
        results = []

        if num_agents <= BATCH_SIZE:
            # Single batch — standard semaphore approach
            semaphore = asyncio.Semaphore(concurrent_limit)
            spawn_tasks = [
                self.spawn_agent(agent, task, semaphore)
                for agent in agents
            ]
            results = await asyncio.gather(*spawn_tasks, return_exceptions=True)
        else:
            # Multi-batch for large agent counts
            self.log_activity(
                f"Batching {num_agents} agents in groups of {BATCH_SIZE}"
            )
            for batch_start in range(0, num_agents, BATCH_SIZE):
                batch_end = min(batch_start + BATCH_SIZE, num_agents)
                batch_agents = agents[batch_start:batch_end]
                batch_num = (batch_start // BATCH_SIZE) + 1
                total_batches = (num_agents + BATCH_SIZE - 1) // BATCH_SIZE

                self._print_progress(
                    "BATCH", -1,
                    f"{batch_num}/{total_batches} (agents {batch_start}-{batch_end - 1})"
                )

                semaphore = asyncio.Semaphore(min(concurrent_limit, len(batch_agents)))
                spawn_tasks = [
                    self.spawn_agent(agent, task, semaphore)
                    for agent in batch_agents
                ]
                batch_results = await asyncio.gather(*spawn_tasks, return_exceptions=True)
                results.extend(batch_results)

                # Reclaim stale tasks between batches (Step 4)
                if plan_file:
                    try:
                        plan_id = Path(plan_file).stem if plan_file else session_id
                        queue = WorkStealingQueue(plan_id, plan_file or "", self.base_dir)
                        reclaimed = queue.reclaim_stale_tasks(timeout_seconds=300)
                        if reclaimed:
                            self.log_activity(
                                f"Reclaimed {len(reclaimed)} stale tasks: {reclaimed}"
                            )
                    except Exception:
                        pass  # Non-fatal

        # Update final state
        state = self.read_state()
        if state:
            state.completed_at = datetime.now().isoformat()
            self.write_state(state)

        # Count results
        successful = sum(1 for r in results if r is True)
        failed = sum(1 for r in results if r is False or isinstance(r, Exception))
        exceptions = [r for r in results if isinstance(r, Exception)]

        if exceptions:
            for exc in exceptions[:3]:  # Log first 3 exceptions
                self.log_activity(f"Agent exception: {exc}", level="ERROR")

        self.log_activity(
            f"Ralph loop completed: {successful}/{num_agents} successful, {failed} failed"
        )

        # Print final summary to stdout
        self._print_summary(successful, failed, exceptions)

        # Clean up progress file (loop is done)
        self._cleanup_progress_file()

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

        # Log before potential directory removal
        self.log_activity(f"Session cleanup: {len(results['deleted'])} deleted, {len(results['preserved'])} preserved")

        # Remove ralph directory (LAST - after logging)
        if ralph_dir.exists():
            if not keep_activity_log:
                # Full cleanup: nuke entire .claude/ralph/ directory
                safe_remove(ralph_dir)
            else:
                # Partial cleanup: remove directory only if empty
                remaining = list(ralph_dir.iterdir())
                if not remaining:
                    safe_remove(ralph_dir)
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
                lines = self.activity_log_path.read_text(encoding="utf-8").splitlines()
                if len(lines) > 1000:
                    self.activity_log_path.write_text("\n".join(lines[-1000:]) + "\n", encoding="utf-8")
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
    # Setup / Teardown (Step 1: Hybrid Architecture)
    # =========================================================================

    def cmd_setup(
        self,
        num_agents: int,
        max_iterations: int,
        task: Optional[str] = None,
        backend: str = SpawnBackend.AUTO.value,
        plan_file: Optional[str] = None,
    ) -> dict:
        """
        Initialize Ralph session infrastructure without spawning agents.

        Creates:
        - State file (.claude/ralph/state.json)
        - Team config (.claude/ralph/team-{session}/config.json)
        - Agent inboxes (.claude/ralph/team-{session}/inbox/)
        - Heartbeat directory (.claude/ralph/team-{session}/heartbeat/)
        - Checkpoint directory

        Returns:
            Setup result dict with session_id and paths.
        """
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Determine effective backend
        effective_backend = backend
        if backend == SpawnBackend.AUTO.value:
            effective_backend = (
                SpawnBackend.TASK.value if num_agents <= 10
                else SpawnBackend.AUTO.value  # Will batch Task + subprocess overflow
            )

        # Create agent states
        agents = [
            AgentState(
                agent_id=i,
                max_iterations=max_iterations,
                status=AgentStatus.PENDING.value,
            )
            for i in range(num_agents)
        ]

        # Create Ralph state
        state = RalphState(
            session_id=session_id,
            task=task,
            total_agents=num_agents,
            max_iterations=max_iterations,
            agents=agents,
            started_at=datetime.now().isoformat(),
            checkpoint_path=plan_file,
        )
        self.write_state(state)
        self.create_checkpoint(state)

        # Create team config with gist-compatible env vars (Step 6)
        team_name = os.environ.get("CLAUDE_CODE_TEAM_NAME", f"ralph-{session_id}")
        team_config = TeamConfig(
            session_id=session_id,
            leader_agent="agent-0",
            agents=[
                {
                    "id": f"agent-{i}",
                    "role": assign_review_specialty(i) if i > 0 else "leader",
                    "status": "pending",
                }
                for i in range(num_agents)
            ],
            backend=effective_backend,
            created_at=datetime.now().isoformat(),
            env_vars={
                "CLAUDE_CODE_TEAM_NAME": team_name,
                "RALPH_PARENT_SESSION_ID": session_id,
                "RALPH_SUBAGENT": "true",
            },
        )

        # Initialize inbox system
        inbox = AgentInbox(session_id, "agent-0", self.base_dir)
        inbox.write_team_config(team_config)

        # Create empty inboxes for all agents
        for i in range(num_agents):
            agent_inbox_path = inbox.inbox_dir / f"agent-{i}.json"
            if not agent_inbox_path.exists():
                with open(agent_inbox_path, "w") as f:
                    json.dump([], f)

        result = {
            "session_id": session_id,
            "backend": effective_backend,
            "num_agents": num_agents,
            "max_iterations": max_iterations,
            "team_dir": str(inbox.team_dir),
            "state_path": str(self.state_path),
            "task": task,
        }

        self.log_activity(f"Setup complete: {session_id} ({effective_backend} backend, {num_agents} agents)")
        print(json.dumps(result, indent=2))
        return result

    def cmd_teardown(self, keep_logs: bool = True) -> dict:
        """
        Clean up Ralph session after completion.

        Performs:
        - Structured shutdown (sends shutdown_request to all agents)
        - Cleans up team directory (inboxes, heartbeats, relay)
        - Preserves activity log and final state if keep_logs=True
        - Archives results to context-relay.json

        Returns:
            Teardown result dict.
        """
        state = self.read_state()
        results = {"cleaned": [], "preserved": [], "errors": []}

        if state:
            session_id = state.session_id

            # Send shutdown request via leader inbox
            try:
                inbox = AgentInbox(session_id, "agent-0", self.base_dir)
                inbox.request_shutdown()
                results["cleaned"].append("shutdown_request_sent")
            except Exception as e:
                results["errors"].append(f"shutdown_request: {e}")

            # Write context relay summary
            try:
                relay_path = self.base_dir / ".claude" / "ralph" / "context-relay.json"
                relay_data = {
                    "session_id": session_id,
                    "task": state.task,
                    "completed_at": datetime.now().isoformat(),
                    "total_agents": state.total_agents,
                    "agents": [
                        {
                            "id": (a.agent_id if isinstance(a, AgentState) else a.get("agent_id")),
                            "status": (a.status if isinstance(a, AgentState) else a.get("status")),
                        }
                        for a in state.agents
                    ],
                    "phase": state.phase,
                }
                relay_path.parent.mkdir(parents=True, exist_ok=True)
                with open(relay_path, "w") as f:
                    json.dump(relay_data, f, indent=2)
                results["preserved"].append(str(relay_path))
            except Exception as e:
                results["errors"].append(f"context_relay: {e}")

            # Clean team directory
            team_dir = self.base_dir / ".claude" / "ralph" / f"team-{session_id}"
            if team_dir.exists():
                try:
                    shutil.rmtree(team_dir)
                    results["cleaned"].append(str(team_dir))
                except OSError as e:
                    results["errors"].append(f"team_dir: {e}")

            # Mark state as complete
            state.completed_at = datetime.now().isoformat()
            state.phase = "complete"
            self.write_state(state)
        else:
            results["errors"].append("no_active_session")

        # Run standard cleanup
        cleanup_results = self.cleanup_ralph_session(keep_activity_log=keep_logs)
        results["cleaned"].extend(cleanup_results["deleted"])
        results["preserved"].extend(cleanup_results["preserved"])
        results["errors"].extend(cleanup_results["errors"])

        self.log_activity(f"Teardown: {len(results['cleaned'])} cleaned, {len(results['errors'])} errors")
        print(json.dumps(results, indent=2))
        return results

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
        """Build the initial prompt for an agent with agent config loading (Step 3)."""
        # Discover and assign agent config via round-robin
        all_configs = discover_agent_configs()
        config_names = list(all_configs.keys())
        agent_config_content = ""
        assigned_role = "general"

        if config_names:
            # Round-robin assignment
            config_name = config_names[agent.agent_id % len(config_names)]
            config_path = all_configs[config_name]
            agent_config_content = load_agent_config(config_path)
            assigned_role = config_name

        # Read team state for inbox info
        state = self.read_state()
        session_id = state.session_id if state else "unknown"
        total = state.total_agents if state else 1

        # Build enhanced prompt
        role_section = ""
        if agent_config_content:
            role_section = f"""
ROLE CONFIG ({assigned_role}):
{agent_config_content[:2000]}
"""

        inbox_section = f"""
COORDINATION:
- Check inbox: .claude/ralph/team-{session_id}/inbox/agent-{agent.agent_id}.json
- Report completion: write task_completed message to relay
- If idle: write idle_notification message
- Heartbeat: write to .claude/ralph/team-{session_id}/heartbeat/agent-{agent.agent_id}.json
"""

        return f"""You are Ralph Agent {agent.agent_id}/{total} working on: {task or 'Complete the assigned development work'}

ASSIGNMENT: {assigned_role}
ITERATION: {agent.current_iteration + 1} of {agent.max_iterations}
{role_section}
WORK PROTOCOL:
1. Call TaskList to see available tasks
2. Claim next available task (status=pending, no blockers)
3. Work autonomously — no confirmation needed
4. Push ALL commits before signaling completion
5. Mark task completed, claim next
6. When all your work is done, output EXACTLY:
   {self.RALPH_COMPLETE_SIGNAL}
   {self.EXIT_SIGNAL}
{inbox_section}
TOOLS: All standard tools + Serena MCP + Context7 MCP

Begin working now.
"""


def _debug_exit(reason: str, code: int = 0) -> None:
    """Exit with optional debug logging.

    When RALPH_DEBUG=1 is set, logs the exit reason to stderr.
    All 6+ silent exit points in agent-tracker go through this helper.
    """
    if os.environ.get("RALPH_DEBUG"):
        import sys as _sys
        _sys.stderr.write(f"[ralph agent-tracker] exit({code}): {reason}\n")
    sys.exit(code)


def agent_tracker() -> None:
    """Track Ralph agent completion and enforce phase transitions.

    Consolidated from guards.py ralph_agent_tracker().
    Fires after each Task tool completes. Updates state.json with:
    - Completed agent count
    - Phase transitions (implementation → review → complete)
    - Debug logging via _debug_exit() (env-gated: RALPH_DEBUG)
    - Stale session auto-cleanup (>4h marks as complete with staleReason)
    """
    # Set timeout for stdin read (cross-platform)
    if sys.platform == "win32":
        import threading

        def _timeout_win():
            _debug_exit("stdin read timeout", 0)
            os._exit(0)

        _timer = threading.Timer(10, _timeout_win)
        _timer.daemon = True
        _timer.start()
    else:
        import signal

        def _timeout_handler(signum, frame):
            _debug_exit("stdin read timeout", 0)

        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(10)  # 10 second timeout

    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        _debug_exit("invalid JSON on stdin", 0)

    if sys.platform == "win32":
        _timer.cancel()
    else:
        import signal
        signal.alarm(0)  # Cancel timeout

    tool_name = data.get("tool_name", "")

    # Only trigger on Task completion
    if tool_name != "Task":
        _debug_exit(f"tool_name={tool_name}, not Task", 0)

    # Check for active state file
    state_path = Path(".claude/ralph/state.json")
    if not state_path.exists():
        state_path = Path(".claude/ralph-state.json")  # Legacy
        if not state_path.exists():
            _debug_exit("no state file found", 0)

    try:
        with open(state_path) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _debug_exit(f"state file unreadable: {e}", 0)

    # Skip if already complete
    phase = state.get("phase", "implementation")
    if phase == "complete":
        _debug_exit("phase already complete", 0)

    # Check for stale session (>4h old) — auto-cleanup (Fix B)
    started_at = state.get("startedAt") or state.get("started_at")
    if started_at:
        try:
            start_time = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            age_hours = (datetime.now(timezone.utc) - start_time).total_seconds() / 3600
            if age_hours > 4:
                # Mark as complete with stale reason instead of silently ignoring
                state["phase"] = "complete"
                state["staleReason"] = f"Session age {age_hours:.1f}h exceeds 4h threshold"
                state["completedAt"] = datetime.now(timezone.utc).isoformat()
                try:
                    with open(state_path, "w") as f:
                        json.dump(state, f, indent=2)
                except OSError:
                    pass
                _debug_exit(f"stale session ({age_hours:.1f}h), marked complete", 0)
        except (ValueError, TypeError) as e:
            _debug_exit(f"timestamp parse error: {e}", 0)

    # Track completion
    completed = state.get("completedAgents", 0) + 1
    state["completedAgents"] = completed

    timestamp = datetime.now(timezone.utc).isoformat()

    # Log activity
    activity_log = state.get("activityLog", [])
    activity_log.append({
        "timestamp": timestamp,
        "event": "agent_completed",
        "phase": phase,
        "completed": completed
    })
    state["activityLog"] = activity_log[-50:]  # Keep last 50

    # Determine phase transition
    output_msg = None

    if phase == "implementation":
        agents_field = state.get("agents", 3)
        expected = state.get("total_agents") or (len(agents_field) if isinstance(agents_field, list) else agents_field)
        if completed >= expected:
            # All implementation agents done → transition to review
            review_config = state.get("review", {"agents": 5, "iterations": 2})
            review_agents = review_config.get("agents", 5)
            review_iterations = review_config.get("iterations", 2)
            task = state.get("task", "Review the implementation")

            state["phase"] = "review"
            state["completedAgents"] = 0  # Reset for review phase

            activity_log.append({
                "timestamp": timestamp,
                "event": "phase_transition",
                "from": "implementation",
                "to": "review"
            })

            output_msg = f"""🔄 RALPH PHASE TRANSITION: Implementation → Review

All {expected} implementation agents completed.

**MANDATORY NEXT STEP:**
Spawn {review_agents} review agents IN PARALLEL:

```
Task(subagent_type: "general-purpose", prompt: "RALPH Review Agent 1/{review_agents}: Review implementation for {task}")
Task(subagent_type: "general-purpose", prompt: "RALPH Review Agent 2/{review_agents}: Review implementation for {task}")
... (spawn all {review_agents} agents in a single message)
```

Review agents should:
1. Check for bugs, security issues, performance problems
2. Leave TODO comments (do NOT auto-fix)
3. Report findings to .claude/review-agents.md

**DO NOT** output completion signals yet. Spawn review agents NOW."""

    elif phase == "review":
        review_config = state.get("review", {"agents": 5, "iterations": 2})
        expected = review_config.get("agents", 5)
        if completed >= expected:
            # All review agents done → signal completion
            state["phase"] = "complete"
            state["completedAt"] = timestamp

            activity_log.append({
                "timestamp": timestamp,
                "event": "phase_transition",
                "from": "review",
                "to": "complete"
            })

            output_msg = f"""✅ RALPH LOOP COMPLETE

All {expected} review agents completed.

**MANDATORY FINAL STEP:**
Output BOTH completion signals NOW:

```
<promise>RALPH_COMPLETE</promise>
EXIT_SIGNAL: true
```

This will allow the session to exit properly.

**Summary:**
- Implementation agents: {state.get("total_agents", len(state["agents"]) if isinstance(state.get("agents"), list) else state.get("agents", "?"))} completed
- Review agents: {expected} completed
- Task: {state.get("task", "N/A")}
- Duration: {state.get("startedAt", "?")} → {timestamp}"""

    # Write updated state
    try:
        with open(state_path, "w") as f:
            json.dump(state, f, indent=2)
    except OSError as e:
        _debug_exit(f"state write failed: {e}", 0)

    # Output phase transition instructions
    if output_msg:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": output_msg
            }
        }
        print(json.dumps(output))

    _debug_exit(f"tracked completion #{completed} in phase={phase}", 0)


def preflight_check() -> None:
    """Pre-session preflight: archive/remove stale state files (Fix D).

    Called by `ralph.py loop` before starting a new session.
    Checks for existing state files that are stale (>4h) and archives them.
    """
    state_path = Path(".claude/ralph/state.json")
    if not state_path.exists():
        return

    try:
        with open(state_path) as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupted state, remove it
        try:
            state_path.unlink()
        except OSError:
            pass
        return

    started_at = state.get("startedAt") or state.get("started_at")
    if not started_at:
        return

    try:
        start_time = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - start_time).total_seconds() / 3600

        if age_hours > 4:
            # Archive stale state
            archive_dir = Path(".claude/ralph/checkpoints")
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_name = f"stale_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            archive_path = archive_dir / archive_name

            state["staleReason"] = f"Archived by preflight_check (age: {age_hours:.1f}h)"
            with open(archive_path, "w") as f:
                json.dump(state, f, indent=2)
            state_path.unlink()

            if os.environ.get("RALPH_DEBUG"):
                sys.stderr.write(
                    f"[ralph preflight] Archived stale state ({age_hours:.1f}h) to {archive_path}\n"
                )
    except (ValueError, TypeError, OSError):
        pass


def print_usage():
    """Print CLI usage information."""
    print("""
Ralph Protocol - Autonomous Agent Loop Manager

Usage:
    ralph.py loop N M [OPTIONS] [task]  - Run N agents × M iterations
    ralph.py setup N M [OPTIONS] [task] - Initialize session (no spawning)
    ralph.py teardown [--no-logs]       - Clean up after session
    ralph.py status                     - Show current Ralph state
    ralph.py resume                     - Resume from latest checkpoint
    ralph.py cleanup                    - Clean up all state files
    ralph.py cleanup --auto             - Auto-cleanup old files (default: 7 days)
    ralph.py cleanup --auto --max-age N - Auto-cleanup files older than N days
    ralph.py agent-tracker              - Handle PostToolUse:Task hook (reads stdin)
    ralph.py hook-stop                  - Handle hook-stop (reads stdin)
    ralph.py hook-pretool               - Handle hook-pretool (reads stdin)
    ralph.py hook-user-prompt           - Handle hook-user-prompt (reads stdin)
    ralph.py hook-session               - Handle hook-session-start (reads stdin)

Loop / Setup Options:
    --review-agents RN      Number of post-review agents (default: 5)
    --review-iterations RM  Iterations per review agent (default: 2)
    --skip-review           Skip post-implementation review
    --plan FILE             Path to plan file being executed
    --backend BACKEND       Spawn backend: task|subprocess|auto (default: auto)

Cleanup Options:
    --auto                  Run age-based cleanup instead of full cleanup
    --max-age N             Days threshold for auto-cleanup (default: 7)

Examples:
    ralph.py loop 3 3 "Implement feature X"
    ralph.py loop 50 15 --review-agents 15 --review-iterations 10 "Big feature"
    ralph.py loop 10 5 --skip-review "Quick fix"
    ralph.py loop 30 10 --plan /path/to/plan.md "Execute plan"
    ralph.py loop 15 5 --backend task "Use Task tool"
    ralph.py setup 10 3 --backend task "Initialize only"
    ralph.py teardown
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
        backend = SpawnBackend.AUTO.value
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
            elif arg == "--backend" and i + 1 < len(sys.argv):
                backend = sys.argv[i + 1]
                if backend not in [b.value for b in SpawnBackend]:
                    print(f"Error: --backend must be one of: task, subprocess, auto")
                    sys.exit(1)
                i += 2
            else:
                task_parts.append(arg)
                i += 1

        task = " ".join(task_parts) if task_parts else None

        # Preflight: archive stale state files before starting new session (Fix D)
        preflight_check()

        print(f"Starting Ralph loop: {num_agents} agents × {max_iterations} iterations")
        print(f"Backend: {backend}")
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
            plan_file=plan_file,
            backend=backend,
        ))

    elif command == "setup":
        # Step 1: Initialize session infrastructure without spawning
        if len(sys.argv) < 4:
            print("Usage: ralph.py setup N M [OPTIONS] [task]")
            sys.exit(1)
        try:
            num_agents = int(sys.argv[2])
            max_iterations = int(sys.argv[3])
        except ValueError:
            print("Error: N and M must be integers")
            sys.exit(1)

        # Parse setup options
        setup_backend = SpawnBackend.AUTO.value
        setup_plan = None
        setup_task_parts = []
        j = 4
        while j < len(sys.argv):
            arg = sys.argv[j]
            if arg == "--backend" and j + 1 < len(sys.argv):
                setup_backend = sys.argv[j + 1]
                j += 2
            elif arg == "--plan" and j + 1 < len(sys.argv):
                setup_plan = sys.argv[j + 1]
                j += 2
            else:
                setup_task_parts.append(arg)
                j += 1
        setup_task = " ".join(setup_task_parts) if setup_task_parts else None

        protocol.cmd_setup(
            num_agents, max_iterations,
            task=setup_task, backend=setup_backend, plan_file=setup_plan
        )

    elif command == "teardown":
        # Step 1: Clean up after session completion
        keep_logs = "--no-logs" not in sys.argv
        protocol.cmd_teardown(keep_logs=keep_logs)

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

    elif command == "agent-tracker":
        # PostToolUse:Task hook - consolidated from guards.py
        agent_tracker()

    elif command == "hook-pre-compact":
        # PreCompact handler - create checkpoint before context compaction
        result = None
        if protocol.state_exists():
            state = protocol.read_state()
            if state is not None:
                try:
                    result = protocol.create_checkpoint(state)
                except Exception as e:
                    protocol.log_activity(f"PreCompact checkpoint failed: {e}", level="ERROR")
        print(json.dumps({"checkpoint_created": result is not None}))

    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise  # Allow explicit sys.exit() calls
    except Exception as e:
        # Defense-in-depth: hook commands must NEVER crash with non-zero exit.
        # A crash during PreCompact kills compaction entirely.
        command = sys.argv[1] if len(sys.argv) > 1 else ""
        if command.startswith("hook-"):
            print(json.dumps({"error": str(e), "hook_safe_exit": True}), file=sys.stderr)
            sys.exit(0)  # Hooks must exit 0 to not block Claude Code
        else:
            raise  # Non-hook commands can crash normally
