# Start Import Sub-Skill

Import tasks from external sources and initialize a Ralph loop with customizable agent/iteration counts.

## Usage

```
/start import help                                         - Show this help
/start import ./docs/PRD.md                                - 3 agents, 3 iterations, import from PRD
/start 5 import ./tasks.yaml                               - 5 agents, 3 iterations, import from YAML
/start 5 10 import https://github.com/owner/repo/issues/1  - 5 agents, 10 iterations, import from GitHub Issue
/start 3 20 import https://github.com/owner/repo/pull/123  - 3 agents, 20 iterations, import from PR description
```

## Argument Parsing

From `$ARGUMENTS`, when `import` keyword is detected:

1. **Numbers before `import`** = Agent count and iteration count (same rules as `/start`)
2. **Text after `import`** = Source path or URL

**Examples:**
| Command | Agents | Iterations | Source |
|---------|--------|------------|--------|
| `/start import ./PRD.md` | 3 | 3 | Local Markdown PRD |
| `/start 5 import ./tasks.yaml` | 5 | 3 | YAML task definition |
| `/start 5 10 import https://github.com/o/r/issues/1` | 5 | 10 | GitHub Issue |
| `/start 3 20 import https://github.com/o/r/pull/42` | 3 | 20 | GitHub PR |

## Source Routing

| Source Pattern | Action |
|----------------|--------|
| `help` | Show usage help |
| `*.md` file path | Parse Markdown PRD |
| `*.yaml` or `*.yml` file path | Parse YAML task definition |
| GitHub Issue URL (`/issues/`) | Fetch and parse GitHub Issue |
| GitHub PR URL (`/pull/`) | Fetch and parse PR description |

---

## Action: Show Help

When source is `help`:

Display this usage information:

```
Start Import - Import tasks into a Ralph loop

Usage:
  /start import <source>
  /start [agents] import <source>
  /start [agents] [iterations] import <source>

Sources:
  ./path/to/PRD.md          Local Markdown PRD file
  ./path/to/tasks.yaml      YAML task definition
  github.com/.../issues/N   GitHub Issue (extracts body + comments)
  github.com/.../pull/N     GitHub PR (extracts description)

Examples:
  /start import ./docs/feature-spec.md
  /start 5 import ./tasks.yaml
  /start 5 10 import https://github.com/owner/repo/issues/42

After import:
  - Tasks are created via TaskCreate from requirements
  - Ralph loop is initialized with extracted task
  - Loop starts automatically with specified agents/iterations
```

---

## Action: Import from Markdown PRD

When source ends with `.md`:

### 1. Read the File

```bash
cat "[SOURCE_PATH]"
```

### 2. Extract Requirements

Parse the Markdown looking for:
- Headings with "Requirements", "Tasks", "Goals", "Features"
- Checklist items `- [ ]` or `- [x]`
- Numbered lists under relevant headings
- User stories (`As a...`, `I want...`, `So that...`)

### 3. Generate Tasks via TaskCreate

Convert extracted requirements to tasks:

```
TaskCreate({
  subject: "[Requirement 1]",
  description: "[Detailed description from PRD]",
  activeForm: "[Active form]"
})

TaskCreate({
  subject: "[Requirement 2]",
  description: "[Detailed description from PRD]",
  activeForm: "[Active form]"
})

// ... for each requirement

TaskCreate({
  subject: "Run validation (pnpm validate)",
  description: "Execute full validation suite to ensure all changes pass lint, type check, and tests",
  activeForm: "Running validation"
})

TaskCreate({
  subject: "Verify completion",
  description: "Self-verify all requirements are met and implementation is complete",
  activeForm: "Verifying completion"
})
```

### 4. Create Ralph State Files

```bash
mkdir -p .claude/ralph && cat > .claude/ralph/loop.local.md <<'RALPH_EOF'
---
active: true
iteration: 1
max_iterations: [ITERATIONS]
completion_promise: "RALPH_COMPLETE"
agents: [AGENTS]
---

## Imported from: [FILENAME]

[FULL_PRD_CONTENT]

## Checklist
- [ ] [Requirement 1]
- [ ] [Requirement 2]
...
RALPH_EOF
```

