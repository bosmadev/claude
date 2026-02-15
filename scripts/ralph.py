#!/usr/bin/env python3
"""
Ralph Protocol - Hook Handlers and Agent Utilities

This module implements the Ralph Protocol for managing autonomous Claude agent
loops with hook integration, agent configuration, and work-stealing queues.

Orchestration uses Claude Code native Agent Teams (TeamCreate/Task/SendMessage).
Subprocess orchestration has been removed — see /start skill for team-based flow.

Usage:
    ralph.py prompt N [task]         - Generate N agent prompts for Task tool spawning
    ralph.py status                  - Show current Ralph state
    ralph.py cleanup                 - Clean up all state files
    ralph.py cleanup --auto          - Auto-cleanup old files (default: 7 days)
    ralph.py agent-tracker           - Handle PostToolUse:Task hook (reads stdin)
    ralph.py hook-stop               - Handle hook-stop (reads stdin)
    ralph.py hook-pretool            - Handle hook-pretool (reads stdin)
    ralph.py hook-user-prompt        - Handle hook-user-prompt (reads stdin)
    ralph.py hook-session            - Handle hook-session-start (reads stdin)
    ralph.py hook-subagent-start     - Handle SubagentStart hook (reads stdin)
    ralph.py hook-subagent-stop      - Handle SubagentStop hook (reads stdin)
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
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from zoneinfo import ZoneInfo

# Ralph library functions (merged from ralph_lib.py)

# =============================================================================
# Agent Specialties + Auto-Assignment
# =============================================================================

AGENT_SPECIALTIES: dict[str, list[str]] = {
    "security-auditor": ["security", "auth", "owasp", "xss", "csrf", "injection", "vulnerability", "encryption", "token", "password"],
    "performance-auditor": ["performance", "speed", "latency", "cache", "optimize", "memory", "profil", "bottleneck", "slow"],
    "api-specialist": ["api", "rest", "graphql", "endpoint", "route", "http", "request", "response", "cors", "middleware"],
    "architecture-reviewer": ["architecture", "pattern", "design", "structure", "module", "dependency", "coupling", "solid"],
    "a11y-reviewer": ["accessibility", "a11y", "aria", "wcag", "screen reader", "keyboard", "contrast", "focus"],
    "database-reviewer": ["database", "sql", "query", "migration", "schema", "index", "orm", "prisma", "drizzle"],
    "commit-reviewer": ["commit", "git", "merge", "branch", "changelog", "version", "release"],
    "performance-optimizer": ["profile", "benchmark", "flame", "trace", "cpu", "heap", "allocation"],
    "doc-accuracy-checker": ["documentation", "readme", "jsdoc", "docstring", "comment", "api doc"],
    "build-error-resolver": ["build", "compile", "error", "typescript", "lint", "biome", "webpack", "vite", "bundle"],
    "refactor-cleaner": ["refactor", "clean", "dead code", "unused", "duplicate", "simplify", "extract"],
    "e2e-runner": ["test", "e2e", "playwright", "cypress", "selenium", "integration test", "coverage"],
    "review-coordinator": ["review", "coordinate", "summary", "aggregate", "findings", "report"],
    "nextjs-specialist": ["nextjs", "next", "react", "ssr", "server component", "app router", "page", "layout"],
    "python-specialist": ["python", "fastapi", "django", "flask", "pip", "uv", "pytest", "pydantic"],
    "go-specialist": ["go", "golang", "goroutine", "channel", "gin", "fiber"],
    "devops-automator": ["devops", "ci", "cd", "docker", "kubernetes", "deploy", "pipeline", "github actions"],
    "scraper-agent": ["scrape", "crawl", "extract", "parse", "html", "browser", "puppeteer"],
    "pr-body-generator": ["pr", "pull request", "description", "summary", "changelog"],
}


def _get_agents_dir() -> str:
    """Get default agents directory, cross-platform."""
    _home = os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude") if sys.platform == "win32" else "/usr/share/claude")
    return str(Path(_home) / "agents")


def discover_agent_configs(agents_dir: str | None = None) -> dict[str, str]:
    """Discover ALL agent config files (not just reviewers).

    Returns:
        Dict mapping config name to file path.
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


