---
name: repotodo
description: Scan and process TODO comments in the codebase. Use /repotodo list to see all TODOs, /repotodo <category> all to process all of a type, or /repotodo <category> 1 to process one.
user-invocable: true
context: fork
---

# Repo TODO Manager

**When invoked, immediately output:** `**SKILL_STARTED:** repotodo`

## Purpose

Scan the codebase for TODO comments marked with categories and process them systematically.

## TODO Comment Format

TODOs should be marked as: `// TODO-<category>: description`

### Supported Categories
| Category   | Description |
|------------|-------------|
| feat       | A new feature |
| fix        | A bug fix |
| docs       | Documentation changes |
| style      | Code style changes (formatting, semicolons, etc.) |
| refactor   | Code refactoring (neither fixes a bug nor adds a feature) |
| test       | Adding or updating tests |
| chore      | Routine tasks like updating dependencies or build tools |
| build      | Changes affecting the build system or external dependencies |
| ci         | Changes to CI configuration files or scripts |
| perf       | Performance improvements |
| revert     | Reverting a previous commit |

## Commands

### `/repotodo help`

Show usage information:

```
/repotodo - Scan and process TODO comments in the codebase

Usage:
  /repotodo [command] [args]

Commands:
  list              List all TODOs by category
  <category> all    Process all TODOs of a category
  <category> <N>    Process N TODOs of a category
  help              Show this help

Categories: feat, fix, docs, style, refactor, test, chore, build, ci, perf, revert

Examples:
  /repotodo list
  /repotodo fix all
  /repotodo feat 1
```

### `/repotodo list`
Lists all TODOs in the codebase grouped by category.

**Output format:**
```
| Category | Count |
|----------|-------|
| feat     | 5     |
| fix      | 3     |
| ...      | ...   |
```

Then list each TODO with file path and line number.

### `/repotodo <category> all`
Process ALL TODOs of the specified category.

Example: `/repotodo feat all` - Implement all TODO-feat items

### `/repotodo <category> <N>`
Process N TODOs of the specified category.

Example: `/repotodo chore 1` - Process one TODO-chore item

## Workflow

### Phase 1: Scan TODOs

Use grep to find all TODO comments:

```bash
grep -rn "TODO-\(feat\|fix\|docs\|style\|refactor\|test\|chore\|build\|ci\|perf\|revert\):" --include="*.ts" --include="*.tsx" --include="*.js" --include="*.jsx" --include="*.py" --include="*.md" .
```

Parse results into structured format:
- File path
- Line number
- Category
- Description

### Phase 2: Lock Check (for single TODO processing)

Before processing a TODO, check if it's already being processed by another CLI instance:

1. Lock file location: `/tmp/claude-todo-locks/`
2. Lock file format: `{file_path_hash}_{line_number}.lock`
3. Lock contains: timestamp, CLI instance ID

**Lock logic:**
```bash
LOCK_DIR="/tmp/claude-todo-locks"
mkdir -p "$LOCK_DIR"

# Create lock file with current timestamp
LOCK_FILE="$LOCK_DIR/$(echo "$FILE:$LINE" | md5sum | cut -d' ' -f1).lock"

if [ -f "$LOCK_FILE" ]; then
  # Check if lock is stale (older than 1 hour)
  LOCK_AGE=$(($(date +%s) - $(stat -c %Y "$LOCK_FILE")))
  if [ $LOCK_AGE -lt 3600 ]; then
    echo "TODO already being processed by another instance"
    # Skip to next TODO
  fi
fi

# Create/update lock
echo "$(date +%s):$$" > "$LOCK_FILE"
```

### Phase 3: Process TODO

1. Read the file containing the TODO
2. Understand the context around the TODO (read 50 lines before and after)
3. Implement the requested change
4. Remove the TODO comment after completion
5. Release the lock

### Phase 4: Cleanup

After completing a TODO:
1. Remove the TODO comment from the source file
2. Delete the lock file
3. Report completion

## Review Log Cleanup

When `/repotodo` finishes processing TODOs, it cleans up `.claude/review-agents.md`:

### Cleanup Behavior

After processing each TODO:

1. Read `.claude/review-agents.md` if it exists
2. For each row in the agent tables:
   - Check if the TODO comment still exists in the source file
   - If the TODO was removed (fixed), delete the row from the table
3. Update `Total TODOs` count in header
4. If all rows for an agent section are done, remove that agent section
5. If all agents are done, archive or delete the file

### Implementation

```bash
cleanup_review_log() {
  local review_log=".claude/review-agents.md"
  [ -f "$review_log" ] || return

  local temp_file=$(mktemp)
  local total_remaining=0

  # Process each table row
  while IFS='|' read -r _ file line category comment _; do
    # Skip header rows
    [[ "$file" =~ ^[[:space:]]*File ]] && continue
    [[ "$file" =~ ^[[:space:]]*--- ]] && continue
    [ -z "$file" ] && continue

    file=$(echo "$file" | tr -d ' ')
    line=$(echo "$line" | tr -d ' ')

    # Check if TODO still exists at that line
    if [ -f "$file" ]; then
      local line_content=$(sed -n "${line}p" "$file" 2>/dev/null)
      if echo "$line_content" | grep -q "TODO-"; then
        # TODO still exists, keep the row
        ((total_remaining++))
        echo "| $file | $line | $category | $comment |" >> "$temp_file"
      fi
    fi
  done < <(grep "^|" "$review_log" | tail -n +3)

  # Update the total count
  sed -i "s/\*\*Total TODOs:\*\* [0-9]*/\*\*Total TODOs:\*\* $total_remaining/" "$review_log"

  # If no TODOs remain, optionally archive
  if [ "$total_remaining" -eq 0 ]; then
    mv "$review_log" ".claude/review-agents-$(date +%Y%m%d-%H%M%S).archived.md"
    echo "Review complete - all TODOs processed. Log archived."
  fi
}
```

### After Processing

After each TODO is processed:
```bash
# Check if this TODO came from a review agent
if grep -q "Review agent" "$file:$line"; then
  cleanup_review_log
fi
```

---

## Important Notes

- Always read the full context before implementing a TODO
- Ensure changes don't break existing functionality
- Run tests if available after implementing each TODO
- If a TODO is unclear, ask for clarification instead of guessing
- Group related TODOs when processing multiple items
- Review agent TODOs are tracked in `.claude/review-agents.md` and cleaned up automatically
