---
name: repotodo
description: Scan and process TODO comments by priority (P1/P2/P3/low)
argument-hint: "[list|P1|P2|P3|low|all|verify|help]"
user-invocable: true
---

# Repo TODO Manager

**When invoked, immediately output:** `**SKILL_STARTED:** repotodo`

## Purpose

Scan the codebase for TODO comments and process them by priority.

## TODO Comment Format

TODOs use a simple priority-based format:

| Format      | Priority | Description                              |
|-------------|----------|------------------------------------------|
| `TODO-P1:`  | Critical | Blocking issues, security fixes, crashes |
| `TODO-P2:`  | High     | Important features, significant bugs     |
| `TODO-P3:`  | Medium   | Nice-to-have, minor improvements         |
| `TODO:`     | Low      | General notes, future considerations     |

**Examples:**
```typescript
// TODO-P1: Fix authentication bypass vulnerability
// TODO-P2: Add input validation for user forms
// TODO-P3: Refactor to reduce code duplication
// TODO: Consider adding dark mode support
```

## Commands

### `/repotodo help`

Show usage information:

```
/repotodo - Scan and process TODO comments by priority

Usage:
  /repotodo [command] [args]

Commands:
  list              List all TODOs by priority
  P1 all            Process all P1 (critical) TODOs
  P1 all --verify   Process all P1 TODOs + VERIFY+FIX agents
  P1 <N>            Process N P1 TODOs
  P2 all            Process all P2 (high) TODOs
  P2 all --verify   Process all P2 TODOs + VERIFY+FIX agents
  P2 <N>            Process N P2 TODOs
  P3 all            Process all P3 (medium) TODOs
  P3 all --verify   Process all P3 TODOs + VERIFY+FIX agents
  P3 <N>            Process N P3 TODOs
  low all           Process all low-priority TODOs (plain TODO:)
  low all --verify  Process all low TODOs + VERIFY+FIX agents
  low <N>           Process N low-priority TODOs
  all               Process ALL TODOs (starts with P1)
  all --verify      Process ALL TODOs + VERIFY+FIX agents
  verify            Check alignment between review findings and source TODOs
  verify --fix      Inject missing TODOs from review findings into source
  help              Show this help

Examples:
  /repotodo list
  /repotodo P1 all
  /repotodo P1 all --verify
  /repotodo P2 1
  /repotodo all --verify
  /repotodo verify
  /repotodo verify --fix
```

### `/repotodo list`

Lists all TODOs grouped by priority.

**Output format:**
```
## TODO Summary

| Priority | Count | Description              |
|----------|-------|--------------------------|
| P1       | 2     | Critical - fix first     |
| P2       | 5     | High priority            |
| P3       | 8     | Medium priority          |
| low      | 12    | General TODOs            |

### P1 - Critical (2)
- `src/auth.ts:45` - Fix authentication bypass vulnerability
- `lib/db.ts:123` - Prevent SQL injection

### P2 - High (5)
...
```

### `/repotodo <priority> all`

Process ALL TODOs of the specified priority.

Example: `/repotodo P1 all` - Fix all critical TODOs

### `/repotodo <priority> all --verify`

Process ALL TODOs of the specified priority, then run VERIFY+FIX agents.

Example: `/repotodo P1 all --verify` - Fix all critical TODOs + verification

### `/repotodo <priority> <N>`

Process N TODOs of the specified priority.

Example: `/repotodo P2 1` - Process one high-priority TODO

### `/repotodo all`

Process all TODOs in priority order (P1 → P2 → P3 → low).

### `/repotodo all --verify`

Process all TODOs in priority order, then run VERIFY+FIX agents.

Example: `/repotodo all --verify` - Fix all TODOs + verification

### `/repotodo verify`

Verify alignment between review findings in `.claude/review-agents.md` and TODO comments in source code.

**Steps:**

1. **Read review findings:** Parse `.claude/review-agents.md` for all findings (file paths, severity, descriptions)
2. **Scan source TODOs:** Grep codebase for `TODO-P1:`, `TODO-P2:`, `TODO-P3:` comments
3. **Cross-reference:** Match review findings to source TODOs by file path and description similarity
4. **Report alignment:**

**Output format:**
```
## TODO Verification Report

### Summary
- X findings have matching source TODOs
- Y findings are MISSING source TODOs (need injection)
- Z source TODOs have no matching finding (orphaned)

### Matched Findings (X)
| Finding | Source TODO | File | Priority |
|---------|------------|------|----------|
| Auth bypass vulnerability | TODO-P1: Fix auth bypass | src/auth.ts:45 | P1 |

### Missing TODOs (Y) — findings with no source TODO
| Finding | File | Suggested Priority | Action Needed |
|---------|------|--------------------|---------------|
| SQL injection risk | lib/db.ts:89 | P1 | Insert TODO |

### Orphaned TODOs (Z) — source TODOs with no matching finding
| Source TODO | File | Priority | Status |
|-------------|------|----------|--------|
| TODO-P2: Refactor auth module | src/auth.ts:102 | P2 | No matching finding |
```