### 5. Initialize State JSON

```bash
cat > .claude/ralph/state.json <<'STATE_EOF'
{
  "iteration": 1,
  "maxIterations": [ITERATIONS],
  "agents": [AGENTS],
  "startedAt": "[ISO_TIMESTAMP]",
  "task": "Imported from [FILENAME]: [SUMMARY]",
  "stuckDetection": {
    "consecutiveErrors": [],
    "lastCompletedTodo": null,
    "iterationsSinceProgress": 0,
    "buildErrors": []
  },
  "activityLog": []
}
STATE_EOF
```

### 6. Confirm and Start

Output confirmation:
```
Start Import Complete!

Source: [FILENAME]
Requirements extracted: [COUNT]
Agents: [AGENTS]
Max iterations: [ITERATIONS]

Starting Ralph loop...
```

Then spawn parallel Task agents to begin work.

---

## Action: Import from YAML

When source ends with `.yaml` or `.yml`:

### Expected YAML Format

```yaml
name: Feature Implementation
description: Build the authentication system
agents: 5        # Optional, can be overridden by /start args
iterations: 20   # Optional, can be overridden by /start args
tasks:
  - Implement login endpoint
  - Add JWT token generation
  - Create refresh token logic
  - Add password hashing
  - Write integration tests
```

### 1. Read and Parse YAML

```bash
cat "[SOURCE_PATH]"
```

Extract:
- `name` -> Task title
- `description` -> Full task description
- `agents` -> Number of agents (default: 3, overridden by /start args if provided)
- `iterations` -> Max iterations (default: 3, overridden by /start args if provided)
- `tasks` -> List of task items

### 2. Generate Tasks and Ralph State

Same as Markdown import, using extracted values. Command-line agent/iteration counts take precedence over YAML values.

---

## Action: Import from GitHub Issue

When source contains `github.com` and `issues`:

### 1. Fetch Issue Data

```bash
gh issue view [NUMBER] --repo [OWNER/REPO] --json title,body,comments
```

### 2. Extract Content

- **Title** -> Task summary
- **Body** -> Full requirements (parse for checklists, user stories)
- **Comments** -> Additional context (look for clarifications, decisions)

### 3. Generate Tasks via TaskCreate

Parse issue body for:
- Markdown checklists `- [ ]`
- Numbered requirements
- Acceptance criteria sections

Create a TaskCreate for each extracted requirement.

### 4. Create Ralph State

Include issue URL in task description for reference.

---

## Action: Import from GitHub PR

When source contains `github.com` and `pull`:

### 1. Fetch PR Data

```bash
gh pr view [NUMBER] --repo [OWNER/REPO] --json title,body,files
```

### 2. Extract Content

- **Title** -> Task summary
- **Body** -> Requirements, test plan
- **Files** -> Context for which areas to work on

### 3. Generate Tasks via TaskCreate

Focus on:
- Incomplete items from PR checklist
- Requested changes from reviews
- Test plan items

---

## Configuration Precedence

| Setting | Source Priority |
|---------|-----------------|
| Agents | /start arg > YAML > default (3) |
| Iterations | /start arg > YAML > default (3) |

**Default values:**
| Setting | Default | Notes |
|---------|---------|-------|
| Agents | 3 | Standard Ralph default |
| Iterations | 3 | Standard Ralph default |
| Completion | Multi-signal | Requires promise + EXIT_SIGNAL |

## Safety Rules

- **Always confirm** before starting Ralph loop
- **Show extracted requirements** for user verification
- **Preserve original source** in `.claude/ralph/loop.local.md` for reference
- **Don't modify source files** - only read and extract

## Integration with Ralph

After import completes:
1. Tasks are created via TaskCreate
2. `.claude/ralph/loop.local.md` is created
3. `.claude/ralph/state.json` is initialized
4. Stop hook will intercept exits and continue loop
5. Multi-signal exit detection is active (promise + EXIT_SIGNAL required)

## Completion Protocol

Same as standard Ralph Mode - output BOTH when all conditions are met:

```
<promise>RALPH_COMPLETE</promise>
EXIT_SIGNAL: true
```
