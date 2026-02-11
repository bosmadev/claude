"""Ralph Library - Reusable functions for Ralph protocol.

This module contains extracted functions from ralph.py for agent management,
configuration loading, task matching, and work-stealing queue operations.
"""

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# =============================================================================
# Agent Specialties + Auto-Assignment
# =============================================================================

AGENT_SPECIALTIES: dict[str, list[str]] = {
    "security-reviewer": ["security", "auth", "owasp", "xss", "csrf", "injection", "vulnerability", "encryption", "token", "password"],
    "performance-reviewer": ["performance", "speed", "latency", "cache", "optimize", "memory", "profil", "bottleneck", "slow"],
    "api-reviewer": ["api", "rest", "graphql", "endpoint", "route", "http", "request", "response", "cors", "middleware"],
    "architecture-reviewer": ["architecture", "pattern", "design", "structure", "module", "dependency", "coupling", "solid"],
    "a11y-reviewer": ["accessibility", "a11y", "aria", "wcag", "screen reader", "keyboard", "contrast", "focus"],
    "database-reviewer": ["database", "sql", "query", "migration", "schema", "index", "orm", "prisma", "drizzle"],
    "commit-reviewer": ["commit", "git", "merge", "branch", "changelog", "version", "release"],
    "performance-profiler": ["profile", "benchmark", "flame", "trace", "cpu", "heap", "allocation"],
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
    """Get default agents directory, cross-platform.

    Returns:
        Path to agents directory (e.g., ~/.claude/agents or /usr/share/claude/agents).
    """
    _home = os.environ.get("CLAUDE_HOME", str(Path.home() / ".claude") if sys.platform == "win32" else "/usr/share/claude")
    return str(Path(_home) / "agents")


def discover_agent_configs(agents_dir: str | None = None) -> dict[str, str]:
    """Discover ALL agent config files (not just reviewers).

    Args:
        agents_dir: Path to agents directory. If None, uses default.

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
    """Load an agent config file content.

    Args:
        config_path: Path to agent config file (e.g., ~/.claude/agents/security-reviewer.md).

    Returns:
        Config file content as string, or empty string if file not found.
    """
    try:
        return Path(config_path).read_text(encoding="utf-8")
    except OSError:
        return ""


def match_agent_to_task(task: str, agents_dir: str | None = None) -> str:
    """Match a task description to the best-fit agent config via keyword overlap scoring.

    Uses AGENT_SPECIALTIES to score task descriptions against agent keywords.
    Returns the agent config name with the highest keyword match score.

    Args:
        task: The task description to match against.
        agents_dir: Path to agents directory. If None, uses default.

    Returns:
        Config name of the best-matching agent (e.g., "security-reviewer").
        Returns "general" if no good match found.

    Example:
        >>> match_agent_to_task("Fix XSS vulnerability in login form")
        'security-reviewer'
        >>> match_agent_to_task("Optimize database query performance")
        'performance-reviewer'
    """
    if not task:
        return "general"

    task_lower = task.lower()
    best_match = "general"
    best_score = 0

    # Check available agents on disk
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
    """Generate a structured agent name.

    Format: ralph-{phase}-{specialty}-{index}

    Args:
        phase: Lifecycle phase (impl, vf, review).
        specialty: Agent specialty (security, api, etc.).
        index: Agent index number.

    Returns:
        Structured agent name string.

    Example:
        >>> generate_agent_name("implementation", "security-reviewer", 0)
        'ralph-impl-security-0'
        >>> generate_agent_name("review", "api-reviewer", 3)
        'ralph-review-api-3'
    """
    # Abbreviate phase names for conciseness
    phase_abbrev = {
        "implementation": "impl",
        "verify_fix": "vf",
        "review": "review",
        "plan": "plan",
        "complete": "done",
    }.get(phase, phase[:4])

    # Sanitize specialty (remove -reviewer, -specialist suffixes)
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
    """Build the initial prompt for an agent with agent config loading.

    Args:
        agent_id: Agent's numeric ID (0-indexed).
        total_agents: Total number of agents in the team.
        current_iteration: Current iteration number (0-indexed).
        max_iterations: Maximum iterations allowed.
        task: Task description string.
        session_id: Ralph session ID for coordination.
        complete_signal: Signal string for completion (deprecated, use TaskUpdate+SendMessage).
        exit_signal: Signal string for exit (e.g., "EXIT").
        assigned_config: Pre-assigned agent config name. If None, uses round-robin.

    Returns:
        Complete agent prompt string.
    """
    # Discover and assign agent config via round-robin or explicit assignment
    all_configs = discover_agent_configs()
    config_names = list(all_configs.keys())
    agent_config_content = ""
    assigned_role = "general"

    if assigned_config and assigned_config in all_configs:
        # Use explicit assignment
        config_path = all_configs[assigned_config]
        agent_config_content = load_agent_config(config_path)
        assigned_role = assigned_config
    elif config_names:
        # Round-robin assignment
        config_name = config_names[agent_id % len(config_names)]
        config_path = all_configs[config_name]
        agent_config_content = load_agent_config(config_path)
        assigned_role = config_name

    # Build enhanced prompt
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
6. Before completion, call mcp__serena__think_about_whether_you_are_done
7. When all your work is done, output EXACTLY:
   {complete_signal}
   {exit_signal}
{inbox_section}
TOOLS: All standard tools + Serena MCP + Context7 MCP

Begin working now.
"""


# =============================================================================
# Work-Stealing Queue Data Models
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


# =============================================================================
# Work-Stealing Queue
# =============================================================================

class WorkStealingQueue:
    """
    File-based work-stealing queue with atomic task claiming.

    Location: {project}/.claude/task-queue-{plan-id}.json or .md

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

    def mark_task_complete(self, task_id: str, agent_id: str) -> bool:
        """
        Mark a task as completed by a specific agent.

        Alias for complete_task() with agent validation.

        Args:
            task_id: ID of the task to complete.
            agent_id: ID of the agent completing the task.

        Returns:
            True if task was found and completed, False otherwise.
        """
        fd = self._acquire_lock()
        try:
            queue = self.load()

            for task in queue.tasks:
                if task.id == task_id:
                    # Validate agent ownership (warning only, still complete)
                    if task.claimed_by != agent_id:
                        pass  # Log warning if needed

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

    def add_task(self, task_id: str, description: str = "", blocked_by: list = None) -> QueueTask:
        """
        Add a new task to the queue.

        Args:
            task_id: Unique task identifier.
            description: Task description for markdown format.
            blocked_by: List of task IDs that must complete first.

        Returns:
            The created QueueTask.
        """
        fd = self._acquire_lock()
        try:
            queue = self.load()

            task = QueueTask(
                id=task_id,
                description=description,
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

    def reclaim_stale_tasks(self, timeout_seconds: int = 300) -> list:
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
# Convenience Functions
# =============================================================================

def claim_next_task(agent_id: str, plan_id: str, plan_file: str, base_dir: Optional[Path] = None) -> Optional[QueueTask]:
    """
    Atomic task claiming with file lock.

    Args:
        agent_id: ID of the agent claiming the task
        plan_id: Plan identifier for the queue
        plan_file: Path to the plan file
        base_dir: Base directory for queue files (default: current dir)

    Returns:
        Claimed QueueTask or None if no tasks available
    """
    queue = WorkStealingQueue(plan_id, plan_file, base_dir)
    return queue.claim_next_task(agent_id)


def release_task(task_id: str, plan_id: str, plan_file: str, base_dir: Optional[Path] = None) -> bool:
    """
    Release uncompleted task back to queue.

    Args:
        task_id: ID of the task to release
        plan_id: Plan identifier for the queue
        plan_file: Path to the plan file
        base_dir: Base directory for queue files (default: current dir)

    Returns:
        True if task was found and released
    """
    queue = WorkStealingQueue(plan_id, plan_file, base_dir)
    return queue.release_task(task_id)


def mark_task_complete(task_id: str, agent_id: str, plan_id: str, plan_file: str, base_dir: Optional[Path] = None) -> bool:
    """
    Mark task as done.

    Args:
        task_id: ID of the task to complete
        agent_id: ID of the agent completing the task
        plan_id: Plan identifier for the queue
        plan_file: Path to the plan file
        base_dir: Base directory for queue files (default: current dir)

    Returns:
        True if task was found and completed
    """
    queue = WorkStealingQueue(plan_id, plan_file, base_dir)
    return queue.mark_task_complete(task_id, agent_id)