**Matching logic:**
- Match by file path: finding references same file as TODO
- Match by description: fuzzy match between finding description and TODO text
- Match by line proximity: finding and TODO within 10 lines of each other
- Priority mapping: finding severity maps to TODO priority (Critical→P1, High→P2, Medium→P3)

### `/repotodo verify --fix`

Same as `verify` but also injects missing TODOs into source files for unmatched findings.

**Steps:**

1. Run the standard `verify` analysis
2. For each finding that has NO matching source TODO:
   - Determine the target file and line from the finding
   - Map finding severity to TODO priority (Critical→P1, High→P2, Medium→P3)
   - Insert a TODO comment at the appropriate location in the source file
   - Format: `// TODO-P{N}: {description} - Review: {agent-id}`
3. Report what was injected

**Output format (appended to verify report):**
```
### Injected TODOs (N)
| File | Line | Priority | TODO Text |
|------|------|----------|-----------|
| src/auth.ts:89 | 89 | P1 | TODO-P1: Fix SQL injection - Review: agent-3 |
```

**Safety:**
- Never overwrites existing TODOs
- Skips injection if a similar TODO already exists within 5 lines
- Uses `scripts/post-review.py` for the actual injection when available
- Dry-run output shown before any file modifications

## Workflow

### Phase 1: Scan TODOs

Use grep to find all TODO comments with proper escaping and timeout:

```bash
# Find priority TODOs (excluding vendor directories) with 60s timeout
timeout 60 grep -rn "TODO-P\[123\]:\|TODO:" \
  --include="*.ts" --include="*.tsx" \
  --include="*.js" --include="*.jsx" \
  --include="*.py" --include="*.md" \
  --include="*.go" --include="*.rs" \
  --include="*.java" --include="*.kt" \
  --exclude-dir=node_modules \
  --exclude-dir=.venv \
  --exclude-dir=venv \
  --exclude-dir=vendor \
  --exclude-dir=dist \
  --exclude-dir=build \
  --exclude-dir=.git \
  --exclude-dir=.claude \
  --exclude-dir=__pycache__ \
  --exclude-dir=.next \
  --exclude-dir=target \
  . 2>/dev/null || {
    if [ $? -eq 124 ]; then
        echo "Error: TODO scan timed out after 60s (codebase too large)"
        echo "Consider scanning a specific directory instead"
        exit 1
    fi
}
```

**Pattern escaping:** `TODO-P\[123\]` uses `\[` and `\]` to escape square brackets in the regex pattern. Without escaping, grep would interpret `[123]` as a character class (match any single digit 1, 2, or 3) instead of the literal string `[123]`. The backslashes ensure we match the exact TODO format: `TODO-P1:`, `TODO-P2:`, `TODO-P3:`.

**Timeout protection:** Grep times out after 60 seconds to prevent hanging on massive codebases. If timeout occurs, suggest scanning a specific directory with a more targeted pattern (e.g., `grep -rn "TODO-P1:" src/` instead of searching the entire project).

**Common excludes:** Added `.git`, `.claude`, `__pycache__`, `.next`, and `target` to exclude directories that should never contain actionable TODOs.

Parse results into structured format:
- File path
- Line number
- Priority (P1, P2, P3, or low)
- Description

**Priority Classification:**
- `TODO-P1:` → P1 (critical)
- `TODO-P2:` → P2 (high)
- `TODO-P3:` → P3 (medium)
- `TODO:` (without priority) → low

### Phase 2: Lock Check (for concurrent safety)

Before processing a TODO, check if it's already being processed to prevent multiple Claude instances or agents from working on the same item simultaneously.

**Lock mechanism:**
1. Lock file location: `$TEMP/claude-todo-locks/` (uses system temp directory)
2. Lock file format: `{file_path_hash}_{line_number}.lock` (hash prevents path traversal)
3. Lock contains: timestamp (epoch seconds) and CLI instance PID (e.g., `1706012345:12345`)
4. Stale lock timeout: 1 hour (3600 seconds) - locks older than this are considered abandoned

**Example:** For `src/auth.ts:42`, create lock file `a1b2c3d4e5f6_42.lock` in `$TEMP/claude-todo-locks/`

```bash
LOCK_DIR="$TEMP/claude-todo-locks"
mkdir -p "$LOCK_DIR"

# Hash the file path to create a safe filename (prevents issues with special chars)
LOCK_FILE="$LOCK_DIR/$(echo "$FILE:$LINE" | md5sum | cut -d' ' -f1).lock"

if [ -f "$LOCK_FILE" ]; then
  # Check lock age (seconds since last modified)
  LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE")))
  if [ $LOCK_AGE -lt 3600 ]; then
    echo "TODO already being processed by another instance (lock age: ${LOCK_AGE}s)"
    # Skip to next TODO
  fi
fi

# Create lock with timestamp and process ID
echo "$(date +%s):$$" > "$LOCK_FILE"
```

**Windows compatibility:**
- `stat -c %Y` (Git Bash) → `(Get-Item $file).LastWriteTimeUtc.ToFileTimeUtc()` (PowerShell)
- `md5sum` (Git Bash) → `(Get-FileHash -Algorithm MD5 $file).Hash` (PowerShell)
- `date +%s` (Git Bash) → `[int][double]::Parse((Get-Date -UFormat %s))` (PowerShell)