def match_agent_to_task(task: str, agents_dir: str | None = None) -> str:
    """Match a task description to the best-fit agent config via keyword overlap scoring."""
    if not task:
        return "general"

    task_lower = task.lower()
    best_match = "general"
    best_score = 0

    available = discover_agent_configs(agents_dir)

    for agent_name, keywords in AGENT_SPECIALTIES.items():
        if agent_name not in available:
            continue
        score = sum(1 for kw in keywords if kw in task_lower)
        if score > best_score:
            best_score = score
            best_match = agent_name

    return best_match if best_score > 0 else "general"


def generate_agent_name(phase: str, specialty: str, index: int) -> str:
    """Generate a structured agent name (ralph-{phase}-{specialty}-{index})."""
    phase_abbrev = {
        "implementation": "impl",
        "verify_fix": "vf",
        "review": "review",
        "plan": "plan",
        "complete": "done",
    }.get(phase, phase[:4])

    spec = specialty.replace("-reviewer", "").replace("-specialist", "").replace("-", "")[:8]
    return f"ralph-{phase_abbrev}-{spec}-{index}"


def build_agent_prompt(
    agent_id: int,
    total_agents: int,
    current_iteration: int,
    max_iterations: int,
    task: Optional[str],
    session_id: str,
    complete_signal: str,
    exit_signal: str,
    assigned_config: Optional[str] = None,
) -> str:
    """Build the initial prompt for an agent with agent config loading."""
    all_configs = discover_agent_configs()
    config_names = list(all_configs.keys())
    agent_config_content = ""
    assigned_role = "general"

    if assigned_config and assigned_config in all_configs:
        config_path = all_configs[assigned_config]
        agent_config_content = load_agent_config(config_path)
        assigned_role = assigned_config
    elif config_names:
        config_name = config_names[agent_id % len(config_names)]
        config_path = all_configs[config_name]
        agent_config_content = load_agent_config(config_path)
        assigned_role = config_name

    role_section = ""
    if agent_config_content:
        role_section = f"""
ROLE CONFIG ({assigned_role}):
{agent_config_content[:2000]}
"""

    inbox_section = f"""
COORDINATION:
- Check inbox: .claude/ralph/team-{session_id}/inbox/agent-{agent_id}.json
- Report completion: write task_completed message to relay
- If idle: write idle_notification message
- Heartbeat: write to .claude/ralph/team-{session_id}/heartbeat/agent-{agent_id}.json
"""

    return f"""You are Ralph Agent {agent_id}/{total_agents} working on: {task or 'Complete the assigned development work'}

ASSIGNMENT: {assigned_role}
ITERATION: {current_iteration + 1} of {max_iterations}
{role_section}
WORK PROTOCOL:
1. Call TaskList to see available tasks
2. Claim next available task (status=pending, no blockers)
3. Work autonomously — no confirmation needed
4. Push ALL commits before signaling completion
5. Mark task completed, claim next
6. When all your work is done, output EXACTLY:
   {complete_signal}
   {exit_signal}
{inbox_section}
TOOLS: All standard tools + Context7 MCP

Begin working now.
"""


# =============================================================================
# Work-Stealing Queue Data Models
# =============================================================================

