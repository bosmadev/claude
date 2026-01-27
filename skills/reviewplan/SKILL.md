---
name: reviewplan
description: Process USER comments in plan files. Scans /plans/ for USER comments and applies changes with 🟧 markers.
argument-hint: "[path]"
user-invocable: true
context: main
---

# /reviewplan - Plan Comment Processor

**When invoked, immediately output:** `**SKILL_STARTED:** reviewplan`

Process USER comments in plan files and apply proper change tracking.

## Usage

```bash
/reviewplan              # Process all plan files in /plans/
/reviewplan path/to.md   # Process specific plan file
```

## Workflow

When invoked, follow this exact process:

### Step 0: Emit Start Signal

Output the skill started signal immediately, before any other processing:

```
**SKILL_STARTED:** reviewplan
```

### Step 1: Scan for USER Comments

```bash
# Find all plan files with USER comments
grep -rn "USER:" plans/*.md 2>/dev/null || echo "No USER comments found"
```

### Step 2: For Each USER Comment Found

1. **Read** the USER: comment line
2. **Understand** what change is requested
3. **Apply** the requested change to the plan
4. **Remove** the USER: line completely
5. **Add 🟧** (Orange Square) marker at END of modified line (not beginning!)
6. **Update** the "Last Updated" timestamp in frontmatter

### Step 3: Clean Up Old Markers

Before adding new markers, remove ALL existing 🟧 markers from the file:

```python
# Conceptually:
content = content.replace(" 🟧", "")  # Remove markers
# Then add new markers only to lines changed in THIS processing
```

### Step 4: Update Timestamp

Update the frontmatter:

```markdown
**Last Updated:** 2026-01-24T23:00:00Z
```

Use current UTC time in ISO 8601 format.

### Step 5: Report

After processing, report:

```markdown
## /reviewplan Complete

Processed: [filename]
- USER comments found: N
- Changes applied: N
- Markers added: N

Files now clean of USER comments.
```

## Change Marker Format

**CRITICAL:** Place 🟧 (Orange Square) at the **END of the line**, not the beginning.

**Correct:**
```markdown
### Section Title 🟧
Some content that was changed 🟧
```

**Incorrect (breaks markdown):**
```markdown
🟧 ### Section Title
🟧 Some content
```

## Example

**Before:**
```markdown
## Files to Create 🟧

USER: Add a new file for database schema

| File | Purpose |
|------|---------|
| app.py | Main app |
```

**After processing:**
```markdown
## Files to Create

| File | Purpose |
|------|---------|
| app.py | Main app |
| schema.sql | Database schema 🟧 |
```

## Integration with /start

When executing a plan via `/start`, the skill should be invoked automatically if USER comments are detected. The `/start` skill will suggest running `/reviewplan` before proceeding with implementation.

## Hook Integration

This skill works with the `guards.py` hooks:
- **UserPromptSubmit**: Detects USER comments and injects processing reminder
- **PostToolUse**: Warns if plan files still have USER comments after writes
