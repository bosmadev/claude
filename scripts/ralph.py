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

Spawn Backends:
- subprocess: Spawns agents as separate `claude --print` processes (default)
- task: Generates prompts for manual Task() spawning in parent Claude session
- auto: Uses Task for <=10 agents, subprocess for overflow

Usage:
    ralph.py loop N M [task]         - Run N agents × M iterations (subprocess backend)
    ralph.py prompt N [task]         - Generate N prompts for Task() spawning
    ralph.py status                  - Show current state
    ralph.py resume                  - Resume from checkpoint
    ralph.py cleanup                 - Clean state files

Task Backend Workflow:
    The 'task' backend requires manual Task() spawning from the parent Claude session
    because ralph.py runs as a subprocess and cannot directly invoke the Task tool.
    
    Example:
        1. Generate prompts: python ralph.py prompt 5 "implement auth"
        2. In parent Claude session, spawn each prompt via Task tool:
           Task(prompt="...agent 1 prompt...")
           Task(prompt="...agent 2 prompt...")
           ...
        3. All agents share the same TaskList and coordinate via Ralph protocol
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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from zoneinfo import ZoneInfo

# Import Ralph library functions
from ralph_lib import (
    build_agent_prompt,
    load_agent_config,
    match_agent_to_task,
    discover_agent_configs,
    generate_agent_name,
    _get_agents_dir,
    AGENT_SPECIALTIES,
)

# Optional Redis import for real-time context injection
try:
    from redis import Redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    Redis = None  # type: ignore


# =============================================================================
# Redis Hybrid Context Injection
# =============================================================================

REDIS_HOST = "localhost"
REDIS_PORT = 6379
CONTEXT_FILE_PATH = Path.home() / ".claude" / ".claude" / "ralph" / "pending-context.md"

# =============================================================================
# Model Configuration for VERIFY+FIX Phases
# =============================================================================

# Model to use for all VERIFY+FIX operations
VERIFY_FIX_MODEL = "claude-opus-4-6"  # Current Opus, date-less alias

# Effort levels for different VERIFY+FIX modes
VERIFY_FIX_EFFORT: dict[str, str] = {
    "scoped": "medium",   # Per-task verification: fast, focused
    "full": "high",       # Post-all-impl: thorough final gate
    "plan": "medium",     # Plan verification: moderate depth
}


# =============================================================================
# Receipt Audit Trail System
# =============================================================================

RECEIPTS_DIR = Path.home() / ".claude" / ".claude" / "ralph" / "receipts"


def write_receipt(
    agent_id: str,
    action: str,
    details: dict[str, Any],
    session_id: str | None = None
) -> bool:
    """
    Write an audit receipt for an agent action.

    Receipts track all agent activities: starts, completions, errors, file edits,
    task state changes. Used for debugging, compliance, and build intelligence.

    Args:
        agent_id: Agent identifier (e.g., "agent-1", "review-2")
        action: Action type - "agent_start", "agent_complete", "agent_error",
                "file_edit", "task_complete", "command_run"
        details: Action-specific metadata (file paths, error messages, etc.)
        session_id: Ralph session ID (auto-detected if None)

    Returns:
        True if receipt written successfully, False otherwise.

    Receipt Format:
        {
            "id": "uuid",
            "timestamp": "ISO8601",
            "agent_id": "agent-1",
            "action": "file_edit",
            "details": {"file": "src/app.py", "change": "add function"},
            "session_id": "abc123"
        }

    Example:
        >>> write_receipt("agent-3", "file_edit", {"file": "app.py", "lines": "10-20"})
        >>> write_receipt("agent-1", "agent_error", {"error": "timeout", "retry": 2})
    """
    try:
        # Ensure receipts directory exists
        RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)

        # Auto-detect session_id from checkpoint if not provided
        if session_id is None:
            checkpoint = Path.home() / ".claude" / ".claude" / "ralph" / "checkpoint.json"
            if checkpoint.exists():
                try:
                    state = json.loads(checkpoint.read_text(encoding="utf-8"))
                    session_id = state.get("session_id", "unknown")
                except (json.JSONDecodeError, OSError):
                    session_id = "unknown"
            else:
                session_id = "unknown"

        # Generate receipt
        timestamp = datetime.now(timezone.utc).isoformat()
        receipt = {
            "id": str(uuid.uuid4()),
            "timestamp": timestamp,
            "agent_id": agent_id,
            "action": action,
            "details": details,
            "session_id": session_id,
        }

        # Write to timestamped JSON file
        # Format: 20260206_120000_agent-1_file-edit.json
        time_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Sanitize action for filename (replace underscores with hyphens)
        action_safe = action.replace("_", "-")
        filename = f"{time_str}_{agent_id}_{action_safe}.json"
        receipt_path = RECEIPTS_DIR / filename

        receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        return True

    except (OSError, TypeError, ValueError):
        # Fail silently - receipts are best-effort audit logs
        return False


def inject_context(context: str, agent_id: str | None = None) -> bool:
    """
    Inject context to running agents via Redis pub/sub with file fallback.

    Uses Redis for real-time delivery when available, falls back to file-based
    injection when Redis is down or not installed.

    Args:
        context: The context/hint to inject (markdown string).
        agent_id: Optional specific agent ID, or None for broadcast to all.

    Returns:
        True if injection succeeded, False otherwise.

    Example:
        >>> inject_context("Try checking the import paths", "agent-3")
        >>> inject_context("Use the singleton pattern for the cache")  # broadcast
    """
    # Try Redis first for real-time delivery
    if REDIS_AVAILABLE:
        try:
            redis = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            channel = f"ralph:context:{agent_id or 'all'}"
            redis.publish(channel, context)
            redis.close()
            return True
        except Exception:
            pass  # Fall through to file-based

    # Fallback to file-based injection
    try:
        CONTEXT_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Append with agent targeting
        entry = f"---\nagent: {agent_id or 'all'}\ntime: {datetime.now().isoformat()}\n---\n{context}\n\n"
        with open(CONTEXT_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(entry)
        return True
    except OSError:
        return False


def receive_context(agent_id: str, timeout: float = 0.1) -> str | None:
    """
    Receive injected context for an agent via Redis sub with file fallback.

    Checks Redis pub/sub first, then falls back to reading from file.
    Consumes the context (removes from file after reading).

    Args:
        agent_id: The agent ID to receive context for.
        timeout: Redis subscription timeout in seconds.

    Returns:
        Context string if available, None otherwise.
    """
    # Try Redis first
    if REDIS_AVAILABLE:
        try:
            redis = Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
            pubsub = redis.pubsub()
            pubsub.subscribe(f"ralph:context:{agent_id}", "ralph:context:all")
            message = pubsub.get_message(timeout=timeout)
            pubsub.close()
            redis.close()
            if message and message.get("type") == "message":
                return message.get("data")
        except (OSError, ConnectionError, TimeoutError):
            # Specific exceptions for network/Redis failures only
            pass  # Fall through to file-based

    # Fallback to file-based
    if not CONTEXT_FILE_PATH.exists():
        return None

    try:
        content = CONTEXT_FILE_PATH.read_text(encoding="utf-8")
        if not content.strip():
            return None

        # Parse and find context for this agent
        entries = content.split("---\nagent:")
        remaining = []
        found_context = None

        for entry in entries:
            if not entry.strip():
                continue
            lines = entry.strip().split("\n")
            if lines:
                target = lines[0].strip()
                if target in (agent_id, "all") and found_context is None:
                    # Extract context (skip metadata lines)
                    context_start = next(
                        (i for i, line in enumerate(lines) if line.startswith("---")),
                        1
                    )
                    found_context = "\n".join(lines[context_start + 1:]).strip()
                else:
                    remaining.append(f"---\nagent:{entry}")

        # Write back remaining entries
        if remaining:
            CONTEXT_FILE_PATH.write_text("".join(remaining), encoding="utf-8")
        else:
            CONTEXT_FILE_PATH.unlink(missing_ok=True)

        return found_context
    except OSError:
        return None


class LifecyclePhase(str, Enum):
    """Ralph session lifecycle phases."""
    PLAN = "plan"
    IMPLEMENT = "implementation"
    VERIFY_FIX = "verify_fix"
    REVIEW = "review"
    COMPLETE = "complete"


class ModelMode(str, Enum):
    """Model routing modes for agent spawning."""
    OPUS = "opus"
    SONNET = "sonnet"
    SONNET_ALL = "sonnet_all"


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
    PENDING_VERIFY = "pending_verify"  # Awaiting per-task verify+fix
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
    # Per-task verify+fix tracking
    changed_files: list = field(default_factory=list)  # Files changed by this agent
    verify_fix_passed: Optional[bool] = None  # Result of per-task verify+fix
    verify_fix_agent_id: Optional[int] = None  # ID of scoped verify+fix agent


@dataclass
class StruggleMetrics:
    """Metrics tracking for an individual agent's struggle state."""
    error_count: int = 0
    retry_count: int = 0
    elapsed_time: float = 0.0
    last_error: str = ""
    struggling: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "errors": self.error_count,
            "retries": self.retry_count,
            "elapsed_time": round(self.elapsed_time, 2),
            "last_error": self.last_error[:200] if self.last_error else "",
            "struggling": self.struggling
        }


class StruggleDetector:
    """
    Detect when agents are struggling with repeated failures.
    
    Tracks error counts, retry attempts, and elapsed time per agent.
    Writes build intelligence data to .claude/ralph/build-intelligence.json.
    
    Struggle thresholds:
    - Error count > 3
    - Retry count > 5
    - Slow progress (implementation-specific)
    """
    
    OUTPUT_FILE = ".claude/ralph/build-intelligence.json"
    ERROR_THRESHOLD = 3
    RETRY_THRESHOLD = 5
    
    def __init__(self, base_dir: Path):
        """
        Initialize StruggleDetector.
        
        Args:
            base_dir: Base directory for output files
        """
        self.base_dir = base_dir
        self.output_path = base_dir / self.OUTPUT_FILE
        self._metrics: dict[str, StruggleMetrics] = {}
        self._start_times: dict[str, datetime] = {}
    
    def record_error(self, agent_id: str, error_msg: str = "") -> None:
        """
        Record an error for an agent.
        
        Args:
            agent_id: Agent identifier (e.g., "agent-1")
            error_msg: Error message text
        """
        if agent_id not in self._metrics:
            self._metrics[agent_id] = StruggleMetrics()
        
        metrics = self._metrics[agent_id]
        metrics.error_count += 1
        if error_msg:
            metrics.last_error = error_msg
        
        # Update struggle state
        self._update_struggle_state(agent_id)
    
    def record_retry(self, agent_id: str) -> None:
        """
        Record a retry attempt for an agent.
        
        Args:
            agent_id: Agent identifier
        """
        if agent_id not in self._metrics:
            self._metrics[agent_id] = StruggleMetrics()
        
        self._metrics[agent_id].retry_count += 1
        self._update_struggle_state(agent_id)
    
    def start_tracking(self, agent_id: str) -> None:
        """
        Start time tracking for an agent.
        
        Args:
            agent_id: Agent identifier
        """
        self._start_times[agent_id] = datetime.now()
    
    def stop_tracking(self, agent_id: str) -> None:
        """
        Stop time tracking and update elapsed time.
        
        Args:
            agent_id: Agent identifier
        """
        if agent_id in self._start_times:
            elapsed = (datetime.now() - self._start_times[agent_id]).total_seconds()
            if agent_id not in self._metrics:
                self._metrics[agent_id] = StruggleMetrics()
            self._metrics[agent_id].elapsed_time = elapsed
            del self._start_times[agent_id]
    
    def is_struggling(self, agent_id: str) -> bool:
        """
        Check if an agent is currently struggling.
        
        Args:
            agent_id: Agent identifier
            
        Returns:
            True if agent is struggling
        """
        if agent_id not in self._metrics:
            return False
        return self._metrics[agent_id].struggling
    
    def get_struggle_summary(self) -> dict:
        """
        Get summary of struggling agents.
        
        Returns:
            Dictionary with total_struggling and total_agents counts
        """
        struggling = sum(1 for m in self._metrics.values() if m.struggling)
        return {
            "total_struggling": struggling,
            "total_agents": len(self._metrics)
        }
    
    def write_intelligence(self) -> None:
        """Write build intelligence data to JSON file."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "timestamp": datetime.now().isoformat(),
            "agents": {
                agent_id: metrics.to_dict()
                for agent_id, metrics in self._metrics.items()
            },
            "summary": self.get_struggle_summary()
        }
        
        try:
            self.output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, TypeError) as e:
            # Log but don't fail - intelligence is nice-to-have
            print(f"Warning: Failed to write build intelligence: {e}", file=sys.stderr)
    
    def _update_struggle_state(self, agent_id: str) -> None:
        """
        Update struggling flag based on thresholds.
        
        Args:
            agent_id: Agent identifier
        """
        metrics = self._metrics[agent_id]
        metrics.struggling = (
            metrics.error_count > self.ERROR_THRESHOLD or
            metrics.retry_count > self.RETRY_THRESHOLD
        )


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
    # Plan verification retry tracking
    plan_verification_retries: int = 0

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
            "plan_verification_retries": self.plan_verification_retries,
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
            # Plan verification retry tracking
            plan_verification_retries=data.get("plan_verification_retries", 0),
        )


# =============================================================================
# Work-Stealing Queue
# =============================================================================

@dataclass
class QueueTask:
    """Task in the work-stealing queue."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str = ""  # Task description for markdown format
    status: str = "pending"
    blocked_by: list = field(default_factory=list)
    claimed_by: Optional[str] = None
    iterations: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
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
            description=data.get("description", ""),
            status=data.get("status", "pending"),
            blocked_by=data.get("blockedBy", []),
            claimed_by=data.get("claimed_by"),
            iterations=data.get("iterations", 0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at")
        )


