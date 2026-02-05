# Ralph State File Schemas

This document defines the JSON schemas used by Ralph for state management.

## task-queue.json

Stores the task queue for a specific plan execution.

**Schema:**
```typescript
{
  "tasks": Array<{
    "id": string,              // Unique task identifier (e.g., "t1", "t2")
    "description": string,     // Human-readable task description
    "status": "pending" | "claimed" | "done" | "failed",
    "claimed_by": string | null, // Agent ID that claimed this task
    "retries": number,         // Number of retry attempts (0 = first try)
    "dependencies": string[],  // Task IDs that must complete first
    "created_at": string,      // ISO8601 timestamp
    "claimed_at": string | null, // ISO8601 timestamp when claimed
    "completed_at": string | null // ISO8601 timestamp when completed/failed
  }>,
  "created_at": string,        // ISO8601 timestamp
  "plan_id": string            // Plan identifier from plan filename
}
```

**File location:** `.claude/ralph/task-queue-{plan-id}.json`

**Lifecycle:**
- Created when Ralph starts
- Updated atomically with file locks during task claiming
- Archived after plan completion

## retry-queue.json

Tracks failed tasks that need to be retried.

**Schema:**
```typescript
{
  "retries": Array<{
    "task_id": string,         // Reference to task in task-queue.json
    "agent_id": string,        // Agent that failed the task
    "attempt": number,         // Retry attempt number (1-indexed)
    "error": string,           // Error message from failure
    "queued_at": string,       // ISO8601 timestamp
    "max_retries": number      // Maximum retry attempts (default: 3)
  }>,
  "plan_id": string            // Plan identifier
}
```

**File location:** `.claude/ralph/retry-queue-{plan-id}.json`

**Lifecycle:**
- Created on first task failure
- Cleared after successful retry or max retries exceeded
- Tasks return to task-queue with updated retry count

## progress.json

Tracks overall execution progress and performance metrics.

**Schema:**
```typescript
{
  "plan_id": string,           // Plan identifier
  "phase": "implementation" | "verify_fix" | "review",
  "agents_total": number,      // Total agents to spawn
  "agents_completed": number,  // Successfully completed agents
  "agents_failed": number,     // Failed agents (after max retries)
  "agents_active": number,     // Currently running agents
  "total_cost_usd": number,    // Cumulative API cost
  "budget_limit_usd": number | null, // Budget cap (null = unlimited)
  "started_at": string,        // ISO8601 timestamp
  "updated_at": string,        // ISO8601 timestamp
  "performance": {
    "avg_cost_per_agent": number,
    "avg_turns_per_agent": number,
    "avg_duration_seconds": number,
    "total_turns": number
  },
  "agents": Array<{
    "id": string,              // Agent identifier
    "status": "active" | "completed" | "failed" | "budget",
    "task_id": string | null,  // Current/last task
    "cost_usd": number,
    "num_turns": number,
    "duration_seconds": number,
    "started_at": string,
    "completed_at": string | null
  }>
}
```

**File location:** `.claude/ralph/progress-{plan-id}.json`

**Lifecycle:**
- Created at session start
- Updated after each agent completion
- Used for budget tracking and performance reporting

## agent-state.json

Stores per-agent state for crash recovery.

**Schema:**
```typescript
{
  "agent_id": string,
  "plan_id": string,
  "task_id": string | null,
  "status": "initializing" | "working" | "completed" | "failed",
  "last_checkpoint": string,   // ISO8601 timestamp
  "context": {
    "files_modified": string[],
    "commits_made": string[],   // Commit SHAs
    "notes": string             // Agent notes/progress
  }
}
```

**File location:** `.claude/ralph/agent-state-{agent-id}.json`

**Lifecycle:**
- Created when agent starts
- Updated at checkpoints (pre/post tool use)
- Deleted on successful completion
- Used for recovery if agent crashes

## File Locking

All state files use atomic file locking to prevent race conditions:

```python
from filelock import FileLock

lock = FileLock(".claude/ralph/task-queue.lock")
with lock:
    # Read, modify, write task queue
    pass
```

## Validation Rules

1. **Task IDs** must be unique within a plan
2. **Agent IDs** follow format: `agent-{N}` (e.g., "agent-1", "agent-2")
3. **Timestamps** must be ISO8601 format with timezone
4. **Status transitions** must follow state machine:
   - Task: pending → claimed → (done|failed)
   - Agent: initializing → working → (completed|failed|budget)
5. **Budget limits** enforced before agent spawn
6. **Retry limits** max 3 attempts per task (configurable)

## Example Queries

### Check available tasks
```python
queue = load_task_queue(plan_id)
available = [t for t in queue["tasks"]
             if t["status"] == "pending"
             and not t["dependencies"]]
```

### Calculate budget remaining
```python
progress = load_progress(plan_id)
if progress["budget_limit_usd"]:
    remaining = progress["budget_limit_usd"] - progress["total_cost_usd"]
else:
    remaining = float('inf')
```

### Find failed tasks for retry
```python
retry_queue = load_retry_queue(plan_id)
retryable = [r for r in retry_queue["retries"]
             if r["attempt"] < r["max_retries"]]
```
