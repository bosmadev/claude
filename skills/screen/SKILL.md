---
name: screen
description: Capture and manage screenshots using Windows Snipping Tool. Use for visual documentation, bug reporting, or UI reference.
argument-hint: [N] [list] [clean] [analyze <id>] [delete <id>] [help]
user-invocable: true
context: fork
---
# Screen Capture Skill

**When invoked, immediately output: `SKILL_STARTED: screen`**

Capture screenshots with Windows Snipping Tool and manage your screenshot library.

## Usage

```
/screen                  - Capture a region screenshot
/screen N                - Review last N screenshots
/screen list             - List all screenshots with metadata
/screen clean            - Delete screenshots older than 7 days
/screen analyze [id]     - Analyze a specific screenshot
/screen delete [id]      - Delete a specific screenshot
/screen help             - Show this help
```

## Argument Routing

From `$ARGUMENTS`, determine the action:

| Input            | Action                               |
| ---------------- | ------------------------------------ |
| `""` or empty  | Capture new region screenshot        |
| Number (N)       | Review last N screenshots            |
| `list`         | List all screenshots                 |
| `clean`        | Delete screenshots older than 7 days |
| `analyze <id>` | Analyze specific screenshot          |
| `delete <id>`  | Delete specific screenshot           |
| `help`         | Show usage help                      |

---

## Script Validation

Before executing any script command, validate that the required scripts exist:

```bash
SCRIPT_DIR="C:/Users/Dennis/.claude/skills/screen/scripts"

# Check capture.py exists
if [ ! -f "$SCRIPT_DIR/capture.py" ]; then
    echo "Error: capture.py not found at $SCRIPT_DIR/capture.py"
    echo "Check Claude Code installation or reinstall the screen skill"
    exit 1
fi

# Check manage.py exists
if [ ! -f "$SCRIPT_DIR/manage.py" ]; then
    echo "Error: manage.py not found at $SCRIPT_DIR/manage.py"
    echo "Check Claude Code installation or reinstall the screen skill"
    exit 1
fi
```

**Failure handling:** If scripts are missing, abort with clear error message directing the user to check the installation.

## Storage

Screenshots are stored at: `~/.claude\skills\screen\screenshots\`

Filename format: `screen-{timestamp}.png`

- Example: `screen-20260123-143052.png`

---

## Action: Capture Screenshot (default)

When user runs `/screen` with no arguments:

### 1. Run Capture Script

```bash
python C:/Users/Dennis/.claude/skills/screen/scripts/capture.py
```

The script will:

- Launch Windows Snipping Tool in region capture mode
- Wait for user to select a region
- Save to `~/.claude\skills\screen\screenshots\screen-{timestamp}.png`
- Output the file path on success

### 2. Display Result

On success:

```
Screenshot captured: ~/.claude\skills\screen\screenshots\screen-20260123-143052.png
```

### 3. Offer Analysis

Ask user: "Would you like me to analyze this screenshot?"

If yes, use the Read tool to view the image and describe its contents.

---

## Action: Review Last N Screenshots

`/screen N` (where N is a number)

### 1. Get Recent Screenshots

```bash
python C:/Users/Dennis/.claude/skills/screen/scripts/manage.py list --limit N --json
```

### 2. Display and Analyze

For each screenshot (newest first):

1. Show filename, timestamp, and size
2. Use Read tool to view the image
3. Provide brief description of contents

---

## Action: List Screenshots

`/screen list`

### 1. Run List Command

```bash
python C:/Users/Dennis/.claude/skills/screen/scripts/manage.py list
```

### 2. Display Table

```
Screenshots (~/.claude\skills\screen\screenshots\):

ID       | Filename                    | Created          | Size
---------|----------------------------|------------------|--------
143052   | screen-20260123-143052.png | Jan 23, 14:30    | 245 KB
120815   | screen-20260123-120815.png | Jan 23, 12:08    | 189 KB

Total: 2 screenshots (434 KB)

Actions: analyze <id> | delete <id> | clean
```

ID is derived from the timestamp portion (HHMMSS) for easy reference.

---

## Action: Clean Old Screenshots

`/screen clean`

### Example Session

```
User: /screen clean

Claude: **SKILL_STARTED:** screen

Scanning for screenshots older than 7 days...

Found 3 screenshots older than 7 days:

- screen-20260116-091523.png (Jan 16, 09:15) - 234 KB
- screen-20260115-182034.png (Jan 15, 18:20) - 156 KB
- screen-20260112-143052.png (Jan 12, 14:30) - 89 KB

Total: 479 KB to free

Delete these screenshots? (yes/no)

User: yes

Claude: Deleting...
- Deleted screen-20260116-091523.png
- Deleted screen-20260115-182034.png
- Deleted screen-20260112-143052.png

Deleted 3 screenshots, freed 479 KB
```

### 1. Find Old Screenshots

```bash
python C:/Users/Dennis/.claude/skills/screen/scripts/manage.py clean --dry-run
```

### 2. Show Preview

```
Found X screenshots older than 7 days:

- screen-20260116-091523.png (Jan 16, 09:15) - 234 KB
- screen-20260115-182034.png (Jan 15, 18:20) - 156 KB

Total: 390 KB to free
```

### 3. Require Confirmation

**Ask: "Delete these screenshots? (yes/no)"**

### 4. Execute

On "yes":

```bash
python C:/Users/Dennis/.claude/skills/screen/scripts/manage.py clean
```

### 5. Report

```
Deleted X screenshots, freed Y KB
```

---

## Action: Analyze Screenshot

`/screen analyze <id>`

### 1. Find Screenshot

Match ID against timestamp portion of filenames.

### 2. Read and Analyze

Use the Read tool to view the image file, then provide:

- Description of UI elements visible
- Text content (if readable)
- Notable features or issues
- Context interpretation

---

## Action: Delete Screenshot

`/screen delete <id>`

### 1. Find Screenshot

```bash
python C:/Users/Dennis/.claude/skills/screen/scripts/manage.py find <id>
```

### 2. Show Confirmation

```
Delete screenshot?
File: ~/.claude\skills\screen\screenshots\screen-20260123-143052.png
Created: Jan 23, 2026 14:30:52
Size: 245 KB

Type "yes" to confirm:
```

### 3. Execute

On "yes":

```bash
python C:/Users/Dennis/.claude/skills/screen/scripts/manage.py delete <id>
```

### 4. Report

```
Deleted: screen-20260123-143052.png
```

---

## Safety Rules

- **Always confirm before deletion**
- **Show preview before bulk operations**
- **Never auto-delete screenshots**
- **Handle missing files gracefully**

## Use Cases

- **Bug Documentation**: Capture UI issues for reporting
- **Visual Reference**: Save designs or layouts for discussion
- **Progress Tracking**: Document visual changes during development
- **Code Review**: Share visual context for UI-related PRs

## Dependencies

- Windows Snipping Tool - Built-in Windows screenshot utility
- `python` - For management script

## File Locations

| File                                           | Purpose               |
| ---------------------------------------------- | --------------------- |
| `~/.claude\skills\screen\scripts\capture.py` | Capture script        |
| `~/.claude\skills\screen\scripts\manage.py`  | Management operations |
| `~/.claude\skills\screen\screenshots\`       | Screenshot storage    |