@dataclass
class TaskQueue:
    """Work-stealing task queue tied to a plan file (supports JSON and Markdown)."""
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
    
    def to_markdown(self) -> str:
        """
        Generate markdown representation of task queue.
        
        Format:
        ---
        plan_id: feature-auth
        created: 2026-02-04T10:00:00Z
        total_tasks: 5
        completed: 2
        ---
        
        # Task Queue: feature-auth
        
        ## ✅ Completed
        - [x] Task 1: Description (agent-abc123)
        
        ## 🔄 In Progress
        - [/] Task 2: Description (agent-def456)
        
        ## ⏳ Pending
        - [ ] Task 3: Description
        """
        completed = [t for t in self.tasks if t.status == "completed"]
        in_progress = [t for t in self.tasks if t.status == "in_progress"]
        pending = [t for t in self.tasks if t.status == "pending"]
        
        lines = [
            "---",
            f"plan_id: {self.plan_id}",
            f"created: {self.created_at}",
            f"total_tasks: {len(self.tasks)}",
            f"completed: {len(completed)}",
            "---",
            "",
            f"# Task Queue: {self.plan_id}",
            ""
        ]
        
        if completed:
            lines.append("## ✅ Completed")
            for task in completed:
                agent_info = f" ({task.claimed_by})" if task.claimed_by else ""
                lines.append(f"- [x] Task {task.id}: {task.description}{agent_info}")
            lines.append("")
        
        if in_progress:
            lines.append("## 🔄 In Progress")
            for task in in_progress:
                agent_info = f" ({task.claimed_by})" if task.claimed_by else ""
                lines.append(f"- [/] Task {task.id}: {task.description}{agent_info}")
            lines.append("")
        
        if pending:
            lines.append("## ⏳ Pending")
            for task in pending:
                blocked_info = f" (blocked by: {', '.join(task.blocked_by)})" if task.blocked_by else ""
                lines.append(f"- [ ] Task {task.id}: {task.description}{blocked_info}")
            lines.append("")
        
        return "\n".join(lines)
    
    @classmethod
    def from_markdown(cls, content: str, plan_id: str = None, plan_file: str = None) -> "TaskQueue":
        """
        Parse markdown task queue into TaskQueue object.
        
        Recognizes:
        - [ ] = pending
        - [/] = in_progress
        - [x] = completed
        """
        import re
        
        lines = content.split("\n")
        
        # Parse frontmatter
        in_frontmatter = False
        frontmatter = {}
        tasks_section = []
        
        for line in lines:
            if line.strip() == "---":
                if not in_frontmatter:
                    in_frontmatter = True
                    continue
                else:
                    in_frontmatter = False
                    continue
            
            if in_frontmatter:
                if ":" in line:
                    key, value = line.split(":", 1)
                    frontmatter[key.strip()] = value.strip()
            else:
                tasks_section.append(line)
        
        # Extract task info from frontmatter or args
        extracted_plan_id = plan_id or frontmatter.get("plan_id", "unknown")
        extracted_plan_file = plan_file or frontmatter.get("plan_file", "")
        created_at = frontmatter.get("created", datetime.now().isoformat())
        
        # Parse task list items
        tasks = []
        task_pattern = re.compile(r"^-\s+\[([ x/])\]\s+Task\s+(\d+):\s+(.+?)(?:\s+\(([^)]+)\))?(?:\s+\(blocked by:\s+([^)]+)\))?$")
        
        for line in tasks_section:
            match = task_pattern.match(line.strip())
            if match:
                checkbox, task_id, description, claimed_by, blocked_by = match.groups()
                
                # Determine status from checkbox
                if checkbox == "x":
                    status = "completed"
                elif checkbox == "/":
                    status = "in_progress"
                else:
                    status = "pending"
                
                # Parse blocked_by list
                blocked_list = []
                if blocked_by:
                    blocked_list = [b.strip() for b in blocked_by.split(",")]
                
                tasks.append(QueueTask(
                    id=task_id,
                    description=description.strip(),
                    status=status,
                    claimed_by=claimed_by,
                    blocked_by=blocked_list
                ))
        
        return cls(
            plan_id=extracted_plan_id,
            plan_file=extracted_plan_file,
            created_at=created_at,
            tasks=tasks
        )


class TaskQueueParser:
    """
    Parser for markdown task lists with priority-based format.
    
    Supports formats:
    - [ ] P1: Description — blocked by: task-name
    - [x] P2: Description — completed
    - [ ] P3: Description — depends on: task-name
    
    Features:
    - Priority extraction (P1/P2/P3)
    - Status parsing (pending/in_progress/completed)
    - Dependency detection (blocked by/depends on)
    - Plan file parsing
    - Round-trip conversion (markdown ↔ QueueTask)
    """
    
    @staticmethod
    def parse_markdown(content: str) -> list[QueueTask]:
        """
        Parse markdown content into list of QueueTask objects.
        
        Recognizes:
        - [ ] = pending
        - [/] = in_progress
        - [x] = completed
        - P1/P2/P3 = priority (stored in description)
        - "blocked by:" or "depends on:" = dependencies
        
        Args:
            content: Markdown text with task list items
            
        Returns:
            List of QueueTask objects
        """
        import re
        
        tasks = []
        lines = content.split("\n")
        
        # Pattern: - [checkbox] P1: Description — blocked by: task-name
        # More flexible: supports various dependency keywords
        task_pattern = re.compile(
            r"^-\s+\[([ x/])\]\s+(?:P[123]:\s+)?(.+?)(?:\s+[—–-]\s+(?:blocked by|depends on):\s+([^—–-]+))?$",
            re.IGNORECASE
        )
        
        for line in lines:
            stripped = line.strip()
            match = task_pattern.match(stripped)
            if not match:
                continue
            
            checkbox, description, dependencies = match.groups()
            
            # Determine status from checkbox
            if checkbox == "x":
                status = "completed"
            elif checkbox == "/":
                status = "in_progress"
            else:
                status = "pending"
            
            # Parse blocked_by list
            blocked_list = []
            if dependencies:
                blocked_list = [d.strip() for d in dependencies.split(",")]
            
            tasks.append(QueueTask(
                description=description.strip(),
                status=status,
                blocked_by=blocked_list
            ))
        
        return tasks
    
    @staticmethod
    def parse_plan_file(path: Path) -> list[QueueTask]:
        """
        Parse a plan markdown file and extract action items.
        
        Looks for task list items anywhere in the document.
        Useful for extracting work items from plan files.
        
        Args:
            path: Path to plan .md file
            
        Returns:
            List of QueueTask objects
        """
        if not path.exists():
            raise FileNotFoundError(f"Plan file not found: {path}")
        
        content = path.read_text(encoding="utf-8")
        return TaskQueueParser.parse_markdown(content)
    
    @staticmethod
    def to_markdown(tasks: list[QueueTask]) -> str:
        """
        Convert list of QueueTask objects to markdown format.
        
        Round-trip compatible with parse_markdown.
        
        Args:
            tasks: List of QueueTask objects
            
        Returns:
            Markdown-formatted task list
        """
        lines = []
        
        for task in tasks:
            # Determine checkbox
            if task.status == "completed":
                checkbox = "[x]"
            elif task.status == "in_progress":
                checkbox = "[/]"
            else:
                checkbox = "[ ]"
            
            # Build line
            line = f"- {checkbox} {task.description}"
            
            # Add dependencies if present
            if task.blocked_by:
                deps = ", ".join(task.blocked_by)
                line += f" — blocked by: {deps}"
            
            lines.append(line)
        
        return "\n".join(lines)


class WorkStealingQueue:
    """
    File-based work-stealing queue with atomic task claiming.

    Location: {project}/.claude/task-queue-{plan-id}.json

    Uses file locking to prevent race conditions when multiple
    agents attempt to claim tasks simultaneously.
    """

    QUEUE_DIR = ".claude"
    LOCK_SUFFIX = ".lock"

    def __init__(self, plan_id: str, plan_file: str, base_dir: Optional[Path] = None, format: str = "markdown"):
        self.plan_id = plan_id
        self.plan_file = plan_file
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.format = format  # "json" or "markdown"
        
        if format == "markdown":
            self.queue_path = self.base_dir / self.QUEUE_DIR / f"task-queue-{plan_id}.md"
        else:
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
        """Load queue from file (JSON or Markdown), creating if needed."""
        if self.queue_path.exists():
            try:
                if self.format == "markdown":
                    content = self.queue_path.read_text(encoding="utf-8")
                    return TaskQueue.from_markdown(content, self.plan_id, self.plan_file)
                else:
                    with open(self.queue_path) as f:
                        return TaskQueue.from_dict(json.load(f))
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

        # Create new queue
        return TaskQueue(
            plan_id=self.plan_id,
            plan_file=self.plan_file,
            created_at=datetime.now().isoformat(),
            tasks=[]
        )

    def save(self, queue: TaskQueue) -> None:
        """Save queue to file (JSON or Markdown)."""
        self._ensure_dir()
        
        if self.format == "markdown":
            content = queue.to_markdown()
            self.queue_path.write_text(content, encoding="utf-8")
        else:
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
# Structured Review Output
# =============================================================================

@dataclass
class ReviewFinding:
    """A single review finding from a review agent."""
    severity: str = "info"  # critical, high, medium, low, info
    category: str = "general"  # security, performance, architecture, etc.
    file_path: str = ""
    line_number: int = 0
    description: str = ""
    suggestion: str = ""
    agent_id: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "description": self.description,
            "suggestion": self.suggestion,
            "agent_id": self.agent_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ReviewFinding":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ReviewSummary:
    """Aggregated review summary from all review agents."""
    session_id: str = ""
    task: str = ""
    total_findings: int = 0
    findings_by_severity: dict = field(default_factory=dict)
    findings_by_category: dict = field(default_factory=dict)
    findings: list = field(default_factory=list)
    reviewed_at: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "task": self.task,
            "total_findings": self.total_findings,
            "findings_by_severity": self.findings_by_severity,
            "findings_by_category": self.findings_by_category,
            "findings": [f.to_dict() if isinstance(f, ReviewFinding) else f for f in self.findings],
            "reviewed_at": self.reviewed_at,
        }

    def to_markdown(self) -> str:
        """Generate review-summary.md content."""
        lines = [
            f"# Review Summary",
            f"",
            f"**Session:** {self.session_id}",
            f"**Task:** {self.task}",
            f"**Reviewed:** {self.reviewed_at}",
            f"**Total Findings:** {self.total_findings}",
            f"",
            f"## Findings by Severity",
            f"",
            f"| Severity | Count |",
            f"|----------|-------|",
        ]
        for sev in ["critical", "high", "medium", "low", "info"]:
            count = self.findings_by_severity.get(sev, 0)
            if count > 0:
                icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "info": "🔵"}.get(sev, "")
                lines.append(f"| {icon} {sev} | {count} |")

        lines.extend([
            f"",
            f"## Findings by Category",
            f"",
            f"| Category | Count |",
            f"|----------|-------|",
        ])
        for cat, count in sorted(self.findings_by_category.items(), key=lambda x: -x[1]):
            lines.append(f"| {cat} | {count} |")

        if self.findings:
            lines.extend([
                f"",
                f"## Details",
                f"",
            ])
            for i, finding in enumerate(self.findings, 1):
                f = finding if isinstance(finding, dict) else finding.to_dict()
                sev = f.get("severity", "info")
                icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "info": "🔵"}.get(sev, "")
                lines.append(f"### {i}. {icon} [{sev.upper()}] {f.get('category', 'general')}")
                if f.get("file_path"):
                    loc = f["file_path"]
                    if f.get("line_number"):
                        loc += f":{f['line_number']}"
                    lines.append(f"**Location:** `{loc}`")
                lines.append(f"")
                lines.append(f.get("description", ""))
                if f.get("suggestion"):
                    lines.append(f"")
                    lines.append(f"**Suggestion:** {f['suggestion']}")
                lines.append(f"")

        return "\n".join(lines)


