# Ralph State Files

This directory contains Ralph's state management system for autonomous development workflows.

## Directory Structure

```
.claude/ralph/
├── SCHEMAS.md                         # Schema documentation
├── state.py                          # Python helper functions
├── README.md                         # This file
├── *-example.json                    # Example files (reference)
├── task-queue-{plan-id}.json        # Task queue (runtime)
├── retry-queue-{plan-id}.json       # Retry queue (runtime)
├── progress-{plan-id}.json          # Progress tracking (runtime)
└── agent-state-{agent-id}.json      # Agent checkpoints (runtime)
```

## State Files

### Task Queue (`task-queue-{plan-id}.json`)
- Stores all tasks for a plan execution
- Uses atomic file locking for concurrent access
- Tracks task status: pending → claimed → done/failed
- Manages task dependencies

### Retry Queue (`retry-queue-{plan-id}.json`)
- Tracks failed tasks awaiting retry
- Max 3 retry attempts per task (configurable)
- Automatically cleared on successful retry

### Progress (`progress-{plan-id}.json`)
- Overall execution progress
- Performance metrics (cost, turns, duration)
- Budget tracking and enforcement
- Per-agent status and metrics

### Agent State (`agent-state-{agent-id}.json`)
- Per-agent checkpoint for crash recovery
- Tracks files modified, commits made
- Deleted on successful completion
- Used to resume interrupted agents

## Python Helper Functions

See `state.py` for full API. Key functions:

### Task Queue Operations
```python
from ralph.state import claim_task, complete_task, get_pending_tasks

# Claim next available task
task = claim_task("plan-id", "agent-1")

# Mark task as done
complete_task("plan-id", "t1", "done")

# Get all pending tasks
pending = get_pending_tasks("plan-id")
```

### Progress Tracking
```python
from ralph.state import create_progress, update_agent_progress, check_budget

# Initialize progress tracking
create_progress("plan-id", "implementation", agents_total=10, budget_limit_usd=5.0)

# Update agent progress
update_agent_progress("plan-id", "agent-1", "completed",
                     task_id="t1", cost_usd=0.12, num_turns=10)

# Check if budget exceeded
if not check_budget("plan-id"):
    print("Budget exceeded!")
```

### Retry Queue
```python
from ralph.state import add_retry, get_retryable_tasks, clear_retry

# Add failed task to retry queue
add_retry("plan-id", "t1", "agent-1", "Build failed: TypeScript error")

# Get tasks that can be retried
retryable = get_retryable_tasks("plan-id")

# Clear retry after success
clear_retry("plan-id", "t1")
```

### Agent State
```python
from ralph.state import create_agent_state, save_agent_state, delete_agent_state

# Create initial state
state = create_agent_state("agent-1", "plan-id", task_id="t1")

# Update state at checkpoint
state["context"]["files_modified"].append("src/auth.ts")
state["context"]["commits_made"].append("a3f9c2d")
save_agent_state("agent-1", state)

# Delete after completion
delete_agent_state("agent-1")
```

## File Locking

All state files use atomic file locking via `filelock`:

```bash
pip install filelock
```

Without filelock, operations are unsafe for concurrent access (fallback mode).

## Usage in Ralph Scripts

Example integration in `ralph.py`:

```python
from ralph.state import (
    create_task_queue, claim_task, complete_task,
    create_progress, update_agent_progress,
    create_agent_state, delete_agent_state
)

# Initialize state files
plan_id = "shimmering-sleeping-octopus"
tasks = [
    {"id": "t1", "description": "Implement auth", "status": "pending", ...},
    {"id": "t2", "description": "Add tests", "status": "pending", ...}
]

create_task_queue(plan_id, tasks)
create_progress(plan_id, "implementation", agents_total=3, budget_limit_usd=5.0)

# Agent claims task
task = claim_task(plan_id, "agent-1")
if task:
    create_agent_state("agent-1", plan_id, task_id=task["id"])

    # Agent works on task...

    # Mark complete
    complete_task(plan_id, task["id"], "done")
    update_agent_progress(plan_id, "agent-1", "completed",
                         cost_usd=0.12, num_turns=10, duration_seconds=420)
    delete_agent_state("agent-1")
```

## Testing

Run the test suite:

```bash
cd ~/.claude/ralph
python state.py
```

This creates test files in `.claude/ralph/` with prefix `test-plan`.

## Schema Documentation

See `SCHEMAS.md` for:
- Full TypeScript type definitions
- Field descriptions and constraints
- Status transition rules
- Validation requirements
- Example queries

## Dependencies

- Python 3.13+
- `filelock` (optional but recommended for concurrent access)

## Safety Features

- **Atomic writes**: Temp file + rename to prevent corruption
- **File locking**: Prevents race conditions during concurrent access
- **Budget enforcement**: Stops spawning agents when budget exceeded
- **Retry limits**: Max 3 attempts per task (configurable)
- **Crash recovery**: Agent state checkpoints enable resume
- **Dependency tracking**: Tasks respect dependencies before execution
