---
name: repotodo
description: Scan and process TODO comments in the codebase. Use /repotodo list to see all TODOs, /repotodo <priority> all to process all of a priority, /repotodo <priority> 1 to process one, or /repotodo verify to check alignment with review findings.
argument-hint: "[list|P1|P2|P3|low|all|verify]"
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

Use grep to find all TODO comments:

```bash
# Find priority TODOs (excluding vendor directories)
grep -rn "TODO-P[123]:\|TODO:" \
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
  .
```

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

Before processing a TODO, check if it's already being processed:

1. Lock file location: `$TEMP/claude-todo-locks/`
2. Lock file format: `{file_path_hash}_{line_number}.lock`
3. Lock contains: timestamp, CLI instance ID
4. Stale lock timeout: 1 hour

```bash
LOCK_DIR="$TEMP/claude-todo-locks"
mkdir -p "$LOCK_DIR"

LOCK_FILE="$LOCK_DIR/$(echo "$FILE:$LINE" | md5sum | cut -d' ' -f1).lock"

if [ -f "$LOCK_FILE" ]; then
  LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE")))
  if [ $LOCK_AGE -lt 3600 ]; then
    echo "TODO already being processed"
    # Skip to next TODO
  fi
fi

echo "$(date +%s):$$" > "$LOCK_FILE"
```

**Windows note:** `stat -c %Y` and `md5sum` are available via Git Bash. In PowerShell, use `(Get-Item $file).LastWriteTimeUtc` and `Get-FileHash -Algorithm MD5` instead.

### Phase 3: Process TODO

1. Read the file containing the TODO
2. Understand context (50 lines before and after)
3. Implement the requested change
4. Remove the TODO comment after completion
5. Release the lock

### Phase 4: VERIFY+FIX (Optional, with --verify flag)

After processing TODOs, run VERIFY+FIX agents to catch issues introduced during fixes:

**Trigger:** Only runs when `--verify` flag is specified

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
Phase 4: VERIFY+FIX agents (if --verify)
    ├─ Build check (pnpm build, tsc, cargo)
    ├─ Type check (tsc --noEmit, pyright)
    ├─ Lint check (biome check --write)
    ├─ Dead-code check (pnpm knip)
    ├─ Validate check (pnpm validate if exists)
    ├─ Serena symbol integrity
    ├─ Import verification
    └─ Auto-fix or AskUserQuestion for complex issues
    ↓
Phase 5: Cleanup + Report
```

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

1. **Use P1 sparingly** - Only for blocking/critical issues
2. **Default to P2** for most actionable items
3. **Use plain TODO** for ideas and future considerations
4. **Include context** in the TODO description
5. **Process P1s immediately** - Don't let critical items linger

## Important Notes

- Always read full context before implementing a TODO
- Run tests after implementing each TODO
- If unclear, ask for clarification instead of guessing
- Group related TODOs when processing multiple items