@dataclass
class PlanCompletionSummary:
    """Summary generated when Ralph session completes."""
    session_id: str
    plan_id: str
    task: str
    total_agents: int
    completed_tasks: int
    failed_tasks: int
    total_cost: float
    duration_seconds: float
    phases_completed: list
    performance: dict
    plan_verification: dict
    verify_fix_summary: dict
    completed_at: str

    def to_markdown(self) -> str:
        """Generate .claude/plan-completion-summary.md content."""
        lines = [
            f"# Plan Completion Summary",
            f"",
            f"## 📊 Overview",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Session | `{self.session_id}` |",
            f"| Plan | `{self.plan_id}` |",
            f"| Task | {self.task} |",
            f"| Total Agents | {self.total_agents} |",
            f"| Completed | {self.completed_tasks} ✅ |",
            f"| Failed | {self.failed_tasks} ❌ |",
            f"| Total Cost | ${self.total_cost:.2f} |",
            f"| Duration | {self.duration_seconds/60:.1f} min |",
            f"",
            f"## 🔍 Plan Verification",
            f"",
        ]
        
        # Format plan verification section
        if self.plan_verification:
            status = self.plan_verification.get("status", "unknown")
            verified_tasks = self.plan_verification.get("verified_tasks", 0)
            missing_tasks = self.plan_verification.get("missing_tasks", 0)
            
            lines.append(f"**Status:** {'✅ PASS' if status == 'pass' else '❌ FAIL'}")
            lines.append(f"**Verified Tasks:** {verified_tasks}")
            lines.append(f"**Missing Tasks:** {missing_tasks}")
            lines.append(f"")
            
            if missing_tasks > 0 and "missing" in self.plan_verification:
                lines.append(f"### Missing Tasks")
                lines.append(f"")
                for task in self.plan_verification.get("missing", []):
                    lines.append(f"- ❌ {task}")
                lines.append(f"")
        else:
            lines.append(f"No plan verification data available.")
            lines.append(f"")
        
        lines.extend([
            f"## 🛠️ Verify+Fix Summary",
            f"",
        ])
        
        # Format verify+fix summary section
        if self.verify_fix_summary:
            total_checks = self.verify_fix_summary.get("total_checks", 0)
            issues_found = self.verify_fix_summary.get("issues_found", 0)
            issues_fixed = self.verify_fix_summary.get("issues_fixed", 0)
            issues_escalated = self.verify_fix_summary.get("issues_escalated", 0)
            
            lines.append(f"| Metric | Count |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Total Checks | {total_checks} |")
            lines.append(f"| Issues Found | {issues_found} |")
            lines.append(f"| Issues Fixed | {issues_fixed} ✅ |")
            lines.append(f"| Issues Escalated | {issues_escalated} ⚠️ |")
            lines.append(f"")
        else:
            lines.append(f"No verify+fix data available.")
            lines.append(f"")
        
        lines.extend([
            f"## ⚡ Performance by Agent",
            f"",
        ])
        
        # Format performance table
        if self.performance and "agents" in self.performance:
            lines.append(f"| Agent | Status | Cost | Turns | Duration |")
            lines.append(f"|-------|--------|------|-------|----------|")
            
            for agent in self.performance["agents"]:
                agent_name = agent.get("agent_name", f"Agent {agent.get('agent_id', '?')}")
                status = agent.get("status", "unknown")
                cost = agent.get("cost_usd", 0.0)
                turns = agent.get("num_turns", 0)
                duration = agent.get("duration_seconds", 0.0)
                
                status_icon = "✅" if status == "completed" else "❌"
                duration_str = f"{duration/60:.1f}m" if duration > 0 else "-"
                
                lines.append(
                    f"| {agent_name} | {status_icon} {status} | ${cost:.2f} | {turns} | {duration_str} |"
                )
            lines.append(f"")
            
            # Add summary stats
            total_cost = self.performance.get("total_cost_usd", 0.0)
            total_turns = self.performance.get("total_turns", 0)
            avg_cost = self.performance.get("avg_cost_per_agent", 0.0)
            
            lines.append(f"**Summary:** {total_turns} total turns, ${total_cost:.2f} total cost, ${avg_cost:.2f} avg per agent")
            lines.append(f"")
        else:
            lines.append(f"No performance data available.")
            lines.append(f"")
        
        lines.extend([
            f"## 📋 Phases Completed",
            f"",
        ])
        
        # Format phases list
        if self.phases_completed:
            for phase in self.phases_completed:
                lines.append(f"- ✅ {phase}")
        else:
            lines.append(f"No phases recorded.")
        
        lines.extend([
            f"",
            f"---",
            f"*Generated: {self.completed_at}*",
        ])
        
        return "\n".join(lines)


# =============================================================================
# Activity Scheduling + Performance Tracking
# =============================================================================

class ActivityScheduler:
    """
    Adaptive polling interval scheduler.

    Starts with fast polling (2s) when agents are active, decays to slower
    intervals (up to 30s) when idle. Resets on new activity.
    """

    MIN_INTERVAL: float = 2.0   # Fastest poll rate (seconds)
    MAX_INTERVAL: float = 30.0  # Slowest poll rate (seconds)
    DECAY_FACTOR: float = 1.5   # Multiplier per idle cycle

    def __init__(self):
        self._current_interval: float = self.MIN_INTERVAL
        self._last_activity: datetime = datetime.now()
        self._idle_cycles: int = 0

    @property
    def interval(self) -> float:
        """Current polling interval in seconds."""
        return self._current_interval

    def record_activity(self) -> None:
        """Reset interval on new activity (agent start/stop, state change)."""
        self._current_interval = self.MIN_INTERVAL
        self._last_activity = datetime.now()
        self._idle_cycles = 0

    def tick(self) -> float:
        """Advance one polling cycle, return the next sleep interval."""
        self._idle_cycles += 1
        self._current_interval = min(
            self._current_interval * self.DECAY_FACTOR,
            self.MAX_INTERVAL
        )
        return self._current_interval

    def idle_seconds(self) -> float:
        """Seconds since last activity."""
        return (datetime.now() - self._last_activity).total_seconds()


@dataclass
class AgentPerformanceRecord:
    """Per-agent performance metrics."""
    agent_id: int
    agent_name: str = ""
    cost_usd: float = 0.0
    num_turns: int = 0
    duration_seconds: float = 0.0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "cost_usd": round(self.cost_usd, 4),
            "num_turns": self.num_turns,
            "duration_seconds": round(self.duration_seconds, 1),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
        }


class PerformanceTracker:
    """
    Track per-agent cost, duration, and turn metrics.

    Aggregates performance data for progress reporting and budget enforcement.
    """

    def __init__(self):
        self._records: dict[int, AgentPerformanceRecord] = {}

        # Struggle detection indicators (per-agent tracking)
        self.struggle_indicators: dict[int, dict] = {}

    def start_agent(self, agent_id: int, agent_name: str = "") -> None:
        """Record agent start."""
        self._records[agent_id] = AgentPerformanceRecord(
            agent_id=agent_id,
            agent_name=agent_name,
            started_at=datetime.now().isoformat(),
            status="running",
        )

    def complete_agent(
        self, agent_id: int, cost_usd: float = 0, num_turns: int = 0, success: bool = True
    ) -> None:
        """Record agent completion with metrics."""
        rec = self._records.get(agent_id)
        if rec is None:
            rec = AgentPerformanceRecord(agent_id=agent_id)
            self._records[agent_id] = rec

        rec.cost_usd = cost_usd
        rec.num_turns = num_turns
        rec.completed_at = datetime.now().isoformat()
        rec.status = "completed" if success else "failed"

        if rec.started_at:
            try:
                start = datetime.fromisoformat(rec.started_at)
                rec.duration_seconds = (datetime.now() - start).total_seconds()
            except (ValueError, TypeError):
                pass

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self._records.values())

    @property
    def total_turns(self) -> int:
        return sum(r.num_turns for r in self._records.values())

    @property
    def avg_cost_per_agent(self) -> float:
        completed = [r for r in self._records.values() if r.status == "completed"]
        return self.total_cost / len(completed) if completed else 0.0

    @property
    def avg_duration(self) -> float:
        completed = [r for r in self._records.values() if r.duration_seconds > 0]
        return (sum(r.duration_seconds for r in completed) / len(completed)) if completed else 0.0

    def summary(self) -> dict:
        """Generate performance summary for progress file."""
        completed = [r for r in self._records.values() if r.status == "completed"]
        failed = [r for r in self._records.values() if r.status == "failed"]
        return {
            "total_agents": len(self._records),
            "completed": len(completed),
            "failed": len(failed),
            "total_cost_usd": round(self.total_cost, 4),
            "total_turns": self.total_turns,
            "avg_cost_per_agent": round(self.avg_cost_per_agent, 4),
            "avg_duration_seconds": round(self.avg_duration, 1),
            "agents": [r.to_dict() for r in self._records.values()],
        }

    def _init_struggle_tracker(self, agent_id: int) -> None:
        """Initialize struggle tracking for an agent."""
        if agent_id not in self.struggle_indicators:
            self.struggle_indicators[agent_id] = {
                "no_file_changes": 0,
                "repeated_errors": [],
                "short_iterations": 0,
                "same_error_count": 0
            }
    
    def record_iteration_result(self, agent_id: int, iteration_result: dict) -> None:
        """
        Record iteration metrics for struggle detection.
        
        Args:
            agent_id: Agent identifier
            iteration_result: Dict with keys:
                - files_changed: int (number of files modified)
                - error: Optional[str] (error message if any)
                - duration_seconds: float (iteration duration)
        """
        self._init_struggle_tracker(agent_id)
        indicators = self.struggle_indicators[agent_id]
        
        # Track file changes
        if not iteration_result.get("files_changed"):
            indicators["no_file_changes"] += 1
        else:
            indicators["no_file_changes"] = 0  # Reset on progress
        
        # Track errors
        if iteration_result.get("error"):
            error_msg = iteration_result["error"]
            indicators["repeated_errors"].append(error_msg)
            # Keep only last 5 errors
            if len(indicators["repeated_errors"]) > 5:
                indicators["repeated_errors"].pop(0)
        
        # Track iteration duration
        duration = iteration_result.get("duration_seconds", 0)
        if duration > 0 and duration < 30:
            indicators["short_iterations"] += 1
        else:
            indicators["short_iterations"] = 0  # Reset on normal iteration
    
    def detect_struggle(self, agent_id: int) -> Optional[str]:
        """
        Detect if agent is struggling based on iteration patterns.
        
        Returns:
            Optional[str]: Struggle type if detected, None if healthy
                - "NO_PROGRESS": No file changes for 3+ iterations
                - "REPEATED_ERROR": Same error occurring repeatedly
                - "RAPID_CYCLING": 5+ iterations under 30 seconds each
        """
        if agent_id not in self.struggle_indicators:
            return None
        
        indicators = self.struggle_indicators[agent_id]
        
        # Check for no progress
        if indicators["no_file_changes"] >= 3:
            return "NO_PROGRESS"
        
        # Check for repeated errors (same error in last 2 iterations)
        recent_errors = indicators["repeated_errors"][-2:]
        if len(recent_errors) == 2 and recent_errors[0] == recent_errors[1]:
            return "REPEATED_ERROR"
        
        # Check for rapid cycling
        if indicators["short_iterations"] >= 5:
            return "RAPID_CYCLING"
        
        return None
    
    def get_struggle_summary(self, agent_id: int) -> dict:
        """Get current struggle indicators for an agent."""
        if agent_id not in self.struggle_indicators:
            return {}
        return self.struggle_indicators[agent_id].copy()


# =============================================================================
# Review Agent Discovery
# =============================================================================
# NOTE: Agent config functions moved to ralph_lib.py for reusability
# Import them via: from ralph_lib import discover_agent_configs, load_agent_config, etc.
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


# =============================================================================
# Complexity Detection & Auto-Configuration
# =============================================================================

@dataclass
class ComplexityConfig:
    """Auto-configured settings based on task complexity."""
    agents: int
    iterations: int
    model: str
    complexity_score: float
    complexity_label: str


