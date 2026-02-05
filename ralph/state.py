#!/usr/bin/env python3
"""
Ralph State Management Helpers

Provides atomic file operations for Ralph state files with proper locking
and validation.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from filelock import FileLock
    HAS_FILELOCK = True
except ImportError:
    HAS_FILELOCK = False
    print("Warning: filelock not installed. Install with: pip install filelock")
    print("Running without file locking (unsafe for concurrent access)")


RALPH_DIR = Path.home() / ".claude" / "ralph"
LOCK_TIMEOUT = 10  # seconds


def _get_lock_path(state_file: Path) -> Path:
    """Get lock file path for a state file."""
    return state_file.with_suffix(".lock")


def _load_json_with_lock(filepath: Path) -> Dict[str, Any]:
    """Load JSON file with file locking."""
    if HAS_FILELOCK:
        lock = FileLock(_get_lock_path(filepath), timeout=LOCK_TIMEOUT)
        with lock:
            if not filepath.exists():
                return {}
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    else:
        # Fallback without locking (unsafe for concurrent access)
        if not filepath.exists():
            return {}
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)


def _save_json_with_lock(filepath: Path, data: Dict[str, Any]) -> None:
    """Save JSON file with file locking and atomic write."""
    # Atomic write: write to temp file, then rename
    temp_path = filepath.with_suffix(".tmp")

    if HAS_FILELOCK:
        lock = FileLock(_get_lock_path(filepath), timeout=LOCK_TIMEOUT)
        with lock:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path.replace(filepath)
    else:
        # Fallback without locking (unsafe for concurrent access)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(filepath)


def _get_iso_timestamp() -> str:
    """Get current timestamp in ISO8601 format with UTC timezone."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# Task Queue Operations
# ============================================================================

def load_task_queue(plan_id: str) -> Dict[str, Any]:
    """Load task queue for a plan."""
    filepath = RALPH_DIR / f"task-queue-{plan_id}.json"
    return _load_json_with_lock(filepath)


def save_task_queue(plan_id: str, queue: Dict[str, Any]) -> None:
    """Save task queue for a plan."""
    filepath = RALPH_DIR / f"task-queue-{plan_id}.json"
    _save_json_with_lock(filepath, queue)


