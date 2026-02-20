---
name: reviewplan
description: Process USER comments in plan files. Scans /plans/ for USER comments and applies changes with 🟧 markers.
argument-hint: "[path]"
user-invocable: true
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
5. **Execute Step 3**: Cleaup before adding new ones
6. **Add 🟧** (Orange Square) marker at END of modified line (not beginning!)
7. **Update** the "Last Updated" timestamp in frontmatter

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

### Step 5: Post-Processing Verification

After applying all changes, **re-scan the entire plan file** to verify no USER comments remain:

```bash
grep -n "USER:" path/to/plan.md
```

If any `USER:` lines are found after processing:
1. Report which lines still have USER comments
2. Process them again (Step 2)
3. Re-scan again until clean

**HALT condition:** If the same USER comment appears 3+ times across processing passes (loop detected), stop and report the issue to the user.

### Step 6: Formatting Check

After USER comments are cleared, run a full-file formatting check for common markdown corruption:

**Check 1 — Broken horizontal rules:**
```bash
grep -n "^---$" path/to/plan.md
```
Horizontal rules should appear on their own line. Flag any `---` that appears:
- Immediately after a heading (no blank line between)
- Inside a table row as cell content
- At the start of a list item

**Check 2 — Merged table headers:**
Look for table rows where the separator line (`|---|---|`) is missing or merged with content:
```bash
grep -n "^|" path/to/plan.md | grep -v "^|[-:]" | head -50
```
Flag any content row not preceded by a `|---|` separator row.

**Check 3 — Compressed numbered lists:**
Look for numbered list items with no blank line between them where blank lines existed before:
```bash
grep -n "^\d\+\." path/to/plan.md
```
If numbered items immediately follow each other with no spacing and the list has >3 items, verify the formatting is intentional (not accidentally collapsed).

Report any formatting issues found but do NOT auto-fix without USER confirmation.

### Step 7: Report

After processing, report:

```markdown
## /reviewplan Complete

Processed: [filename]
- USER comments found: N
- Changes applied: N
- Markers added: N
- Post-verification: CLEAN (or: N remaining USER comments)
- Formatting check: PASS (or: N issues found)

Files now clean of USER comments.
```

## Markdown-Safe 🟧 Placement Rules

**CRITICAL:** Place 🟧 at the **END of the line**, not the beginning. Different markdown elements require specific handling:

### Standard lines

Place at END of line: `Content changed 🟧`

### Headings

Place after text: `### Title 🟧`

### Tables

Place INSIDE last cell, before closing pipe:

```markdown
CORRECT: | File | Change 🟧 |
WRONG:   | File | Change | 🟧
```

NEVER mark separator rows:

```markdown
WRONG:   |------|--------| 🟧
SKIP:    |------|--------|    (no marker)
```

If entire table changed, mark the row ABOVE the table:

```markdown
Two services exist: 🟧
| File | Schedule |
|------|----------|
```

### Code blocks

NEVER place 🟧 inside code fences.
Mark the line ABOVE the code block:

```markdown
CORRECT: **Fixed imports:** 🟧
         ```typescript
         import { foo } from "bar";
         ```

WRONG:   import { foo } from "bar"; 🟧  (inside code)
```

### Lists

Place after item text: `- Item description 🟧`

### Incorrect (breaks markdown)

```markdown
🟧 ### Section Title    <- WRONG: breaks heading
🟧 Some content         <- WRONG: marker at beginning
```

## Marker Lifecycle: Remove Old Before Adding New

Each `/reviewplan` invocation MUST:

1. **Strip ALL existing 🟧 markers** from the entire file first
2. Process USER comments and apply changes
3. Add 🟧 ONLY to lines changed in THIS processing pass
4. Old markers from previous passes are gone — readers already saw them

This ensures the plan only shows what's NEW since the last review.

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

## Emoji Plan Output Format (MANDATORY)

When applying changes to plan files, all tables and sections MUST use emoji-prefixed headers:

**Section headers:** Add category emoji before title.

```markdown
## 🔒 Security Considerations
## ⚡ Performance Impact
## 🏗️ Architecture Changes
```

**Table headers:** Add status emoji in relevant cells.

```markdown
| # | ✅ Feature | ⚠️ Risk | 📋 Status |
|---|-----------|---------|----------|
| 1 | Auth flow | 🔴 High | ✅ Done  |
```

**Priority items:** 🔴 Critical, 🟡 Medium, 🟢 Low.
**Decision tables:** Each row gets a leading emoji for visual scanning.
**Comparison matrices:** Use emoji columns for at-a-glance status.

## Pre-ExitPlanMode Validation Gate (MANDATORY)

**Before calling ExitPlanMode**, the `/start` skill MUST validate that no `USER:` comments remain in any plan file:

```bash
grep -rn "USER:" ~/.claude/plans/*.md 2>/dev/null
```

**If any USER comments remain:**
1. **HALT** — do NOT call ExitPlanMode
2. Output: `⛔ HALT: Plan has unprocessed USER comments. Run /reviewplan first.`
3. List the files and line numbers with remaining USER comments
4. Wait for user to run `/reviewplan` and confirm

**Only proceed with ExitPlanMode after:**
- Zero `USER:` matches across all plan files, OR
- User explicitly overrides with `/start ... force` (documents the override)

This gate prevents implementation agents from working off a stale plan that still has pending user feedback.

## Integration with /start

When executing a plan via `/start`, the skill should be invoked automatically if USER comments are detected. The `/start` skill will suggest running `/reviewplan` before proceeding with implementation.

## Hook Integration

This skill works with the `guards.py` hooks:

- **UserPromptSubmit**: Detects USER comments and injects processing reminder
- **PostToolUse**: Warns if plan files still have USER comments after writes