def calculate_complexity(task_description: str) -> float:
    """
    Calculate complexity score for a task description.
    
    Scoring factors:
    - Base keywords: "refactor", "architecture", "system", "migrate" (+0.5 each)
    - Scope indicators: "all", "entire", "full", "complete" (+0.3 each)
    - File count mentions: "multiple files", "across" (+0.4 each)
    - Simple indicators: "typo", "fix", "add button", "update text" (-0.5 each)
    - Word count: long descriptions tend to be more complex (+0.1 per 20 words)
    
    Returns:
        float: Complexity score (0-5 range typical)
    """
    if not task_description:
        return 1.0
    
    score = 1.0  # Base score
    lower_task = task_description.lower()
    
    # High complexity keywords
    high_keywords = ["refactor", "architecture", "system", "migrate", "redesign", 
                     "rewrite", "overhaul", "integrate", "framework"]
    score += sum(0.5 for kw in high_keywords if kw in lower_task)
    
    # Scope indicators
    scope_keywords = ["all", "entire", "full", "complete", "comprehensive", "throughout"]
    score += sum(0.3 for kw in scope_keywords if kw in lower_task)
    
    # Multi-file indicators
    multi_file = ["multiple files", "across", "codebase", "project-wide", "global"]
    score += sum(0.4 for kw in multi_file if kw in lower_task)
    
    # Simple task indicators (reduce score)
    simple_keywords = ["typo", "fix typo", "add button", "update text", "change color",
                      "rename", "small fix", "quick"]
    score -= sum(0.5 for kw in simple_keywords if kw in lower_task)
    
    # Word count factor (longer = more complex)
    word_count = len(task_description.split())
    score += (word_count // 20) * 0.1
    
    return max(0.5, min(5.0, score))  # Clamp between 0.5 and 5.0


def auto_configure(task_description: str = None, explicit_model: str = None) -> ComplexityConfig:
    """
    Auto-configure agent count and iterations based on task complexity.
    
    Model is ALWAYS Opus unless user explicitly specifies "sonnet" or "sonnet_all".
    
    Args:
        task_description: Task to analyze for complexity
        explicit_model: User-specified model override (sonnet/sonnet_all/opus)
    
    Returns:
        ComplexityConfig with recommended settings
    """
    if not task_description:
        # No task specified, use default
        return ComplexityConfig(
            agents=3,
            iterations=3,
            model=explicit_model or "opus",
            complexity_score=1.0,
            complexity_label="unknown"
        )
    
    score = calculate_complexity(task_description)
    
    # Model is ALWAYS Opus unless explicit override
    model = explicit_model if explicit_model else "opus"
    
    # Determine configuration based on score
    if score < 1.5:  # Simple task
        return ComplexityConfig(
            agents=3,
            iterations=1,
            model=model,
            complexity_score=score,
            complexity_label="simple"
        )
    elif score < 2.5:  # Standard task
        return ComplexityConfig(
            agents=5,
            iterations=2,
            model=model,
            complexity_score=score,
            complexity_label="standard"
        )
    else:  # Complex task
        return ComplexityConfig(
            agents=10,
            iterations=3,
            model=model,
            complexity_score=score,
            complexity_label="complex"
        )


# =============================================================================
# Ralph Protocol Implementation
# =============================================================================

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
        
        # Phase tracking for progress.json
        self._current_phase = "implementation"
        self._impl_total = 0
        self._impl_completed = 0
        self._impl_failed = 0
        self._review_total = 0
        self._review_completed = 0
        self._review_failed = 0
        self._model_mode = ModelMode.OPUS.value  # Default, updated in run_loop

        # Migrate legacy files on initialization
        self._migrate_legacy_files()
        
        # Initialize struggle detection
        self._struggle_detector = StruggleDetector(self.base_dir)

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
        Write Ralph state to JSON file with config backup rotation.

        Args:
            state: RalphState object to persist.

        Returns:
            True if successful, False otherwise.
        """
        try:
            # Ensure .claude directory exists
            self.state_path.parent.mkdir(parents=True, exist_ok=True)

            # Backup before overwrite (keep last 3)
            self._backup_config()

            with open(self.state_path, 'w') as f:
                json.dump(state.to_dict(), f, indent=2)
            self.log_activity(f"State written: {state.session_id}")
            return True
        except IOError as e:
            self.log_activity(f"Error writing state: {e}", level="ERROR")
            return False

    def _backup_config(self, max_backups: int = 3) -> None:
        """
        Rotate state backups, keeping the last N copies.

        Args:
            max_backups: Maximum number of backup files to retain.
        """
        if not self.state_path.exists():
            return

        backup_dir = self.state_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"state_{timestamp}.json"

        try:
            shutil.copy2(str(self.state_path), str(backup_path))
        except OSError:
            return

        # Prune old backups
        backups = sorted(backup_dir.glob("state_*.json"))
        for old_backup in backups[:-max_backups]:
            try:
                old_backup.unlink()
            except OSError:
                pass

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
        
        Visual Escalation Signals:
        - ESCALATION: 🚨 (red) - Agent needs human intervention
        - HINT_INJECTED: 💡 (yellow) - Context injected to unblock agent
        - AGENT_PAUSED: ⏸️ (yellow) - Agent paused pending decision
        - BUDGET_EXCEEDED: 💰 (red) - Budget limit reached
        """
        elapsed = self._elapsed_str()
        progress = self._progress_str()
        detail_str = f"  {detail}" if detail else ""

        # Color-code by event type with visual escalation signals
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
        elif event == "BUDGET":
            icon = f"{self._C_RED}💰{self._C_RESET}"
            event_fmt = f"{self._C_RED}BUDGET_EXCEEDED{self._C_RESET}"
        elif event == "ESCALATION":
            icon = f"{self._C_RED}🚨{self._C_RESET}"
            event_fmt = f"{self._C_RED}ESCALATION{self._C_RESET}"
        elif event == "HINT_INJECTED":
            icon = f"{self._C_YELLOW}💡{self._C_RESET}"
            event_fmt = f"{self._C_YELLOW}HINT_INJECTED{self._C_RESET}"
        elif event == "AGENT_PAUSED":
            icon = f"{self._C_YELLOW}⏸️{self._C_RESET}"
            event_fmt = f"{self._C_YELLOW}AGENT_PAUSED{self._C_RESET}"
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


    def signal_escalation(self, agent_id: int, reason: str) -> None:
        """Emit ESCALATION visual signal when agent needs human intervention."""
        self._print_progress("ESCALATION", agent_id, reason)
        self.log_activity(f"Agent {agent_id} escalation: {reason}", level="WARN")
    
    def signal_hint_injected(self, agent_id: int, hint_type: str) -> None:
        """Emit HINT_INJECTED visual signal when context is injected to help agent."""
        self._print_progress("HINT_INJECTED", agent_id, hint_type)
        self.log_activity(f"Agent {agent_id} hint injected: {hint_type}")
    
    def signal_agent_paused(self, agent_id: int, reason: str) -> None:
        """Emit AGENT_PAUSED visual signal when agent is waiting for decision."""
        self._print_progress("AGENT_PAUSED", agent_id, reason)
        self.log_activity(f"Agent {agent_id} paused: {reason}", level="INFO")

    def _get_struggling_count(self) -> int:
        """Count agents currently showing struggle indicators."""
        if not hasattr(self, '_perf_tracker') or not self._perf_tracker:
            return 0
        count = 0
        for agent_id in self._perf_tracker.struggle_indicators:
            struggles = self._perf_tracker.detect_struggle(agent_id)
            if struggles:
                count += 1
        return count
    
    def _get_model_mix(self) -> dict:
        """Get count of Opus vs Sonnet agents based on current mode."""
        # Model mix depends on phase and model_mode setting
        # Implementation agents use model_mode (default OPUS)
        # Review agents always use SONNET
        model_mix = {"opus": 0, "sonnet": 0}
        
        if self._current_phase == "implementation":
            if self._model_mode == ModelMode.SONNET_ALL.value:
                model_mix["sonnet"] = self._total_agents_in_loop
            else:
                # OPUS or default SONNET mode (impl=opus, review=sonnet)
                model_mix["opus"] = self._total_agents_in_loop
        elif self._current_phase == "review":
            # Review agents are always Sonnet
            model_mix["sonnet"] = self._review_total
            # Add implementation agents to opus count
            if self._model_mode != ModelMode.SONNET_ALL.value:
                model_mix["opus"] = self._impl_total
            else:
                model_mix["sonnet"] += self._impl_total
        elif self._current_phase == "complete":
            # Both phases complete - show final counts
            if self._model_mode == ModelMode.SONNET_ALL.value:
                model_mix["sonnet"] = self._impl_total + self._review_total
            else:
                model_mix["opus"] = self._impl_total
                model_mix["sonnet"] = self._review_total
        
        return model_mix

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
                # NEW: Phase-level tracking
                "phase": self._current_phase,
                "impl": {
                    "total": self._impl_total,
                    # During impl phase, use current counters; after transition use snapshot
                    "completed": self._completed_count if self._current_phase == "implementation" else self._impl_completed,
                    "failed": self._failed_count if self._current_phase == "implementation" else self._impl_failed,
                },
                "review": {
                    "total": self._review_total,
                    # During review phase, use current counters; after completion use snapshot
                    "completed": self._completed_count if self._current_phase == "review" else self._review_completed,
                    "failed": self._failed_count if self._current_phase == "review" else self._review_failed,
                },
                "model_mix": self._get_model_mix(),
                "struggling": self._get_struggling_count(),
            }
            # Include performance tracker summary if available
            if hasattr(self, '_perf_tracker') and self._perf_tracker:
                progress_data["performance"] = self._perf_tracker.summary()
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
        """Write progress file with total: 0 to signal completion (auto-hide in statusline)."""
        try:
            # Write minimal progress.json with total: 0 to signal statusline to hide Ralph section
            total_completed = self._impl_completed + self._review_completed
            total_failed = self._impl_failed + self._review_failed
            cleanup_data = {
                "total": 0,
                "completed": total_completed,
                "failed": total_failed,
                "done": total_completed + total_failed,
                "cost_usd": round(self._total_cost, 4),
                "phase": "complete",
                "updated_at": datetime.now().isoformat(),
            }
            with open(self.progress_path, 'w') as f:
                json.dump(cleanup_data, f)
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

    def _generate_completion_summary(self) -> Optional[PlanCompletionSummary]:
        """
        Generate completion summary when Ralph session completes.
        
        Aggregates data from state, performance tracker, and plan verification.
        
        Returns:
            PlanCompletionSummary object or None if state unavailable.
        """
        state = self.read_state()
        if not state:
            return None
        
        # Load performance data
        performance = {}
        try:
            progress_file = self.base_dir / ".claude" / "ralph" / "progress.json"
            if progress_file.exists():
                with open(progress_file, 'r') as f:
                    progress_data = json.load(f)
                    performance = progress_data.get("performance", {})
        except (json.JSONDecodeError, OSError):
            pass
        
        # Load plan verification data (if available)
        plan_verification = {}
        try:
            verification_file = self.base_dir / ".claude" / "plan-verification.json"
            if verification_file.exists():
                with open(verification_file, 'r') as f:
                    plan_verification = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
        
        # Load verify+fix summary (if available)
        verify_fix_summary = {}
        try:
            verify_fix_file = self.base_dir / ".claude" / "verify-fix-summary.json"
            if verify_fix_file.exists():
                with open(verify_fix_file, 'r') as f:
                    verify_fix_summary = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
        
        # Count completed/failed tasks from task queue
        completed_tasks = 0
        failed_tasks = 0
        try:
            plan_file = state.checkpoint_path or ""
            if plan_file:
                plan_name = Path(plan_file).stem
                queue_file = self.base_dir / ".claude" / f"task-queue-{plan_name}.json"
            else:
                claude_dir = self.base_dir / ".claude"
                queue_files = list(claude_dir.glob("task-queue-*.json"))
                queue_file = queue_files[0] if queue_files else None
            
            if queue_file and queue_file.exists():
                with open(queue_file, 'r') as f:
                    queue_data = json.load(f)
                    tasks = queue_data.get("tasks", [])
                    for task in tasks:
                        status = task.get("status", "pending")
                        if status == "completed":
                            completed_tasks += 1
                        elif status == "failed":
                            failed_tasks += 1
        except (json.JSONDecodeError, OSError, AttributeError):
            pass
        
        # Calculate duration
        duration_seconds = 0.0
        if state.started_at:
            try:
                start = datetime.fromisoformat(state.started_at)
                end = datetime.now(timezone.utc)
                if state.completed_at:
                    end = datetime.fromisoformat(state.completed_at)
                duration_seconds = (end - start).total_seconds()
            except (ValueError, TypeError):
                pass
        
        # Get phases completed
        phases_completed = []
        if hasattr(state, 'phase_history'):
            phases_completed = state.phase_history or []
        elif state.phase:
            phases_completed = [state.phase]
        
        # Extract plan_id from checkpoint_path or state
        plan_id = ""
        if state.checkpoint_path:
            plan_id = Path(state.checkpoint_path).stem
        elif hasattr(state, 'plan_id'):
            plan_id = state.plan_id or ""
        
        return PlanCompletionSummary(
            session_id=state.session_id,
            plan_id=plan_id,
            task=state.task or "No task description",
            total_agents=performance.get("total_agents", 0),
            completed_tasks=completed_tasks,
            failed_tasks=failed_tasks,
            total_cost=performance.get("total_cost_usd", 0.0),
            duration_seconds=duration_seconds,
            phases_completed=phases_completed,
            performance=performance,
            plan_verification=plan_verification,
            verify_fix_summary=verify_fix_summary,
            completed_at=datetime.now(timezone.utc).isoformat()
        )

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

        if phase in ("complete", LifecyclePhase.COMPLETE.value) or completed_at:
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
            
            # Generate completion summary before cleanup
            summary = self._generate_completion_summary()
            inject_msg = ""
            
            if summary:
                try:
                    # Write summary to .claude/plan-completion-summary.md
                    summary_path = self.base_dir / ".claude" / "plan-completion-summary.md"
                    summary_path.parent.mkdir(parents=True, exist_ok=True)
                    summary_path.write_text(summary.to_markdown(), encoding="utf-8")
                    
                    # Prepare injection message with summary preview
                    inject_msg = f"""✅ RALPH SESSION COMPLETE

Plan completion summary written to: {summary_path}

## Summary Preview

**Session:** {summary.session_id}
**Total Agents:** {summary.total_agents}
**Completed Tasks:** {summary.completed_tasks} ✅
**Failed Tasks:** {summary.failed_tasks} ❌
**Total Cost:** ${summary.total_cost:.2f}
**Duration:** {summary.duration_seconds/60:.1f} minutes

Full details available in {summary_path}
"""
                except Exception as e:
                    self.log_activity(f"Failed to generate completion summary: {e}", level="ERROR")
                    inject_msg = "✅ RALPH SESSION COMPLETE\n\n(Failed to generate completion summary)"
            
            cleanup_results = self.cleanup_ralph_session(keep_activity_log=False)
            
            response = {
                "decision": "approve",
                "reason": "Ralph protocol complete",
                "cleanup": cleanup_results
            }
            
            if inject_msg:
                response["inject_message"] = inject_msg
            
            return response

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

    # =========================================================================
    # SubagentStart / SubagentStop Hook Handlers
    # =========================================================================

    def handle_hook_subagent_start(self, stdin_content: Optional[str] = None) -> dict:
        """
        Handle SubagentStart hook — track agent spawn in state.

        Records the subagent spawn event with timestamp and agent metadata.
        """
        if not self.state_exists():
            return {}

        try:
            data = json.loads(stdin_content) if stdin_content else json.loads(sys.stdin.read())
        except (json.JSONDecodeError, TypeError):
            return {}

        state = self.read_state()
        if not state:
            return {}

        agent_id = data.get("agent_id", data.get("subagent_id", "unknown"))
        self.log_activity(f"SubagentStart: {agent_id}")

        # Update heartbeat
        state.last_heartbeat = datetime.now().isoformat()
        self.write_state(state)

        return {"tracked": True, "agent_id": agent_id}

    def handle_hook_subagent_stop(self, stdin_content: Optional[str] = None) -> dict:
        """
        Handle SubagentStop hook — track agent completion, enforce iteration limits, manage retries.

        Records completion, updates metrics, detects failures, and queues failed agents
        for retry (max 3 retries per agent).
        """
        if not self.state_exists():
            return {}

        try:
            data = json.loads(stdin_content) if stdin_content else json.loads(sys.stdin.read())
        except (json.JSONDecodeError, TypeError):
            return {}

        state = self.read_state()
        if not state:
            return {}

        agent_id = data.get("agent_id", data.get("subagent_id", "unknown"))
        cost_usd = data.get("total_cost_usd", 0)
        num_turns = data.get("num_turns", 0)
        exit_status = data.get("exit_status", 0)
        duration_ms = data.get("duration_ms", 0)

        # Detect failure: non-zero exit status
        failed = exit_status != 0

        status_label = "FAILED" if failed else "SUCCESS"
        self.log_activity(
            f"SubagentStop: {agent_id} ({status_label}) ${cost_usd:.4f}, {num_turns} turns, {duration_ms}ms"
        )

        # Update heartbeat and track cost
        state.last_heartbeat = datetime.now().isoformat()
        self.write_state(state)

        # Record daily cost
        if cost_usd > 0:
            try:
                record_daily_cost(cost_usd)
            except Exception:
                pass

        # Update progress.json with aggregated cost
        self._update_progress_with_agent_cost(cost_usd)

        # Handle retry logic for failed agents
        retry_queued = False
        if failed:
            retry_queued = self._queue_failed_agent_for_retry(agent_id, {
                "cost_usd": cost_usd,
                "num_turns": num_turns,
                "exit_status": exit_status,
                "duration_ms": duration_ms,
            })

        return {
            "tracked": True,
            "agent_id": agent_id,
            "cost_usd": cost_usd,
            "num_turns": num_turns,
            "failed": failed,
            "retry_queued": retry_queued,
        }

    def _update_progress_with_agent_cost(self, cost_usd: float) -> None:
        """Update progress.json with aggregated agent cost."""
        try:
            progress_path = self.base_dir / self.PROGRESS_FILE
            if progress_path.exists():
                with open(progress_path, 'r') as f:
                    progress = json.load(f)
            else:
                progress = {
                    "total": 0,
                    "completed": 0,
                    "failed": 0,
                    "done": 0,
                    "cost_usd": 0,
                }

            progress["cost_usd"] = round(progress.get("cost_usd", 0) + cost_usd, 4)
            progress["updated_at"] = datetime.now().isoformat()

            progress_path.parent.mkdir(parents=True, exist_ok=True)
            with open(progress_path, 'w') as f:
                json.dump(progress, f, indent=2)
        except (IOError, json.JSONDecodeError):
            pass

    def _queue_failed_agent_for_retry(self, agent_id: str, failure_info: dict) -> bool:
        """
        Queue a failed agent for retry if under retry limit.

        Args:
            agent_id: Agent identifier
            failure_info: Failure metadata (cost, turns, exit status, duration)

        Returns:
            True if queued for retry, False if retry limit exceeded
        """
        MAX_RETRIES = 3
        retry_queue_path = self.base_dir / ".claude" / "ralph" / "retry-queue.json"

        try:
            # Load existing retry queue
            if retry_queue_path.exists():
                with open(retry_queue_path, 'r') as f:
                    retry_queue = json.load(f)
            else:
                retry_queue = {}

            # Check retry count for this agent
            agent_entry = retry_queue.get(agent_id, {
                "retry_count": 0,
                "failures": [],
            })

            current_retry_count = agent_entry.get("retry_count", 0)

            if current_retry_count >= MAX_RETRIES:
                self.log_activity(
                    f"Agent {agent_id} exceeded max retries ({MAX_RETRIES}), not queueing",
                    level="WARN"
                )
                return False

            # Queue for retry
            agent_entry["retry_count"] = current_retry_count + 1
            agent_entry["failures"].append({
                **failure_info,
                "timestamp": datetime.now().isoformat(),
            })
            agent_entry["status"] = "pending_retry"
            agent_entry["last_failure"] = datetime.now().isoformat()

            retry_queue[agent_id] = agent_entry

            # Write updated retry queue
            retry_queue_path.parent.mkdir(parents=True, exist_ok=True)
            with open(retry_queue_path, 'w') as f:
                json.dump(retry_queue, f, indent=2)

            self.log_activity(
                f"Agent {agent_id} queued for retry (attempt {current_retry_count + 1}/{MAX_RETRIES})"
            )
            return True

        except (IOError, json.JSONDecodeError) as e:
            self.log_activity(f"Failed to queue agent for retry: {e}", level="ERROR")
            return False

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

