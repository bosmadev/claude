# Plan Guardian Integration

Consolidated documentation for the plan change tracking system.

## Overview

The plan change tracking system ensures USER comments in plan files are properly processed and changes are marked consistently. This document consolidates logic previously scattered across multiple files.

## Components

### 1. UserPromptSubmit Hook (`guards.py plan-comments`)

**When:** Every user prompt

**What it does:**
- Scans `/plans/*.md` for USER: comments
- Detects plan context (plan mode, recent plan edits, explicit requests)
- Injects processing instructions into Claude's context

**Key behavior:**
- If USER comments found: Injects warning with file list
- Suggests running `/reviewplan` for thorough processing

### 2. PostToolUse Hook (`guards.py plan-write-check`)

**When:** After Write/Edit operations on plan files

**What it does:**
- Checks if written plan file still has USER: comments
- Provides immediate feedback if comments remain unprocessed

**Key behavior:**
- Only fires for `/plans/*.md` files
- Non-blocking (feedback only, cannot prevent writes)

### 3. /reviewplan Skill

**When:** User explicitly invokes `/reviewplan`

**What it does:**
1. Scans all plan files for USER: comments
2. Processes each comment
3. Removes processed USER: lines
4. Adds 🟧 markers at end of modified lines
5. Updates timestamps
6. Reports changes made

## Change Marker Format

**Marker:** 🟧 (Orange Square, U+1F7E7)

**Placement:** At END of line (critical for markdown compatibility)

```markdown
# Correct
### Section Title 🟧
Content changed 🟧

# Incorrect (breaks markdown)
🟧 ### Section Title
🟧 Content changed
```

## Processing Rules

1. **Remove old markers** before adding new ones
2. **Add marker** only to lines changed in current processing
3. **Update timestamp** in frontmatter to current UTC time
4. **Delete USER: line** after processing the request

## Hook Configuration

In `settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /usr/share/claude/hooks/guards.py plan-comments",
            "timeout": 5
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /usr/share/claude/hooks/guards.py plan-write-check",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

## Integration with /start

When `/start` executes a plan:

1. Before implementation, check for USER comments
2. If found, suggest running `/reviewplan` first
3. After USER comments processed, proceed with implementation

The `/start` SKILL.md should include instructions to invoke `/reviewplan` during plan execution if USER comments are detected.

## Troubleshooting

### USER comments not detected

Check:
- Plan files are in `/plans/` directory
- Files have `.md` extension
- Comments start with `USER:` (case sensitive)

### Markers breaking markdown

Ensure markers are at END of line:
```markdown
### Title 🟧     # Correct
🟧 ### Title     # Wrong
```

### Hook not firing

Verify:
- Hook is registered in `settings.json`
- Python path is correct
- `guards.py` has correct permissions