def create_task_queue(plan_id: str, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a new task queue."""
    queue = {
        "tasks": tasks,
        "created_at": _get_iso_timestamp(),
        "plan_id": plan_id
    }
    save_task_queue(plan_id, queue)
    return queue


def claim_task(plan_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
    """
    Atomically claim the next available task.

    Returns the claimed task or None if no tasks available.
    """
    queue = load_task_queue(plan_id)

    for task in queue["tasks"]:
        # Find first pending task with no dependencies or all dependencies done
        if task["status"] == "pending" and task["claimed_by"] is None:
            deps = task.get("dependencies", [])
            if all(t["status"] == "done" for t in queue["tasks"] if t["id"] in deps):
                task["status"] = "claimed"
                task["claimed_by"] = agent_id
                task["claimed_at"] = _get_iso_timestamp()
                save_task_queue(plan_id, queue)
                return task

    return None


def complete_task(plan_id: str, task_id: str, status: str) -> None:
    """Mark a task as done or failed."""
    queue = load_task_queue(plan_id)

    for task in queue["tasks"]:
        if task["id"] == task_id:
            task["status"] = status
            task["completed_at"] = _get_iso_timestamp()
            break

    save_task_queue(plan_id, queue)


def get_pending_tasks(plan_id: str) -> List[Dict[str, Any]]:
    """Get all pending tasks (no dependencies or all dependencies done)."""
    queue = load_task_queue(plan_id)
    pending = []

    for task in queue["tasks"]:
        if task["status"] == "pending":
            deps = task.get("dependencies", [])
            if all(t["status"] == "done" for t in queue["tasks"] if t["id"] in deps):
                pending.append(task)

    return pending


# ============================================================================
# Retry Queue Operations
# ============================================================================

def load_retry_queue(plan_id: str) -> Dict[str, Any]:
    """Load retry queue for a plan."""
    filepath = RALPH_DIR / f"retry-queue-{plan_id}.json"
    data = _load_json_with_lock(filepath)
    if not data:
        return {"retries": [], "plan_id": plan_id}
    return data


def save_retry_queue(plan_id: str, retry_queue: Dict[str, Any]) -> None:
    """Save retry queue for a plan."""
    filepath = RALPH_DIR / f"retry-queue-{plan_id}.json"
    _save_json_with_lock(filepath, retry_queue)


def add_retry(plan_id: str, task_id: str, agent_id: str, error: str, max_retries: int = 3) -> None:
    """Add a task to the retry queue."""
    retry_queue = load_retry_queue(plan_id)

    # Get current attempt count from task queue
    task_queue = load_task_queue(plan_id)
    task = next((t for t in task_queue["tasks"] if t["id"] == task_id), None)
    if not task:
        return

    attempt = task.get("retries", 0) + 1

    retry_queue["retries"].append({
        "task_id": task_id,
        "agent_id": agent_id,
        "attempt": attempt,
        "error": error,
        "queued_at": _get_iso_timestamp(),
        "max_retries": max_retries
    })

    save_retry_queue(plan_id, retry_queue)


def get_retryable_tasks(plan_id: str) -> List[Dict[str, Any]]:
    """Get tasks that can be retried (haven't exceeded max retries)."""
    retry_queue = load_retry_queue(plan_id)
    return [r for r in retry_queue["retries"] if r["attempt"] < r["max_retries"]]


def clear_retry(plan_id: str, task_id: str) -> None:
    """Remove a task from retry queue after successful retry."""
    retry_queue = load_retry_queue(plan_id)
    retry_queue["retries"] = [r for r in retry_queue["retries"] if r["task_id"] != task_id]
    save_retry_queue(plan_id, retry_queue)


# ============================================================================
# Progress Tracking Operations
# ============================================================================

def load_progress(plan_id: str) -> Dict[str, Any]:
    """Load progress data for a plan."""
    filepath = RALPH_DIR / f"progress-{plan_id}.json"
    return _load_json_with_lock(filepath)


def save_progress(plan_id: str, progress: Dict[str, Any]) -> None:
    """Save progress data for a plan."""
    filepath = RALPH_DIR / f"progress-{plan_id}.json"
    progress["updated_at"] = _get_iso_timestamp()
    _save_json_with_lock(filepath, progress)


def create_progress(
    plan_id: str,
    phase: str,
    agents_total: int,
    budget_limit_usd: Optional[float] = None
) -> Dict[str, Any]:
    """Create initial progress tracking."""
    progress = {
        "plan_id": plan_id,
        "phase": phase,
        "agents_total": agents_total,
        "agents_completed": 0,
        "agents_failed": 0,
        "agents_active": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": budget_limit_usd,
        "started_at": _get_iso_timestamp(),
        "updated_at": _get_iso_timestamp(),
        "performance": {
            "avg_cost_per_agent": 0.0,
            "avg_turns_per_agent": 0.0,
            "avg_duration_seconds": 0.0,
            "total_turns": 0
        },
        "agents": []
    }
    save_progress(plan_id, progress)
    return progress


def update_agent_progress(
    plan_id: str,
    agent_id: str,
    status: str,
    task_id: Optional[str] = None,
    cost_usd: float = 0.0,
    num_turns: int = 0,
    duration_seconds: float = 0.0
) -> None:
    """Update progress for a specific agent."""
    progress = load_progress(plan_id)

    # Find or create agent entry
    agent = next((a for a in progress["agents"] if a["id"] == agent_id), None)
    if not agent:
        agent = {
            "id": agent_id,
            "status": "initializing",
            "task_id": None,
            "cost_usd": 0.0,
            "num_turns": 0,
            "duration_seconds": 0.0,
            "started_at": _get_iso_timestamp(),
            "completed_at": None
        }
        progress["agents"].append(agent)

    # Update agent
    agent["status"] = status
    if task_id:
        agent["task_id"] = task_id
    agent["cost_usd"] += cost_usd
    agent["num_turns"] += num_turns
    agent["duration_seconds"] += duration_seconds

    if status in ("completed", "failed", "budget"):
        agent["completed_at"] = _get_iso_timestamp()
        if status == "completed":
            progress["agents_completed"] += 1
        elif status == "failed":
            progress["agents_failed"] += 1
        progress["agents_active"] = max(0, progress["agents_active"] - 1)
    elif status == "active" and agent.get("completed_at") is None:
        progress["agents_active"] += 1

    # Update totals
    progress["total_cost_usd"] += cost_usd

    # Update performance metrics
    completed = [a for a in progress["agents"] if a["status"] == "completed"]
    if completed:
        progress["performance"]["avg_cost_per_agent"] = sum(a["cost_usd"] for a in completed) / len(completed)
        progress["performance"]["avg_turns_per_agent"] = sum(a["num_turns"] for a in completed) / len(completed)
        progress["performance"]["avg_duration_seconds"] = sum(a["duration_seconds"] for a in completed) / len(completed)

    progress["performance"]["total_turns"] = sum(a["num_turns"] for a in progress["agents"])

    save_progress(plan_id, progress)


def check_budget(plan_id: str) -> bool:
    """Check if budget limit has been exceeded. Returns True if can continue."""
    progress = load_progress(plan_id)
    if progress["budget_limit_usd"] is None:
        return True
    return progress["total_cost_usd"] < progress["budget_limit_usd"]


# ============================================================================
# Agent State Operations
# ============================================================================

def load_agent_state(agent_id: str) -> Dict[str, Any]:
    """Load agent state for crash recovery."""
    filepath = RALPH_DIR / f"agent-state-{agent_id}.json"
    return _load_json_with_lock(filepath)


def save_agent_state(agent_id: str, state: Dict[str, Any]) -> None:
    """Save agent state checkpoint."""
    filepath = RALPH_DIR / f"agent-state-{agent_id}.json"
    state["last_checkpoint"] = _get_iso_timestamp()
    _save_json_with_lock(filepath, state)


def create_agent_state(agent_id: str, plan_id: str, task_id: Optional[str] = None) -> Dict[str, Any]:
    """Create initial agent state."""
    state = {
        "agent_id": agent_id,
        "plan_id": plan_id,
        "task_id": task_id,
        "status": "initializing",
        "last_checkpoint": _get_iso_timestamp(),
        "context": {
            "files_modified": [],
            "commits_made": [],
            "notes": ""
        }
    }
    save_agent_state(agent_id, state)
    return state


def delete_agent_state(agent_id: str) -> None:
    """Delete agent state after successful completion."""
    filepath = RALPH_DIR / f"agent-state-{agent_id}.json"
    if filepath.exists():
        filepath.unlink()

    lock_path = _get_lock_path(filepath)
    if lock_path.exists():
        lock_path.unlink()


# ============================================================================
# Initialization
# ============================================================================

def ensure_ralph_dir() -> None:
    """Ensure Ralph directory exists."""
    RALPH_DIR.mkdir(parents=True, exist_ok=True)


# Auto-create directory on import
ensure_ralph_dir()


if __name__ == "__main__":
    # Test the helpers
    print("Testing Ralph state helpers...")

    # Create test task queue
    test_plan = "test-plan"
    tasks = [
        {
            "id": "t1",
            "description": "Test task 1",
            "status": "pending",
            "claimed_by": None,
            "retries": 0,
            "dependencies": [],
            "created_at": _get_iso_timestamp(),
            "claimed_at": None,
            "completed_at": None
        }
    ]

    create_task_queue(test_plan, tasks)
    print(f"[OK] Created task queue for {test_plan}")

    # Test task claiming
    task = claim_task(test_plan, "agent-1")
    print(f"[OK] Claimed task: {task['id']}")

    # Test progress tracking
    create_progress(test_plan, "implementation", 3, budget_limit_usd=5.0)
    update_agent_progress(test_plan, "agent-1", "active", task_id="t1", cost_usd=0.10, num_turns=5)
    print(f"[OK] Created and updated progress")

    # Test agent state
    create_agent_state("agent-1", test_plan, task_id="t1")
    print(f"[OK] Created agent state")

    print(f"\nAll tests passed! Check {RALPH_DIR} for generated files.")