### Memory Persistence:
- Use `mcp__serena__write_memory` to save architectural decisions, symbol maps
- Use `mcp__serena__read_memory` to recall project context across sessions
- Use `mcp__serena__list_memories` to see available memory files
- Run `/serena-workflow` for the full tool matrix and editing workflows

### Reflection Checkpoints:
- `mcp__serena__think_about_collected_information` — after gathering context
- `mcp__serena__think_about_task_adherence` — before making changes
- `mcp__serena__think_about_whether_you_are_done` — before reporting completion
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

    async def _spawn_review_agent(
        self,
        agent_state: AgentState,
        task: Optional[str] = None,
        semaphore: Optional[asyncio.Semaphore] = None
    ) -> bool:
        """
        Spawn a review agent that analyzes code changes without making edits.

        Review agents:
        - Analyze code quality, security, performance
        - Leave TODO comments for issues found
        - Report findings to .claude/review-agents.md
        - Do NOT auto-fix issues

        Args:
            agent_state: State object for this review agent.
            task: Original task description for context.
            semaphore: Optional semaphore for concurrency limiting.

        Returns:
            True if review completed successfully, False otherwise.
        """
        if semaphore:
            await semaphore.acquire()

        try:
            agent_state.status = AgentStatus.RUNNING.value
            agent_state.started_at = datetime.now().isoformat()

            # Track performance
            self._perf_tracker.start_agent(agent_state.agent_id, f"review-{agent_state.agent_id}")

            # Print start message
            self._print_progress("STARTED", agent_state.agent_id, "Review")

            # Build review-specific prompt
            prompt = self._build_review_prompt(agent_state, task)

            # Spawn subprocess (same mechanism as implementation agents)
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["claude", "--print", prompt],
                        cwd=str(self.base_dir),
                        capture_output=True,
                        text=True,
                        timeout=600,  # 10 min timeout for review
                        env={**os.environ, "CLAUDE_CODE_ENTRY_POINT": "cli"},
                    )
                )

                success = result.returncode == 0
                cost = self._extract_cost_from_output(result.stdout + result.stderr)
                turns = self._extract_turns_from_output(result.stdout + result.stderr)

                self._perf_tracker.complete_agent(
                    agent_state.agent_id,
                    cost_usd=cost,
                    num_turns=turns,
                    success=success
                )

                # Update counters
                if success:
                    self._completed_count += 1
                    self._total_cost += cost
                    self._print_progress(
                        "DONE", agent_state.agent_id,
                        f"Review  ${cost:.2f}, {turns} turns"
                    )
                else:
                    self._failed_count += 1
                    self._print_progress("FAILED", agent_state.agent_id, "Review")

                return success

            except subprocess.TimeoutExpired:
                self._failed_count += 1
                self._print_progress("TIMEOUT", agent_state.agent_id, "Review")
                return False
            except Exception as e:
                self._failed_count += 1
                self.log_activity(f"Review agent {agent_state.agent_id} error: {e}", level="ERROR")
                return False

        finally:
            if semaphore:
                semaphore.release()

    async def _spawn_verify_fix_agent(
        self,
        agent_state: AgentState,
        task: Optional[str] = None,
        semaphore: Optional[asyncio.Semaphore] = None
    ) -> bool:
        """
        Spawn a verify-fix agent that checks build integrity and auto-fixes issues.

        Verify-fix agents:
        - Run build checks (pnpm build, type checks, linting)
        - Use Serena to verify symbol integrity
        - Auto-fix simple issues (imports, types, formatting)
        - Escalate complex issues via AskUserQuestion
        - Do NOT leave TODO comments

        Args:
            agent_state: State object for this verify-fix agent.
            task: Original task description for context.
            semaphore: Optional semaphore for concurrency limiting.

        Returns:
            True if verification completed successfully, False otherwise.
        """
        if semaphore:
            await semaphore.acquire()

        try:
            agent_state.status = AgentStatus.RUNNING.value
            agent_state.started_at = datetime.now().isoformat()

            # Track performance
            self._perf_tracker.start_agent(agent_state.agent_id, f"verify-fix-{agent_state.agent_id}")

            # Print start message
            self._print_progress("STARTED", agent_state.agent_id, "Verify+Fix")

            # Build verify-fix-specific prompt
            prompt = self._build_verify_fix_prompt(agent_state, task)

            # Spawn subprocess with Opus model (VERIFY+FIX requires Opus)
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["claude", "--print", "--model", VERIFY_FIX_MODEL, prompt],
                        cwd=str(self.base_dir),
                        capture_output=True,
                        text=True,
                        timeout=600,  # 10 min timeout for verify-fix
                        env={**os.environ, "CLAUDE_CODE_ENTRY_POINT": "cli", "CLAUDE_CODE_EFFORT_LEVEL": VERIFY_FIX_EFFORT["full"]},
                    )
                )

                success = result.returncode == 0
                cost = self._extract_cost_from_output(result.stdout + result.stderr)
                turns = self._extract_turns_from_output(result.stdout + result.stderr)

                self._perf_tracker.complete_agent(
                    agent_state.agent_id,
                    cost_usd=cost,
                    num_turns=turns,
                    success=success
                )

                # Update counters
                if success:
                    self._completed_count += 1
                    self._total_cost += cost
                    self._print_progress(
                        "DONE", agent_state.agent_id,
                        f"Verify+Fix  ${cost:.2f}, {turns} turns"
                    )
                else:
                    self._failed_count += 1
                    self._print_progress("FAILED", agent_state.agent_id, "Verify+Fix")

                return success

            except subprocess.TimeoutExpired:
                self._failed_count += 1
                self._print_progress("TIMEOUT", agent_state.agent_id, "Verify+Fix")
                return False
            except Exception as e:
                self._failed_count += 1
                self.log_activity(f"Verify-fix agent {agent_state.agent_id} error: {e}", level="ERROR")
                return False

        finally:
            if semaphore:
                semaphore.release()

    def _get_agent_changed_files(self, initial_head: str) -> list[str]:
        """Get list of files changed since the given commit (agent's initial HEAD).

        Args:
            initial_head: The git commit SHA when the agent started.

        Returns:
            List of file paths that were modified since initial_head.
        """
        if not initial_head:
            return []

        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", initial_head, "HEAD"],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        except Exception as e:
            self.log_activity(f"Failed to get changed files: {e}", level="WARN")

        return []

    async def _spawn_scoped_verify_fix(
        self,
        parent_agent: AgentState,
        changed_files: list[str],
        task: Optional[str] = None
    ) -> bool:
        """Spawn a verify+fix agent scoped to specific files changed by parent agent.

        This runs AFTER an implementation agent completes, checking only the files
        that agent modified. Uses Opus model for thorough verification.

        Args:
            parent_agent: The implementation agent that just completed.
            changed_files: List of files to verify (from _get_agent_changed_files).
            task: Original task description for context.

        Returns:
            True if verification passed, False if issues found.
        """
        if not changed_files:
            self.log_activity(f"Agent {parent_agent.agent_id}: No changed files, skipping scoped verify")
            return True

        self.log_activity(f"Agent {parent_agent.agent_id}: Running scoped verify+fix on {len(changed_files)} files")
        self._print_progress("VERIFY", parent_agent.agent_id, f"checking {len(changed_files)} files")

        # Build scoped verify prompt
        files_list = "\n".join(f"- {f}" for f in changed_files[:50])  # Cap at 50 files
        prompt = f"""You are a SCOPED VERIFY+FIX agent for Agent {parent_agent.agent_id}.

## SCOPE (ONLY check these files):
{files_list}

## Checklist:
1. **Build check**: Does the project compile/build? (pnpm build, npm run build, etc.)
2. **Type check**: Any TypeScript/Python type errors in scoped files?
3. **Lint check**: Run linter on scoped files only (biome check, eslint, etc.)
4. **Import verification**: All imports in scoped files valid and resolved?
5. **Symbol integrity**: Use Serena find_referencing_symbols to verify no broken references

## On Issues Found:
- Auto-fix simple issues (formatting, imports, type annotations)
- Escalate complex issues via AskUserQuestion
- Do NOT leave TODO comments — fix or escalate immediately

## Output Format (REQUIRED):
When complete, output exactly:
SCOPED_VERIFY_COMPLETE: [PASS|FAIL]
ISSUES_FOUND: [count]
ISSUES_FIXED: [count]
ISSUES_ESCALATED: [count]

Then if all issues resolved:
{self.RALPH_COMPLETE_SIGNAL}
{self.EXIT_SIGNAL}

## Original Task Context:
{task or 'Implementation task'}

Begin scoped verification of {len(changed_files)} files now.
"""

        try:
            # Spawn with Opus model (user preference: thorough verification)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["claude", "--print", "--model", VERIFY_FIX_MODEL, prompt],
                    cwd=str(self.base_dir),
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 min timeout
                    env={**os.environ, "CLAUDE_CODE_ENTRY_POINT": "cli", "CLAUDE_CODE_EFFORT_LEVEL": VERIFY_FIX_EFFORT["scoped"]},
                )
            )

            output = result.stdout + result.stderr
            success = result.returncode == 0

            # Parse result
            passed = "SCOPED_VERIFY_COMPLETE: PASS" in output
            issues_found = 0
            issues_fixed = 0

            # Extract counts
            import re
            found_match = re.search(r"ISSUES_FOUND:\s*(\d+)", output)
            fixed_match = re.search(r"ISSUES_FIXED:\s*(\d+)", output)
            if found_match:
                issues_found = int(found_match.group(1))
            if fixed_match:
                issues_fixed = int(fixed_match.group(1))

            if passed:
                self._print_progress(
                    "VERIFIED", parent_agent.agent_id,
                    f"passed ({issues_fixed} fixes)"
                )
                return True
            else:
                self._print_progress(
                    "VERIFY_FAIL", parent_agent.agent_id,
                    f"{issues_found} issues"
                )
                return False

        except subprocess.TimeoutExpired:
            self._print_progress("VERIFY_TIMEOUT", parent_agent.agent_id)
            return False
        except Exception as e:
            self.log_activity(f"Scoped verify-fix error for agent {parent_agent.agent_id}: {e}", level="ERROR")
            return False


    async def _spawn_plan_verification_agent(self, task: Optional[str] = None) -> dict:
        """Verify 100% plan completion before allowing RALPH_COMPLETE.
        
        Reads the plan file, verifies each task/requirement is implemented using
        Serena symbol search, and returns verification status.
        
        Args:
            task: Original task description for context.
            
        Returns:
            dict with keys:
                - verified (bool): True if all tasks completed
                - missing_tasks (list): List of incomplete task descriptions
                - verified_count (int): Number of verified tasks
                - total_count (int): Total tasks in plan
        """
        self.log_activity("Starting plan verification phase")
        self._print_progress("PLAN_VERIFY", -1, "checking plan completion")
        
        # Find plan file
        plans_dir = self.base_dir / ".claude" / "plans"
        if not plans_dir.exists():
            self.log_activity("No plans directory found, skipping verification")
            return {"verified": True, "missing_tasks": [], "verified_count": 0, "total_count": 0}
        
        # Get most recent plan file
        plan_files = sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not plan_files:
            self.log_activity("No plan files found, skipping verification")
            return {"verified": True, "missing_tasks": [], "verified_count": 0, "total_count": 0}
        
        plan_file = plan_files[0]
        self.log_activity(f"Verifying plan: {plan_file.name}")
        
        # Build verification prompt
        prompt = f"""You are a PLAN VERIFICATION agent. Your job is to verify that ALL tasks in the plan have been implemented.

## Instructions:

1. Read the plan file: {plan_file}
2. For each task/requirement in the plan:
   - Use Serena find_symbol to verify implementation exists
   - Check for actual code, not TODOs or placeholders
   - Mark as ✅ DONE or ❌ MISSING
3. Output a structured verification report

## Verification Rules:

- A task is DONE if: code exists, tests pass, no TODOs remain for that feature
- A task is MISSING if: no implementation found, only TODOs, or incomplete
- Use Serena find_referencing_symbols to verify integration
- Check multiple files if a feature spans components

## Output Format (REQUIRED):

When complete, output exactly:

PLAN_VERIFICATION_COMPLETE: [PASS|FAIL]
VERIFIED_TASKS: [count]
MISSING_TASKS: [count]

Then for each MISSING task, output:
MISSING: [Brief task description]

Then if verification passes:
{self.RALPH_COMPLETE_SIGNAL}
{self.EXIT_SIGNAL}

## Original Task Context:
{task or 'Implementation task'}

Begin plan verification now. Be thorough - this is the final gate before review.
"""
        
        try:
            # Spawn with Opus model for thorough verification
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["claude", "--print", "--model", VERIFY_FIX_MODEL, prompt],
                    cwd=str(self.base_dir),
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 min timeout
                    env={**os.environ, "CLAUDE_CODE_ENTRY_POINT": "cli", "CLAUDE_CODE_EFFORT_LEVEL": VERIFY_FIX_EFFORT["plan"]},
                )
            )
            
            output = result.stdout + result.stderr
            success = result.returncode == 0
            
            # Parse result
            passed = "PLAN_VERIFICATION_COMPLETE: PASS" in output
            verified_count = 0
            missing_count = 0
            missing_tasks = []
            
            # Extract counts
            import re
            verified_match = re.search(r"VERIFIED_TASKS:\s*(\d+)", output)
            missing_match = re.search(r"MISSING_TASKS:\s*(\d+)", output)
            
            if verified_match:
                verified_count = int(verified_match.group(1))
            if missing_match:
                missing_count = int(missing_match.group(1))
            
            # Extract missing task descriptions
            missing_pattern = re.compile(r"MISSING:\s*(.+?)(?=\n(?:MISSING:|PLAN_VERIFICATION_COMPLETE:|$))", re.DOTALL)
            for match in missing_pattern.finditer(output):
                task_desc = match.group(1).strip()
                if task_desc:
                    missing_tasks.append(task_desc)
            
            total_count = verified_count + missing_count
            
            if passed:
                self._print_progress(
                    "PLAN_VERIFIED", -1,
                    f"all {verified_count} tasks complete"
                )
                self.log_activity(f"Plan verification PASSED: {verified_count}/{total_count} tasks complete")
            else:
                self._print_progress(
                    "PLAN_INCOMPLETE", -1,
                    f"{missing_count} missing"
                )
                self.log_activity(
                    f"Plan verification FAILED: {missing_count}/{total_count} tasks missing"
                )
                for i, task in enumerate(missing_tasks[:5], 1):  # Log first 5
                    self.log_activity(f"  Missing task {i}: {task[:80]}")
            
            return {
                "verified": passed,
                "missing_tasks": missing_tasks,
                "verified_count": verified_count,
                "total_count": total_count,
            }
            
        except subprocess.TimeoutExpired:
            self._print_progress("PLAN_VERIFY_TIMEOUT", -1)
            self.log_activity("Plan verification timed out", level="ERROR")
            return {
                "verified": False,
                "missing_tasks": ["Verification timeout - unable to complete"],
                "verified_count": 0,
                "total_count": 0,
            }
        except Exception as e:
            self.log_activity(f"Plan verification error: {e}", level="ERROR")
            return {
                "verified": False,
                "missing_tasks": [f"Verification error: {str(e)}"],
                "verified_count": 0,
                "total_count": 0,
            }

    def _build_review_prompt(self, agent: AgentState, task: Optional[str]) -> str:
        """Build prompt for a review agent."""
        # Get list of changed files
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=str(self.base_dir),
                capture_output=True,
                text=True,
                timeout=10,
            )
            changed_files = result.stdout.strip() if result.returncode == 0 else ""
        except Exception:
            changed_files = ""

        # Try to load quality check results from VERIFY+FIX phase
        quality_context = ""
        quality_log_path = self.base_dir / ".claude" / "verify-fix-quality.log"
        if quality_log_path.exists():
            try:
                quality_results = quality_log_path.read_text(encoding="utf-8")
                quality_context = f"""
QUALITY CHECK RESULTS (from VERIFY+FIX phase):
{quality_results[:2000]}  # Limit to 2000 chars to avoid bloat
"""
            except Exception:
                pass

        # Assign review specialty based on agent ID
        specialties = [
            "security",      # Agent 0: Security vulnerabilities
            "performance",   # Agent 1: Performance issues
            "types",         # Agent 2: Type safety and design
            "errors",        # Agent 3: Error handling
            "quality",       # Agent 4: Code quality and style
        ]
        specialty = specialties[agent.agent_id % len(specialties)]

        return f"""You are Review Agent {agent.agent_id} specializing in: {specialty.upper()}

TASK CONTEXT: {task or 'Review recent code changes'}

CHANGED FILES:
{changed_files or '(Use git diff --name-only HEAD to find changes)'}
{quality_context}
REVIEW PROTOCOL:
1. Focus on {specialty} issues in the changed files
2. For each issue found, leave a TODO comment in the code:
   - TODO-P1: Critical issues (security, crashes)
   - TODO-P2: Important issues (bugs, performance)
   - TODO-P3: Improvements (refactoring, docs)

3. Report findings to .claude/review-agents.md in this format:
   | Severity | Category | File | Issue | Suggestion |
   |----------|----------|------|-------|------------|
   | 🔴 P1 | {specialty} | path/file.ts:42 | Description | Fix suggestion |

4. Do NOT auto-fix issues - only identify and document them

5. When done, output:
   REVIEW_COMPLETE
   {self.EXIT_SIGNAL}

SPECIALTY FOCUS ({specialty}):
"""
        + self._get_specialty_instructions(specialty)

    def _get_specialty_instructions(self, specialty: str) -> str:
        """Get specialty-specific review instructions."""
        instructions = {
            "security": """
- Check for injection vulnerabilities (SQL, XSS, command injection)
- Verify authentication and authorization
- Look for hardcoded secrets or credentials
- Check for insecure data handling
- Verify input validation and sanitization
""",
            "performance": """
- Identify N+1 query patterns
- Check for memory leaks or excessive allocations
- Look for blocking operations in async code
- Verify efficient data structures are used
- Check for unnecessary re-renders in React
""",
            "types": """
- Check for proper TypeScript types (no `any`)
- Verify function signatures are complete
- Look for missing null checks
- Check interface/type consistency
- Verify proper use of generics
""",
            "errors": """
- Check for proper error handling
- Verify try/catch blocks are appropriate
- Look for swallowed exceptions
- Check for proper error messages
- Verify error recovery paths
""",
            "quality": """
- Check code follows project conventions
- Look for code duplication
- Verify proper naming conventions
- Check for dead code
- Verify documentation completeness
""",
        }
        return instructions.get(specialty, "Review for general code quality issues.")

    def _extract_cost_from_output(self, output: str) -> float:
        """Extract cost from Claude output."""
        import re
        match = re.search(r'\$(\d+\.?\d*)', output)
        return float(match.group(1)) if match else 0.0

    def _extract_turns_from_output(self, output: str) -> int:
        """Extract turn count from Claude output."""
        import re
        match = re.search(r'(\d+)\s*turns?', output, re.IGNORECASE)
        return int(match.group(1)) if match else 1

    async def _spawn_agent_impl(self, agent_state: AgentState, task: Optional[str] = None) -> bool:
        """Internal implementation of agent spawning via subprocess.

        Spawns a separate `claude --print` process for each agent.
        Each process has its own context window and MCP servers.
        """
        agent_state.status = AgentStatus.RUNNING.value
        agent_state.started_at = datetime.now().isoformat()
        
        # Start struggle tracking
        agent_id_str = f"agent-{agent_state.agent_id}"
        if hasattr(self, '_struggle_detector') and self._struggle_detector:
            self._struggle_detector.start_tracking(agent_id_str)

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
        agent_id_str = f"agent-{agent_state.agent_id}"
        
        # Write agent start receipt
        state = self.read_state()
        session_id = state.session_id if state else "unknown"
        write_receipt(
            agent_id_str,
            "agent_start",
            {
                "task": task or "general",
                "started_at": agent_state.started_at,
                "max_iterations": agent_state.max_iterations
            },
            session_id
        )
        
        self.log_activity(f"Agent {agent_state.agent_id} started")
        self._print_progress("STARTED", agent_state.agent_id)
        # Track performance start
        if hasattr(self, '_perf_tracker') and self._perf_tracker:
            self._perf_tracker.start_agent(agent_state.agent_id)
        if hasattr(self, '_scheduler') and self._scheduler:
            self._scheduler.record_activity()

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
            # Generate structured agent name based on phase and specialty
            current_phase = state.phase if state else "implementation"
            assigned_config = match_agent_to_task(task or "", None) if task else "general"
            structured_name = generate_agent_name(current_phase, assigned_config, agent_state.agent_id)

            env["CLAUDE_CODE_AGENT_ID"] = f"agent-{agent_state.agent_id}"
            env["CLAUDE_CODE_AGENT_NAME"] = structured_name
            env["RALPH_AGENT_TYPE"] = current_phase

            # Review agents get read-only sandbox (plan mode)
            if current_phase == LifecyclePhase.REVIEW.value:
                env["CLAUDE_CODE_PERMISSION_MODE"] = "plan"
                env["RALPH_AGENT_TYPE"] = "review"
            env["RALPH_PARENT_SESSION_ID"] = session_id

            # Record HEAD at agent start for push gate comparison
            # Review agents that make no commits won't be blocked on exit
            initial_head = None  # Store locally for per-task verify+fix
            try:
                head_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True,
                    cwd=str(self.base_dir), timeout=5
                )
                if head_result.returncode == 0:
                    initial_head = head_result.stdout.strip()
                    env["RALPH_INITIAL_HEAD"] = initial_head
            except Exception:
                pass

            # Use start_new_session to detach from parent process group
            # --output-format json gives us total_cost_usd in the result
            # Apply model routing if specified
            cmd = ["claude", "--print", "--output-format", "json"]
            model_override = env.get("RALPH_MODEL_MODE", "")
            if model_override and model_override != ModelMode.OPUS.value:
                cmd.extend(["--model", model_override])
            cmd.extend(["-p", prompt])

            # Budget guard: check cost before spawning
            if hasattr(self, '_perf_tracker') and self._perf_tracker:
                budget_limit = float(env.get("RALPH_MAX_BUDGET_USD", "0") or "0")
                if budget_limit > 0 and self._perf_tracker.total_cost >= budget_limit:
                    self.log_activity(
                        f"Budget limit ${budget_limit:.2f} reached (spent ${self._perf_tracker.total_cost:.2f}), "
                        f"skipping agent {agent_state.agent_id}",
                        level="WARN"
                    )
                    agent_state.status = AgentStatus.FAILED.value
                    agent_state.completed_at = datetime.now().isoformat()
                    self._failed_count += 1
                    self._print_progress("BUDGET", agent_state.agent_id, f"limit ${budget_limit:.2f} exceeded")
                    await self._update_final_state(agent_state, None)
                    return False

            proc = await asyncio.create_subprocess_exec(
                *cmd,
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
                agent_state.completed_at = datetime.now().isoformat()
                
                # Stop tracking on success
                agent_id_str = f"agent-{agent_state.agent_id}"
                if hasattr(self, '_struggle_detector') and self._struggle_detector:
                    self._struggle_detector.stop_tracking(agent_id_str)
                
                # Write agent complete receipt
                state = self.read_state()
                session_id = state.session_id if state else "unknown"
                write_receipt(
                    agent_id_str,
                    "agent_complete",
                    {
                        "completed_at": agent_state.completed_at,
                        "iterations": agent_state.current_iteration,
                        "ralph_complete": True
                    },
                    session_id
                )

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
                # Record performance metrics
                if hasattr(self, '_perf_tracker') and self._perf_tracker:
                    self._perf_tracker.complete_agent(
                        agent_state.agent_id, cost_usd=cost_usd, num_turns=num_turns, success=True
                    )
                if hasattr(self, '_scheduler') and self._scheduler:
                    self._scheduler.record_activity()
                detail_parts = []
                if cost_usd > 0:
                    detail_parts.append(f"${cost_usd:.2f}")
                if num_turns > 0:
                    detail_parts.append(f"{num_turns} turns")
                self._print_progress("DONE", agent_state.agent_id, ", ".join(detail_parts) if detail_parts else "")

                # Per-task verify+fix for implementation phase agents
                # Skip review/verify-fix agents to avoid infinite loops
                is_implementation_phase = (
                    current_phase == LifecyclePhase.IMPLEMENT.value or
                    env.get("RALPH_AGENT_TYPE") == LifecyclePhase.IMPLEMENT.value
                )
                
                if is_implementation_phase and initial_head:
                    # Get files changed by this agent
                    changed_files = self._get_agent_changed_files(initial_head)
                    agent_state.changed_files = changed_files
                    
                    if changed_files:
                        # Spawn scoped verify+fix agent
                        verify_passed = await self._spawn_scoped_verify_fix(
                            agent_state, changed_files, task
                        )
                        agent_state.verify_fix_passed = verify_passed
                        
                        if not verify_passed:
                            self.log_activity(
                                f"Agent {agent_state.agent_id}: Verify+fix found issues (agent still marked complete)",
                                level="WARN"
                            )
            else:
                agent_state.status = AgentStatus.FAILED.value
                error_msg = stderr_text[:200] if stderr_text else stdout_text[:200]
                
                # Record struggle on failure
                agent_id_str = f"agent-{agent_state.agent_id}"
                if hasattr(self, '_struggle_detector') and self._struggle_detector:
                    self._struggle_detector.record_error(agent_id_str, error_msg)
                
                self.log_activity(
                    f"Agent {agent_state.agent_id} failed (exit {proc.returncode}): {error_msg}",
                    level="ERROR"
                )
                if hasattr(self, '_perf_tracker') and self._perf_tracker:
                    self._perf_tracker.complete_agent(
                        agent_state.agent_id, cost_usd=0, num_turns=0, success=False
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
            
            # Write agent error receipt
            agent_id_str = f"agent-{agent_state.agent_id}"
            state = self.read_state()
            session_id = state.session_id if state else "unknown"
            write_receipt(
                agent_id_str,
                "agent_error",
                {
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "iteration": agent_state.current_iteration,
                    "failed_at": datetime.now().isoformat()
                },
                session_id
            )

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
        
        # Write build intelligence after each agent finishes
        if hasattr(self, '_struggle_detector') and self._struggle_detector:
            self._struggle_detector.write_intelligence()

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
        model_mode: str = ModelMode.OPUS.value,
        max_budget_usd: Optional[float] = None,
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
        
        # Phase tracking for statusline
        self._current_phase = "implementation"
        self._impl_total = num_agents
        self._impl_completed = 0
        self._impl_failed = 0
        self._review_total = 0
        self._review_completed = 0
        self._review_failed = 0
        self._model_mode = model_mode

        # Initialize performance tracking and adaptive scheduling
        self._perf_tracker = PerformanceTracker()
        self._scheduler = ActivityScheduler()

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

        # Print implementation summary
        self._print_summary(successful, failed, exceptions)

        # =====================================================================
        # VERIFY+FIX PHASE - Run build checks and auto-fix issues
        # =====================================================================
        verify_fix_successful = 0
        verify_fix_failed = 0
        verify_fix_exceptions: list[Exception] = []

        # Static config: 3 agents, 2 iterations
        VERIFY_FIX_AGENTS = 3
        VERIFY_FIX_ITERATIONS = 2

        if successful > 0:
            print(flush=True)
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            print(
                f"  {self._C_BOLD}Verify+Fix Phase{self._C_RESET}  "
                f"{VERIFY_FIX_AGENTS} agents x {VERIFY_FIX_ITERATIONS} iterations",
                flush=True
            )
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            print(flush=True)

            # Reset counters for verify-fix phase
            self._loop_start_time = datetime.now()
            self._completed_count = 0
            self._failed_count = 0
            self._total_agents_in_loop = VERIFY_FIX_AGENTS

            # Create verify-fix agent states
            verify_fix_agent_states = [
                AgentState(
                    agent_id=i,
                    max_iterations=VERIFY_FIX_ITERATIONS,
                    status=AgentStatus.PENDING.value
                )
                for i in range(VERIFY_FIX_AGENTS)
            ]

            # Spawn verify-fix agents
            verify_fix_semaphore = asyncio.Semaphore(min(self.MAX_CONCURRENT_AGENTS, VERIFY_FIX_AGENTS))
            verify_fix_tasks = [
                self._spawn_verify_fix_agent(agent, task, verify_fix_semaphore)
                for agent in verify_fix_agent_states
            ]
            verify_fix_results = await asyncio.gather(*verify_fix_tasks, return_exceptions=True)

            # Count verify-fix results
            verify_fix_successful = sum(1 for r in verify_fix_results if r is True)
            verify_fix_failed = sum(1 for r in verify_fix_results if r is False or isinstance(r, Exception))
            verify_fix_exceptions = [r for r in verify_fix_results if isinstance(r, Exception)]

            self.log_activity(
                f"Verify+Fix phase completed: {verify_fix_successful}/{VERIFY_FIX_AGENTS} successful"
            )

            # Print verify-fix summary
            print(flush=True)
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            print(f"{self._C_BOLD}  Verify+Fix Phase Complete{self._C_RESET}", flush=True)
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            print(
                f"  Verify+Fix Agents: {self._C_GREEN}{verify_fix_successful}{self._C_RESET} succeeded, "
                f"{self._C_DIM}{verify_fix_failed}{self._C_RESET} failed",
                flush=True
            )
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )

        # =====================================================================
        # PLAN VERIFICATION PHASE - Verify 100% plan completion
        # =====================================================================
        plan_verified = True
        plan_verification_result = None
        
        if successful > 0 and plan_file:
            # Run plan verification
            plan_verification_result = await self._spawn_plan_verification_agent(task)
            plan_verified = plan_verification_result["verified"]
            missing_tasks = plan_verification_result["missing_tasks"]
            verified_count = plan_verification_result["verified_count"]
            total_count = plan_verification_result["total_count"]
            
            # Print verification summary
            print(flush=True)
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            print(f"{self._C_BOLD}  Plan Verification Complete{self._C_RESET}", flush=True)
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            
            if plan_verified:
                print(
                    f"  Status: {self._C_GREEN}PASS{self._C_RESET} - All {verified_count} tasks completed",
                    flush=True
                )
            else:
                print(
                    f"  Status: {self._C_DIM}INCOMPLETE{self._C_RESET} - {len(missing_tasks)} tasks missing",
                    flush=True
                )
                print(
                    f"  Verified: {self._C_GREEN}{verified_count}{self._C_RESET}/{total_count}",
                    flush=True
                )
                
                # Check if we should retry
                state = self.read_state()
                if state and state.plan_verification_retries < 2:
                    print(
                        f"  {self._C_DIM}Retry {state.plan_verification_retries + 1}/2 - queuing missing tasks{self._C_RESET}",
                        flush=True
                    )
                    
                    # Queue missing tasks and increment retry counter
                    state.plan_verification_retries += 1
                    self.write_state(state)

                    # Note: Missing tasks are logged but not re-queued to implementation phase.
                    # Automatic looping back would require significant restructuring of run_loop
                    # to handle phase transitions and prevent infinite loops. Instead, missing
                    # tasks are surfaced in the verification report for manual follow-up or
                    # can be addressed via a new /start invocation targeting the specific tasks.
                    self.log_activity(
                        f"Plan incomplete - {len(missing_tasks)} tasks missing (retry {state.plan_verification_retries}/2)"
                    )
                    for i, missing_task in enumerate(missing_tasks[:5], 1):
                        self.log_activity(f"  Missing: {missing_task[:100]}")
                else:
                    max_retries_msg = " (max retries reached)" if state and state.plan_verification_retries >= 2 else ""
                    print(
                        f"  {self._C_DIM}Proceeding to review{max_retries_msg}{self._C_RESET}",
                        flush=True
                    )
            
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )

        # =====================================================================
        # REVIEW PHASE - Spawn review agents after implementation
        # =====================================================================
        review_successful = 0
        review_failed = 0
        review_exceptions: list[Exception] = []

        if not skip_review and successful > 0:
            print(flush=True)
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            print(
                f"  {self._C_BOLD}Review Phase{self._C_RESET}  "
                f"{review_agents} agents x {review_iterations} iterations",
                flush=True
            )
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            print(flush=True)

            # Snapshot implementation results before resetting counters
            self._impl_completed = self._completed_count
            self._impl_failed = self._failed_count

            # Transition to review phase
            self._current_phase = "review"
            self._write_progress_file()  # Persist impl snapshot before counter reset

            # Reset counters for review phase
            self._loop_start_time = datetime.now()
            self._completed_count = 0
            self._failed_count = 0
            self._total_agents_in_loop = review_agents
            self._review_total = review_agents

            # Create review agent states
            review_agent_states = [
                AgentState(
                    agent_id=i,
                    max_iterations=review_iterations,
                    status=AgentStatus.PENDING.value
                )
                for i in range(review_agents)
            ]

            # Spawn review agents
            review_semaphore = asyncio.Semaphore(min(self.MAX_CONCURRENT_AGENTS, review_agents))
            review_tasks = [
                self._spawn_review_agent(agent, task, review_semaphore)
                for agent in review_agent_states
            ]
            review_results = await asyncio.gather(*review_tasks, return_exceptions=True)

            # Count review results
            review_successful = sum(1 for r in review_results if r is True)
            review_failed = sum(1 for r in review_results if r is False or isinstance(r, Exception))
            review_exceptions = [r for r in review_results if isinstance(r, Exception)]

            self.log_activity(
                f"Review phase completed: {review_successful}/{review_agents} successful"
            )

            # Print review summary
            print(flush=True)
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            print(f"{self._C_BOLD}  Review Phase Complete{self._C_RESET}", flush=True)
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )
            print(
                f"  Review Agents: {self._C_GREEN}{review_successful}{self._C_RESET} succeeded, "
                f"{self._C_DIM}{review_failed}{self._C_RESET} failed",
                flush=True
            )
            print(
                f"{self._C_DIM}{'=' * 60}{self._C_RESET}",
                flush=True
            )

            # Generate review summary
            self._generate_review_summary()

            # Snapshot review results before transitioning to complete
            self._review_completed = self._completed_count
            self._review_failed = self._failed_count

        elif skip_review:
            self.log_activity("Review phase skipped (--skip-review)")
            # If review skipped, snapshot impl results now
            self._impl_completed = self._completed_count
            self._impl_failed = self._failed_count
            # Review counters remain 0 since review was skipped

        else:
            # Review not run (no successful impl agents) - snapshot impl results
            self._impl_completed = self._completed_count
            self._impl_failed = self._failed_count
            # Review counters remain 0 since review wasn't attempted

        # Mark completion phase
        self._current_phase = "complete"
        self._write_progress_file()  # Persist phase snapshot before cleanup
        
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

    def _generate_review_summary(self) -> Optional[str]:
        """
        Parse review agent outputs and generate review-summary.md.

        Reads .claude/review-agents.md (if exists) and parses tabular findings
        into a structured ReviewSummary, then writes .claude/review-summary.md.

        Returns:
            Path to generated summary file, or None if no review data.
        """
        review_path = self.base_dir / ".claude" / "review-agents.md"
        if not review_path.exists():
            return None

        try:
            content = review_path.read_text(encoding="utf-8")
        except OSError:
            return None

        # Parse findings from markdown table rows
        findings = []
        for line in content.splitlines():
            line = line.strip()
            if not line.startswith("|") or line.startswith("|-") or "Severity" in line:
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 4:
                finding = ReviewFinding(
                    severity=cells[0].lower().strip("🔴🟠🟡🟢🔵 ") or "info",
                    category=cells[1] if len(cells) > 1 else "general",
                    file_path=cells[2] if len(cells) > 2 else "",
                    description=cells[3] if len(cells) > 3 else "",
                    suggestion=cells[4] if len(cells) > 4 else "",
                )
                findings.append(finding)

        if not findings:
            return None

        # Build summary
        state = self.read_state()
        severity_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        for f in findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
            category_counts[f.category] = category_counts.get(f.category, 0) + 1

        summary = ReviewSummary(
            session_id=state.session_id if state else "unknown",
            task=state.task if state else "",
            total_findings=len(findings),
            findings_by_severity=severity_counts,
            findings_by_category=category_counts,
            findings=findings,
            reviewed_at=datetime.now().isoformat(),
        )

        # Write summary
        summary_path = self.base_dir / ".claude" / "review-summary.md"
        try:
            summary_path.write_text(summary.to_markdown(), encoding="utf-8")
            self.log_activity(f"Review summary written: {len(findings)} findings")
            return str(summary_path)
        except OSError:
            return None

    def _build_verify_fix_prompt(self, agent: AgentState, task: Optional[str]) -> str:
        """Build prompt for verify-fix phase agents."""
        vf_config_path = Path(_get_agents_dir()) / "verify-fix.md"
        vf_content = load_agent_config(str(vf_config_path)) if vf_config_path.exists() else ""

        state = self.read_state()
        session_id = state.session_id if state else "unknown"

        return f"""You are Ralph Verify-Fix Agent {agent.agent_id} working on: {task or 'Verify and fix the implementation'}

PHASE: VERIFY+FIX (post-implementation, pre-review)
SESSION: {session_id}
ITERATION: {agent.current_iteration + 1} of {agent.max_iterations}

{vf_content[:3000] if vf_content else ''}

WORK PROTOCOL:
1. Run build checks for the project (pnpm build or npm run build)
2. Use Serena tools to verify symbol integrity across modified files
3. Run type checker (tsc --noEmit or equivalent)
4. Run linter (pnpm lint or biome check)
5. Run dead-code check (pnpm knip if configured)
6. Run validate check (pnpm validate if exists)
7. CLAUDE.md audit - use AskUserQuestion to propose rule additions/improvements
8. Setup recommendations - use AskUserQuestion to suggest automation improvements
9. Design review - verify UI/UX consistency if frontend changes present
10. Auto-fix simple issues (imports, types, formatting)
11. Use AskUserQuestion for complex issues requiring human decision
12. Do NOT leave TODO comments — fix or escalate
13. IMPORTANT: Write summary of quality check results (steps 1-9) to .claude/verify-fix-quality.log
    - Include: build status, type errors, lint issues, dead code, validation results
    - Format as concise bullet list for review phase context
14. Use mcp__serena__think_about_whether_you_are_done before completion
15. Push ALL commits before signaling completion
16. When all verification is done, output EXACTLY:
   {self.RALPH_COMPLETE_SIGNAL}
   {self.EXIT_SIGNAL}

TOOLS: All standard tools + Serena MCP + Context7 MCP

Begin verification now.
"""

    def _build_agent_prompt(self, agent: AgentState, task: Optional[str]) -> str:
        """Build the initial prompt for an agent with agent config loading (Step 3)."""
        # Read team state for session info
        state = self.read_state()
        session_id = state.session_id if state else "unknown"
        total = state.total_agents if state else 1

        # Use ralph_lib.build_agent_prompt for consistent prompt generation
        return build_agent_prompt(
            agent_id=agent.agent_id,
            total_agents=total,
            current_iteration=agent.current_iteration,
            max_iterations=agent.max_iterations,
            task=task,
            session_id=session_id,
            complete_signal=self.RALPH_COMPLETE_SIGNAL,
            exit_signal=self.EXIT_SIGNAL,
            assigned_config=None,  # Use round-robin assignment
        )


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
            # All implementation agents done → transition to verify_fix
            vf_config = state.get("verify_fix", {"agents": 2, "iterations": 2})
            vf_agents = vf_config.get("agents", 2)
            task = state.get("task", "Verify and fix the implementation")

            state["phase"] = "verify_fix"
            state["completedAgents"] = 0  # Reset for verify_fix phase

            activity_log.append({
                "timestamp": timestamp,
                "event": "phase_transition",
                "from": "implementation",
                "to": "verify_fix"
            })

            output_msg = f"""🔄 RALPH PHASE TRANSITION: Implementation → Verify+Fix

All {expected} implementation agents completed.

**MANDATORY NEXT STEP:**
Spawn {vf_agents} verify-fix agents IN PARALLEL:

```
Task(subagent_type: "general-purpose", prompt: "RALPH Verify-Fix Agent 1/{vf_agents}: Verify and fix implementation for {task}")
Task(subagent_type: "general-purpose", prompt: "RALPH Verify-Fix Agent 2/{vf_agents}: Verify and fix implementation for {task}")
```

Verify-Fix agents should:
1. Run build checks (`pnpm build` / `python -m py_compile`)
2. Use Serena to verify symbol integrity
3. Run type checks where applicable
4. Auto-fix simple issues (imports, types, formatting)
5. Use AskUserQuestion for complex issues
6. Do NOT leave TODO comments — fix or escalate

**DO NOT** output completion signals yet. Spawn verify-fix agents NOW."""

    elif phase == "verify_fix":
        vf_config = state.get("verify_fix", {"agents": 2, "iterations": 2})
        expected = vf_config.get("agents", 2)
        if completed >= expected:
            # All verify-fix agents done → transition to review
            review_config = state.get("review", {"agents": 5, "iterations": 2})
            review_agents = review_config.get("agents", 5)
            review_iterations = review_config.get("iterations", 2)
            task = state.get("task", "Review the implementation")

            state["phase"] = "review"
            state["completedAgents"] = 0  # Reset for review phase

            activity_log.append({
                "timestamp": timestamp,
                "event": "phase_transition",
                "from": "verify_fix",
                "to": "review"
            })

            output_msg = f"""🔄 RALPH PHASE TRANSITION: Verify+Fix → Review

All {expected} verify-fix agents completed.

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
- Verify-fix agents: {state.get("verify_fix", {}).get("agents", 2)} completed
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
    ralph.py prompt N [task]            - Generate N agent prompts for Task tool spawning
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
    ralph.py hook-subagent-start        - Handle SubagentStart hook (reads stdin)
    ralph.py hook-subagent-stop         - Handle SubagentStop hook (reads stdin)

Loop / Setup Options:
    --review-agents RN      Number of post-review agents (default: 5)
    --review-iterations RM  Iterations per review agent (default: 2)
    --skip-review           Skip post-implementation review
    --plan FILE             Path to plan file being executed
    --backend BACKEND       Spawn backend: task|subprocess|auto (default: auto)
                            NOTE: 'task' backend requires manual Task() spawning in parent session.
                            Use 'ralph.py prompt N' to generate prompts, then spawn via Task tool.
    --model MODE            Model routing: opus|sonnet|sonnet_all (default: opus)
    --budget USD            Max budget in USD (stop spawning when exceeded)

Cleanup Options:
    --auto                  Run age-based cleanup instead of full cleanup
    --max-age N             Days threshold for auto-cleanup (default: 7)

Examples:
    ralph.py loop 3 3 "Implement feature X"
    ralph.py loop 50 15 --review-agents 15 --review-iterations 10 "Big feature"
    ralph.py loop 10 5 --skip-review "Quick fix"
    ralph.py loop 30 10 --plan /path/to/plan.md "Execute plan"
    ralph.py prompt 5 "Implement auth system"  # Generate prompts for parent Task spawning
    ralph.py setup 10 3 --backend task "Initialize only"
    ralph.py teardown
    ralph.py status
    ralph.py resume
    ralph.py cleanup --auto --max-age 3

Task Backend Workflow:
    1. Run: ralph.py prompt 5 "implement feature"
    2. In parent Claude session, spawn returned prompts via Task tool:
       Task(prompt="...agent 1 prompt...")
       Task(prompt="...agent 2 prompt...")
       ...
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
        model_mode = ModelMode.OPUS.value
        max_budget_usd = None
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
            elif arg == "--model" and i + 1 < len(sys.argv):
                model_mode = sys.argv[i + 1]
                valid_modes = [m.value for m in ModelMode]
                if model_mode not in valid_modes:
                    print(f"Error: --model must be one of: {', '.join(valid_modes)}")
                    sys.exit(1)
                i += 2
            elif arg == "--budget" and i + 1 < len(sys.argv):
                try:
                    max_budget_usd = float(sys.argv[i + 1])
                except ValueError:
                    print("Error: --budget must be a number (USD)")
                    sys.exit(1)
                i += 2
            else:
                task_parts.append(arg)
                i += 1

        task = " ".join(task_parts) if task_parts else None

        # Set model/budget env vars for subprocess agents
        if model_mode != ModelMode.OPUS.value:
            os.environ["RALPH_MODEL_MODE"] = model_mode
        if max_budget_usd is not None:
            os.environ["RALPH_MAX_BUDGET_USD"] = str(max_budget_usd)

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
            model_mode=model_mode,
            max_budget_usd=max_budget_usd,
        ))

    elif command == "prompt":
        # Generate agent prompts for parent session Task spawning
        if len(sys.argv) < 3:
            print("Usage: ralph.py prompt N [task]")
            sys.exit(1)
        
        try:
            num_agents = int(sys.argv[2])
        except ValueError:
            print("Error: N must be an integer")
            sys.exit(1)
        
        task_parts = sys.argv[3:] if len(sys.argv) > 3 else []
        task = " ".join(task_parts) if task_parts else None
        
        # Generate prompts without spawning
        max_iterations = 3  # Default for prompt generation
        agents = [
            AgentState(
                agent_id=i,
                max_iterations=max_iterations,
                status=AgentStatus.PENDING.value
            )
            for i in range(num_agents)
        ]
        
        # Create temporary state for prompt generation
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        state = RalphState(
            session_id=session_id,
            task=task,
            total_agents=num_agents,
            max_iterations=max_iterations,
            agents=agents,
            started_at=datetime.now().isoformat()
        )
        protocol.write_state(state)
        
        print(f"\nGenerated {num_agents} agent prompts for Task spawning:")
        print("=" * 70)
        print("\nCopy these prompts and spawn them in your parent Claude session using Task():\n")
        
        for i, agent in enumerate(agents):
            prompt = protocol._build_agent_prompt(agent, task)
            print(f"# Agent {i}")
            print(f'Task(prompt="""{prompt}""")')
            print()
        
        print("=" * 70)
        print(f"\nAfter spawning all {num_agents} agents, they will share the TaskList")
        print("and coordinate via the Ralph protocol.")
        
        # Clean up temporary state
        protocol.cleanup_ralph_session(keep_activity_log=False)

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

    elif command == "hook-subagent-start":
        # SubagentStart hook handler
        result = protocol.handle_hook_subagent_start()
        print(json.dumps(result))

    elif command == "hook-subagent-stop":
        # SubagentStop hook handler
        result = protocol.handle_hook_subagent_stop()
        print(json.dumps(result))

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