**Why lock checks matter:** Without locking, parallel agents could duplicate work or create merge conflicts when fixing the same TODO.

### Phase 3: Process TODO

1. Read the file containing the TODO
2. Understand context (50 lines before and after)
3. Implement the requested change
4. Remove the TODO comment after completion
5. Release the lock

### Phase 4: VERIFY+FIX (Optional, with --verify flag)

After processing TODOs, run VERIFY+FIX agents to catch issues introduced during fixes.

**Trigger:** Only runs when `--verify` flag is specified

**Agent Configuration:**
- **Agent count:** 2 VERIFY+FIX agents (default)
- **Iterations:** 2 per agent (default)
- **Model:** Opus 4.6
- **Full specification:** See `agents/verify-fix.md` for complete agent behavior and criteria

**VERIFY+FIX Workflow:**

```
/repotodo P1 all --verify
    ↓
Phase 1: Scan TODOs
    ↓
Phase 2: Lock Check
    ↓
Phase 3: Process each TODO (main context)
    ↓
Phase 4: VERIFY+FIX agents (2 agents, 2 iterations)
    ├─ Build check (timeout: 10min) - pnpm build, tsc, cargo
    ├─ Type check (timeout: 5min) - tsc --noEmit, pyright
    ├─ Lint check (timeout: 3min) - biome check --write
    ├─ Dead-code check (timeout: 5min) - pnpm knip
    ├─ Validate check (timeout: 10min) - pnpm validate if exists
    ├─ Symbol integrity check (no timeout - fast)
    ├─ Import verification (no timeout - fast)
    └─ Auto-fix or AskUserQuestion for complex issues
    ↓
Phase 5: Cleanup + Report
```

**Timeout specifications and rationale:**
- **Build (10min):** Large projects with many dependencies can take 5-10min for cold builds. Includes bundling, minification, and optimization.
- **Type check (5min):** TypeScript compiler must traverse entire codebase and dependency type definitions. Expensive on monorepos with 100k+ lines.
- **Lint (3min):** Biome is fast but still needs to parse and analyze all files. 3min accounts for large codebases and plugin overhead.
- **Dead-code (5min):** Knip analyzes the entire dependency graph, checking imports/exports across all files. Graph traversal is O(n²) in worst case.
- **Validate (10min):** Runs all checks sequentially (build + test + lint + type + dead-code). Sum of individual timeouts.

**Timeout behavior:** If any check times out, the agent:
1. Reports the timeout with the specific check name
2. Shows partial output captured before timeout
3. Asks user: "Check timed out after Xmin. Proceed with remaining checks or abort? (proceed/abort)"
4. If "proceed": continues to next check but marks timed-out check as ⚠️ WARNING in final report
5. If "abort": stops VERIFY+FIX phase and returns to user

**VERIFY+FIX Agent Behavior:**
- Reuses `agents/verify-fix.md` configuration
- Auto-fixes simple issues (imports, types, formatting)
- Escalates complex issues via AskUserQuestion
- NEVER leaves new TODO comments - fix or escalate
- Uses Opus model for verification

**Example Commands:**

```bash
/repotodo P1 all           # Process P1 TODOs (no verify)
/repotodo P1 all --verify  # Process P1 TODOs + VERIFY+FIX agents
/repotodo all --verify     # Process ALL TODOs + VERIFY+FIX agents
```

### Phase 5: Cleanup

After completing a TODO:
1. Remove the TODO comment from the source file
2. Delete the lock file
3. Report completion

## Review Log Integration

When `/repotodo` finishes processing, it cleans up `.claude/review-agents.md`:

1. Check if TODO comments still exist in source files
2. Remove completed TODO rows from tracking tables
3. Update `Total TODOs` count
4. Archive file when all TODOs are complete

## Best Practices

1. **Use P1 sparingly** - Only for blocking/critical issues (security bugs, crashes, data loss risks). Example: `// TODO-P1: SQL injection in login query`
2. **Default to P2** for most actionable items - Bugs, performance issues, missing error handling. Example: `// TODO-P2: Add timeout to API call`
3. **Use plain TODO** for ideas and future considerations - Nice-to-haves, refactoring suggestions. Example: `// TODO: Consider memoizing this calculation`
4. **Include context** in the TODO description - Explain WHY it needs to be done, not just WHAT. Bad: `// TODO-P2: Fix this` Good: `// TODO-P2: Race condition when user spams submit button`
5. **Process P1s immediately** - Don't let critical items linger. Run `/repotodo P1 all` daily or before each release.
6. **Group related TODOs** - If fixing one TODO requires changes to multiple files, use the same priority and similar descriptions so they're processed together.
7. **Remove on completion** - The /repotodo workflow automatically removes TODO comments after fixing them. Don't leave "DONE" TODOs in code.

## Important Notes

- Always read full context before implementing a TODO
- Run tests after implementing each TODO
- If unclear, ask for clarification instead of guessing
- Group related TODOs when processing multiple items
