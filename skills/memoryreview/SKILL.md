---
name: memoryreview
description: Analyze, optimize, and sync MEMORY.md files across worktrees. Use when reviewing memory health, checking size limits, or merging memory from main branch.
when_to_use: When the user wants to review memory quality, optimize memory size, sync memory from main, or compare memory between worktrees.
argument-hint: "[analyze|optimize|pull|diff|help]"
context: fork
---

# /memoryreview — Memory File Health & Sync

Analyze and maintain MEMORY.md files across worktrees.

**EXECUTE IMMEDIATELY (NO PLANNING):**

When the user runs `/memoryreview [command]`, immediately execute:

```bash
python ~/.claude/scripts/memoryreview.py {command}
```

Where `{command}` is the user's argument. Default to "analyze" if no argument provided.

**After running the script, copy the ENTIRE script output into your response as a markdown code block. Bash tool output is NOT visible to the user.**

**STOP after execution. Do NOT continue with any other tasks.**

---

## Commands

| Command | Effect |
|---------|--------|
| `/memoryreview` | Analyze MEMORY.md: duplicates, stale entries, consolidation suggestions |
| `/memoryreview analyze` | Same as above |
| `/memoryreview optimize` | Check size vs 200-line CC limit, suggest topic file moves |
| `/memoryreview pull` | Smart merge from main worktree — diff by heading, merge new entries |
| `/memoryreview diff` | Side-by-side comparison between main and current branch memory files |
| `/memoryreview help` | Show usage, commands, examples |

## Behavior

- **analyze**: Reads current MEMORY.md, counts lines/sections, detects duplicate headings, flags entries older than 30 days
- **optimize**: Reports line count vs 200-line system prompt limit, identifies sections > 10 lines that should move to topic files
- **pull**: Finds main worktree via `git worktree list`, diffs by `##` headings, merges new entries only — does NOT overwrite
- **diff**: Shows which `##` sections exist in main but not current branch, and vice versa
- **help**: Prints usage summary

## Notes

- MEMORY.md is auto-injected into every system prompt (first 200 lines only)
- Lines 200+ are silently truncated — oversized MEMORY.md loses data
- `pull` is safe: only adds new headings, never removes existing ones
- For destructive edits, the user must edit MEMORY.md directly

## Examples

```bash
# Check memory health
/memoryreview

# See what's bloating memory
/memoryreview optimize

# Sync new entries from main branch
/memoryreview pull

# Preview differences before pulling
/memoryreview diff
```