@dataclass
class QueueTask:
    """Task in the work-stealing queue."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str = ""
    status: str = "pending"
    blocked_by: list = field(default_factory=list)
    claimed_by: Optional[str] = None
    iterations: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id, "description": self.description, "status": self.status,
            "blockedBy": self.blocked_by, "claimed_by": self.claimed_by,
            "iterations": self.iterations, "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "QueueTask":
        return cls(
            id=data["id"], description=data.get("description", ""),
            status=data.get("status", "pending"), blocked_by=data.get("blockedBy", []),
            claimed_by=data.get("claimed_by"), iterations=data.get("iterations", 0),
            started_at=data.get("started_at"), completed_at=data.get("completed_at"),
        )


@dataclass
class TaskQueue:
    """Work-stealing task queue tied to a plan file (JSON and Markdown)."""
    plan_id: str
    plan_file: str
    created_at: str
    tasks: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id, "plan_file": self.plan_file,
            "created_at": self.created_at,
            "tasks": [t.to_dict() if isinstance(t, QueueTask) else t for t in self.tasks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskQueue":
        return cls(
            plan_id=data["plan_id"], plan_file=data["plan_file"],
            created_at=data["created_at"],
            tasks=[QueueTask.from_dict(t) if isinstance(t, dict) else t for t in data.get("tasks", [])],
        )

    def to_markdown(self) -> str:
        """Generate markdown representation of task queue."""
        completed = [t for t in self.tasks if t.status == "completed"]
        in_progress = [t for t in self.tasks if t.status == "in_progress"]
        pending = [t for t in self.tasks if t.status == "pending"]

        lines = [
            "---", f"plan_id: {self.plan_id}", f"created: {self.created_at}",
            f"total_tasks: {len(self.tasks)}", f"completed: {len(completed)}", "---",
            "", f"# Task Queue: {self.plan_id}", "",
        ]

        if completed:
            lines.append("## Completed")
            for task in completed:
                agent_info = f" ({task.claimed_by})" if task.claimed_by else ""
                lines.append(f"- [x] Task {task.id}: {task.description}{agent_info}")
            lines.append("")

        if in_progress:
            lines.append("## In Progress")
            for task in in_progress:
                agent_info = f" ({task.claimed_by})" if task.claimed_by else ""
                lines.append(f"- [/] Task {task.id}: {task.description}{agent_info}")
            lines.append("")

        if pending:
            lines.append("## Pending")
            for task in pending:
                blocked_info = f" (blocked by: {', '.join(task.blocked_by)})" if task.blocked_by else ""
                lines.append(f"- [ ] Task {task.id}: {task.description}{blocked_info}")
            lines.append("")

        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, content: str, plan_id: str = None, plan_file: str = None) -> "TaskQueue":
        """Parse markdown task queue into TaskQueue object."""
        import re

        lines = content.split("\n")
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

        extracted_plan_id = plan_id or frontmatter.get("plan_id", "unknown")
        extracted_plan_file = plan_file or frontmatter.get("plan_file", "")
        created_at = frontmatter.get("created", datetime.now().isoformat())

        tasks = []
        task_pattern = re.compile(r"^-\s+\[([ x/])\]\s+Task\s+(\d+):\s+(.+?)(?:\s+\(([^)]+)\))?(?:\s+\(blocked by:\s+([^)]+)\))?$")

        for line in tasks_section:
            match = task_pattern.match(line.strip())
            if match:
                checkbox, task_id, description, claimed_by, blocked_by = match.groups()
                if checkbox == "x":
                    status = "completed"
                elif checkbox == "/":
                    status = "in_progress"
                else:
                    status = "pending"
                blocked_list = [b.strip() for b in blocked_by.split(",")] if blocked_by else []
                tasks.append(QueueTask(
                    id=task_id, description=description.strip(),
                    status=status, claimed_by=claimed_by, blocked_by=blocked_list,
                ))

        return cls(plan_id=extracted_plan_id, plan_file=extracted_plan_file, created_at=created_at, tasks=tasks)


# =============================================================================
# Work-Stealing Queue
# =============================================================================

class WorkStealingQueue:
    """File-based work-stealing queue with atomic task claiming.

    Location: {project}/.claude/task-queue-{plan-id}.json or .md
    Uses file locking to prevent race conditions.
    """

    QUEUE_DIR = ".claude"
    LOCK_SUFFIX = ".lock"

    def __init__(self, plan_id: str, plan_file: str, base_dir: Optional[Path] = None, format: str = "markdown"):
        self.plan_id = plan_id
        self.plan_file = plan_file
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.format = format

        ext = ".md" if format == "markdown" else ".json"
        self.queue_path = self.base_dir / self.QUEUE_DIR / f"task-queue-{plan_id}{ext}"
        self.lock_path = self.base_dir / self.QUEUE_DIR / f"task-queue-{plan_id}{self.LOCK_SUFFIX}"

    def _ensure_dir(self) -> None:
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)

    def _acquire_lock(self) -> int:
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
        if sys.platform == "win32":
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def load(self) -> TaskQueue:
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
        return TaskQueue(plan_id=self.plan_id, plan_file=self.plan_file, created_at=datetime.now().isoformat(), tasks=[])

    def save(self, queue: TaskQueue) -> None:
        self._ensure_dir()
        if self.format == "markdown":
            self.queue_path.write_text(queue.to_markdown(), encoding="utf-8")
        else:
            with open(self.queue_path, "w") as f:
                json.dump(queue.to_dict(), f, indent=2)

    def claim_next_task(self, agent_id: str) -> Optional[QueueTask]:
        """Atomically claim the next available task."""
        fd = self._acquire_lock()
        try:
            queue = self.load()
            completed_ids = {t.id for t in queue.tasks if t.status == "completed"}
            for task in queue.tasks:
                if task.status != "pending" or task.claimed_by:
                    continue
                if not all(b in completed_ids for b in task.blocked_by):
                    continue
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

    def mark_task_complete(self, task_id: str, agent_id: str) -> bool:
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

    def add_task(self, task_id: str, description: str = "", blocked_by: list = None) -> QueueTask:
        fd = self._acquire_lock()
        try:
            queue = self.load()
            task = QueueTask(id=task_id, description=description, status="pending", blocked_by=blocked_by or [])
            queue.tasks.append(task)
            self.save(queue)
            return task
        finally:
            self._release_lock(fd)

    def get_status(self) -> dict:
        queue = self.load()
        status_counts = {"pending": 0, "in_progress": 0, "completed": 0}
        for task in queue.tasks:
            status_counts[task.status] = status_counts.get(task.status, 0) + 1
        return {"plan_id": queue.plan_id, "total_tasks": len(queue.tasks), **status_counts}

    def reclaim_stale_tasks(self, timeout_seconds: int = 300) -> list:
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
                    if (now - started).total_seconds() > timeout_seconds:
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


# Convenience functions for work-stealing queue
def claim_next_task(agent_id: str, plan_id: str, plan_file: str, base_dir: Optional[Path] = None) -> Optional[QueueTask]:
    """Atomic task claiming with file lock."""
    return WorkStealingQueue(plan_id, plan_file, base_dir).claim_next_task(agent_id)


def release_task(task_id: str, plan_id: str, plan_file: str, base_dir: Optional[Path] = None) -> bool:
    """Release uncompleted task back to queue."""
    return WorkStealingQueue(plan_id, plan_file, base_dir).release_task(task_id)


def mark_task_complete(task_id: str, agent_id: str, plan_id: str, plan_file: str, base_dir: Optional[Path] = None) -> bool:
    """Mark task as done."""
    return WorkStealingQueue(plan_id, plan_file, base_dir).mark_task_complete(task_id, agent_id)


# Import transaction primitives from hooks
sys.path.insert(0, str(Path(__file__).parent.parent))
from hooks.transaction import atomic_write_json, transactional_update

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
CONTEXT_FILE_PATH = Path.home() / ".claude" / "ralph" / "pending-context.md"

# =============================================================================
# Model Configuration for VERIFY+FIX Phases
# =============================================================================

# Model to use for all VERIFY+FIX operations (configurable via CLAUDE_CODE_VERIFY_FIX_MODEL)
VERIFY_FIX_MODEL = os.environ.get("CLAUDE_CODE_VERIFY_FIX_MODEL", "claude-opus-4-6")

# Effort levels for different VERIFY+FIX modes
VERIFY_FIX_EFFORT: dict[str, str] = {
    "scoped": "medium",   # Per-task verification: fast, focused
    "full": "high",       # Post-all-impl: thorough final gate
    "plan": "medium",     # Plan verification: moderate depth
}

# =============================================================================
# Receipt Audit Trail System
# =============================================================================

RECEIPTS_DIR = Path.home() / ".claude" / "ralph" / "receipts"

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
            checkpoint = Path.home() / ".claude" / "ralph" / "checkpoint.json"
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
        self._lock = threading.Lock()
    
    def record_error(self, agent_id: str, error_msg: str = "") -> None:
        """
        Record an error for an agent.

        Args:
            agent_id: Agent identifier (e.g., "agent-1")
            error_msg: Error message text
        """
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            self._start_times[agent_id] = datetime.now()
    
    def stop_tracking(self, agent_id: str) -> None:
        """
        Stop time tracking and update elapsed time.

        Args:
            agent_id: Agent identifier
        """
        with self._lock:
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
        with self._lock:
            if agent_id not in self._metrics:
                return False
            return self._metrics[agent_id].struggling
    
    def get_struggle_summary(self) -> dict:
        """
        Get summary of struggling agents.

        Returns:
            Dictionary with total_struggling and total_agents counts
        """
        with self._lock:
            struggling = sum(1 for m in self._metrics.values() if m.struggling)
            return {
                "total_struggling": struggling,
                "total_agents": len(self._metrics)
            }
    
    def write_intelligence(self) -> None:
        """Write build intelligence data to JSON file."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
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
        except OSError as e:
            # Log but don't fail - intelligence is nice-to-have
            print(f"Warning: Failed to write build intelligence: {e}", file=sys.stderr)
    
    def _update_struggle_state(self, agent_id: str) -> None:
        """
        Update struggling flag based on thresholds.

        Args:
            agent_id: Agent identifier

        Note:
            Called from within locked sections - does not acquire lock.
        """
        metrics = self._metrics[agent_id]
        metrics.struggling = (
            metrics.error_count >= self.ERROR_THRESHOLD or
            metrics.retry_count >= self.RETRY_THRESHOLD
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

class TaskQueueParser:
    """
    Parser for markdown task lists with priority-based format.
    
    Supports formats:
    - [ ] P1: Description - blocked by: task-name
    - [x] P2: Description - completed
    - [ ] P3: Description - depends on: task-name
    
    Features:
    - Priority extraction (P1/P2/P3)
    - Status parsing (pending/in_progress/completed)
    - Dependency detection (blocked by/depends on)
    - Plan file parsing
    - Round-trip conversion (markdown <-> QueueTask)
    """
    
    @staticmethod
    def parse_markdown(content: str) -> list[QueueTask]:
        """
        Parse markdown content into list of QueueTask objects.
        
        Supports priority labels (P1/P2/P3) and dependency syntax.
        
        Args:
            content: Markdown task list content
            
        Returns:
            List of QueueTask objects
        """
        import re

        tasks = []
        lines = content.strip().split("\n")
        
        # Pattern: - [checkbox] P1: Description - blocked by: task-name
        # Supports em-dash (\u2014), en-dash (\u2013), and hyphen as separators
        task_pattern = re.compile(
            r"^-\s+\[([ x/])\]\s+(?:P[123]:\s+)?(.+?)(?:\s+[\u2014\u2013-]\s+(?:blocked by|depends on):\s+(.+))?$",
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
            atomic_write_json(self.queue_path, queue.to_dict(), fsync=True)

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

            # Add integrity marker for state.json
            state_data = state.to_dict()
            state_data["integrity_marker"] = "claude_ralph_state_v1"
            atomic_write_json(self.state_path, state_data, fsync=True)
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
            atomic_write_json(self.progress_path, progress_data, fsync=True)
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
        and provide integration context.

        Orphan detection:
        1. Sessions older than 24 hours → cleanup
        2. Sessions with no running processes → cleanup
        3. Sessions marked complete but not cleaned → cleanup

        Args:
            stdin_content: Raw stdin from hook.

        Returns:
            Hook response with restoration status.
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

        # Serena MCP removed (2026-02-13) — using CC native tools only

        return response

    # =========================================================================
    # SubagentStart / SubagentStop Hook Handlers
    # =========================================================================

    def handle_hook_subagent_start(self, stdin_content: Optional[str] = None) -> dict:
        """
        Handle SubagentStart hook - track agent spawn in state.

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
        Handle SubagentStop hook - track agent completion, enforce iteration limits, manage retries.

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
        self._update_progress_with_agent_cost(cost_usd, exit_status=exit_status)

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

    def _update_progress_with_agent_cost(self, cost_usd: float, exit_status: int = 0) -> None:
        """Update progress.json with aggregated agent cost and completion status."""
        try:
            progress_path = self.base_dir / self.PROGRESS_FILE

            def update_fn(current: dict) -> dict:
                """Apply cost and completion updates."""
                # Initialize if None (file doesn't exist)
                if current is None:
                    current = {
                        "total": 0,
                        "completed": 0,
                        "failed": 0,
                        "done": 0,
                        "cost_usd": 0,
                    }

                # Update cost
                current["cost_usd"] = round(current.get("cost_usd", 0) + cost_usd, 4)

                # Update completion counters based on exit status
                if exit_status == 0:
                    current["completed"] = current.get("completed", 0) + 1
                else:
                    current["failed"] = current.get("failed", 0) + 1
                current["done"] = current.get("completed", 0) + current.get("failed", 0)

                current["updated_at"] = datetime.now().isoformat()
                current["integrity_marker"] = "claude_ralph_progress_v1"

                return current

            # Use transactional_update with locking
            transactional_update(
                progress_path,
                update_fn,
                timeout=5.0,
                retries=3,
                fsync=True,
                default={
                    "total": 0,
                    "completed": 0,
                    "failed": 0,
                    "done": 0,
                    "cost_usd": 0,
                }
            )
        except Exception:
            # Silent fail as before (progress updates are non-critical)
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

            # Write updated retry queue with integrity marker
            retry_queue_path.parent.mkdir(parents=True, exist_ok=True)
            retry_queue["integrity_marker"] = "claude_ralph_retry_v1"
            atomic_write_json(retry_queue_path, retry_queue, fsync=True)

            self.log_activity(
                f"Agent {agent_id} queued for retry (attempt {current_retry_count + 1}/{MAX_RETRIES})"
            )
            return True

        except (IOError, json.JSONDecodeError) as e:
            self.log_activity(f"Failed to queue agent for retry: {e}", level="ERROR")
            return False

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

    def _build_agent_prompt(self, agent: AgentState, task: Optional[str]) -> str:
        """Build the initial prompt for an agent with agent config loading (Step 3)."""
        # Read team state for session info
        state = self.read_state()
        session_id = state.session_id if state else "unknown"
        total = state.total_agents if state else 1

        # Use build_agent_prompt for consistent prompt generation
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

    # Check for stale session (>4h old) - auto-cleanup (Fix B)
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
2. Verify symbol integrity via Grep/Read
3. Run type checks where applicable
4. Auto-fix simple issues (imports, types, formatting)
5. Use AskUserQuestion for complex issues
6. Do NOT leave TODO comments - fix or escalate

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
Ralph Protocol - Hook Handlers and Utilities

Usage:
    ralph.py prompt N [task]            - Generate N agent prompts for Task tool spawning
    ralph.py status                     - Show current Ralph state
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

Cleanup Options:
    --auto                  Run age-based cleanup instead of full cleanup
    --max-age N             Days threshold for auto-cleanup (default: 7)

Examples:
    ralph.py prompt 5 "Implement auth system"  # Generate prompts for parent Task spawning
    ralph.py status
    ralph.py cleanup --auto --max-age 3

NOTE: Subprocess orchestration (loop, setup, teardown, resume commands) has been removed.
      All orchestration now uses Claude Code native Agent Teams via Task() tool.
      See /start skill for team-based orchestration.
""")

def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1]
    protocol = RalphProtocol()

    if command == "prompt":
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

    elif command == "status":
        protocol.cmd_status()

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
