---
name: chats
description: Manage Claude Code chats - list, rename, delete, and clean up old chats. Use when viewing chat history, cleaning up disk space, or resuming previous work.
user-invocable: true
context: main
---

# Chats Manager

**When invoked, immediately output:** `**SKILL_STARTED:** chats`

Interactive chat manager for browsing, renaming, deleting, and cleaning Claude Code chats.

## Usage

```
/chats                      - List all chats
/chats [id]                 - View chat details
/chats rename [id] [name]   - Rename a chat
/chats delete [id|days|all] - Delete chat(s) by ID, age, or all
/chats cache                - Clean non-essential caches
/chats open [id]            - Show how to resume a chat
/chats filter [project]     - Filter by project name
/chats commits              - Manage commit.md files across projects
/chats commits delete all   - Delete all commit.md files
/chats plans                - Interactive plan files manager
/chats plans delete all     - Bulk delete all plan files
/chats help                 - Show this help
```

## Help Command

When arguments equal "help":

```
/chats help

Available commands:
  /chats                      List all chats
  /chats [id]                 View chat details
  /chats rename [id] [name]   Rename a chat
  /chats delete [id|days|all] Delete chat(s) - by ID, by age (days), or all
  /chats cache                Clean caches
  /chats open [id]            Show resume command
  /chats filter [project]     Filter by project

Examples:
  /chats filter gswarm-api
  /chats delete 30            # Delete chats older than 30 days
  /chats delete all           # Delete all chats
  /chats delete abc123        # Delete specific chat
  /chats rename abc123 "Auth implementation"
```

---

## Data Source

Chats are stored in `~/.claude/projects/*/sessions-index.json` files.

Each `sessions-index.json` contains:
```json
{
  "version": 1,
  "entries": [
    {
      "sessionId": "uuid",
      "fullPath": "/path/to/session.jsonl",
      "firstPrompt": "chat name/description",
      "messageCount": 10,
      "created": "ISO date",
      "modified": "ISO date",
      "projectPath": "/path/to/project"
    }
  ]
}
```

---

## Action: List Chats (default)

When user runs `/chats` with no arguments:

### 1. Load All Chats

```bash
cat ~/.claude/projects/*/sessions-index.json 2>/dev/null | jq -s '[.[].entries[]] | sort_by(.modified) | reverse'
```

### 2. Display Chats Table

Show a formatted table with columns:
- **ID**: First 8 characters of `sessionId`
- **Name**: `firstPrompt` truncated to ~40 chars (or "No prompt" if empty)
- **Modified**: `modified` date in human-readable format (e.g., "2h ago", "Jan 20")
- **Msgs**: `messageCount`
- **Project**: Repo/branch format using project detection helper

```
Chats (newest first):

ID       | Name                                     | Modified  | Msgs | Project
---------|------------------------------------------|-----------|------|------------------
f4799e2a | Can we add a skill or command in ~/.c... | 2h ago    |    1 | gswarm-api/main
5fc9e45f | i see only question marks, fix this...   | 2h ago    |   24 | gswarm-cli/feature
ac96a372 | No prompt                                | 5h ago    |   10 | gemini-api/worktree1
```

### Project Detection Helper

Extract repo/branch format from project path:

```bash
get_project_display() {
  local project_path="${1%/}"
  local git_path="$project_path/.git"

  if [ -f "$git_path" ]; then
    # Worktree: extract name from gitdir path
    local gitdir=$(cat "$git_path" | sed 's/gitdir: //')
    echo "$(echo "$gitdir" | sed 's|/.git/worktrees/.*||' | xargs basename)/$(basename "$project_path")"
  else
    # Regular repo: use branch name
    local branch=$(git -C "$project_path" rev-parse --abbrev-ref HEAD 2>/dev/null)
    echo "$(basename "$project_path")${branch:+/$branch}"
  fi
}
# Examples: gswarm-api/main, gswarm-api/worktree1, bare-repo/feat
```

### 3. Show Available Actions

```
Actions: rename [id] [name] | delete [id] | delete [days|all] | cache | open [id] | filter [project]
```

---

## Action: Rename Chat

`/chats rename [id] [name]`

1. Find the `sessions-index.json` containing the chat ID (match first 8+ chars)
2. Update the `firstPrompt` field for that entry
3. Write the updated JSON back to the file
4. Confirm: "Chat [id] renamed to '[name]'"

```bash
# Find index file containing chat
for f in ~/.claude/projects/*/sessions-index.json; do
  if jq -e --arg id "$SESSION_ID" '.entries[] | select(.sessionId | startswith($id))' "$f" >/dev/null 2>&1; then
    # Update firstPrompt
    jq --arg id "$SESSION_ID" --arg name "$NEW_NAME" \
      '(.entries[] | select(.sessionId | startswith($id))).firstPrompt = $name' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  fi
done
```

---

## Action: Delete Chats (unified)

`/chats delete [id|days|all]`

The delete command handles three argument types:

### If argument is a chat ID (alphanumeric, 8+ chars):

1. Find the `sessions-index.json` containing the chat ID
2. Get the `fullPath` of the chat file
3. **Ask for confirmation** showing chat details
4. If confirmed:
   - Remove the chat `.jsonl` file
   - Remove the entry from the index
   - Write the updated JSON back
5. Report: "Deleted chat [id]"

### If argument is "all":

1. Find all chats across all projects:
   ```bash
   for f in $(find ~/.claude/projects -name "sessions-index.json" 2>/dev/null); do
     jq '.entries | length' "$f"
   done | awk '{sum+=$1} END {print sum}'
   ```

2. Get total size:
   ```bash
   find ~/.claude/projects -name "*.jsonl" -exec du -ch {} + 2>/dev/null | tail -1
   ```

3. Show preview: "Found X chats across Y projects (Z MB total)"

4. **Ask: "Delete ALL chats? Type 'yes' to confirm:"**

5. If confirmed, for each sessions-index.json:
   ```bash
   jq -r '.entries[].fullPath' "$index_file" | while read f; do rm -f "$f"; done
   jq '.entries = []' "$index_file" > "$index_file.tmp" && mv "$index_file.tmp" "$index_file"
   ```

6. Report: "Deleted X chats, freed Y MB"

7. **Prompt for Additional Cleanup** - After deleting chats, prompt for each:

   ```
   Delete screenshots? (12 files, 746 KB) (yes/no):
   Delete plan files? (53 files, 285 KB) (yes/no):
   Delete debug/? (410 files, 97 MB) (yes/no):
   Delete todos/? (16 files, 72 KB) (yes/no):
   Delete tasks/? (9 dirs, 80 KB) (yes/no):
   Delete file-history/? (24 files, 1.2 MB) (yes/no):
   Delete paste-cache/? (8 files, 128 KB) (yes/no):
   Delete shell-snapshots/? (58 files, 3.6 MB) (yes/no):
   Delete session-env/? (2.4 MB) (yes/no):
   Delete command-history.log? (256 KB) (yes/no):
   Delete Ralph state? (state, checkpoints, guardian) (yes/no):
   Delete project .claude/ dirs? (3 projects, 1.5 MB) (yes/no):
   ```

   **Cleanup paths** (count files, show size, delete if confirmed):

   | Item | Path Pattern |
   |------|-------------|
   | screenshots | `/usr/share/claude/skills/screen/screenshots/screen-*.png` |
   | plans | `/usr/share/claude/plans/*.md` |
   | debug | `~/.claude/debug/*` |
   | todos | `~/.claude/todos/*` |
   | tasks | `~/.claude/tasks/*` (use `find -mindepth 1 -maxdepth 1 -type d` for count) |
   | file-history | `~/.claude/file-history/*` |
   | paste-cache | `~/.claude/paste-cache/*` |
   | shell-snapshots | `~/.claude/shell-snapshots/*` |
   | session-env | `~/.claude/session-env/*` |
   | command-history | `~/.claude/command-history.log` |
   | ralph/ | `~/.claude/ralph/` (state.json, activity.log, checkpoints/, guardian/) |
   | ralph-legacy | `~/.claude/ralph-state.json`, `~/.claude/ralph-activity.log`, `~/.claude/ralph-checkpoints/` |
   | project .claude/ | See "Project Directory Cleanup" below |

8. **Project Directory Cleanup** - Scan known project directories for `.claude/` folders:

   ```bash
   # Scan common project locations
   for base in ~/projects ~/repos ~/code ~/work; do
     find "$base" -maxdepth 2 -type d -name ".claude" 2>/dev/null
   done
   ```

   For each project `.claude/` directory found, show and optionally delete:

   | Item | Path Pattern | Description |
   |------|--------------|-------------|
   | sessions | `{project}/.claude/sessions/*.json` | Browser session data |
   | task-queue | `{project}/.claude/task-queue-*.json` | Ralph task queues |
   | pending-commit | `{project}/.claude/pending-commit.md` | Pending commit changes |
   | pending-pr | `{project}/.claude/pending-pr.md` | Pending PR summary |
   | ralph/ | `{project}/.claude/ralph/` | All Ralph state (state, logs, checkpoints, guardian) |

   **Display format:**
   ```
   Project .claude/ directories found:

   #  | Project              | Sessions | Queues | State Files | Size
   ---|----------------------|----------|--------|-------------|------
   1  | gswarm-api           | 3        | 2      | 5           | 450 KB
   2  | my-nextjs-app        | 1        | 0      | 2           | 128 KB

   Delete all project .claude/ contents? (yes/no):
   ```

9. Final report with total freed space

### If argument is a number (days):

1. Calculate cutoff date:
   ```bash
   cutoff_date=$(date -d "$DAYS days ago" -Iseconds)
   ```

2. Find chats older than N days:
   ```bash
   for index_file in $(find ~/.claude/projects -name "sessions-index.json" 2>/dev/null); do
     jq --arg cutoff "$cutoff_date" '.entries[] | select(.modified < $cutoff)' "$index_file"
   done
   ```

3. Show preview with list of chats to delete

4. **Ask: "Delete these X chats? (yes/no)"**

5. If confirmed, delete matching chats and update indexes

6. Report: "Deleted X chats, freed Y MB"

### Argument Detection Logic

```bash
case "$1" in
  all) delete_all_chats ;;
  *[!0-9]*) delete_chat_by_id "$1" ;;  # Non-numeric = chat ID
  *) delete_chats_older_than "$1" ;;    # Numeric = days
esac
```

---

## Action: Clean Cache

`/chats cache`

Clean non-essential Claude Code cache directories to free disk space.

### Directories to Clean

| Directory | Contents | Impact |
|-----------|----------|--------|
| ~/.claude/cache/ | Temporary cache files | None - regenerated as needed |
| ~/.claude/debug/ | Debug and error logs | Lose debug history |
| ~/.claude/file-history/ | File change history | Lose undo history for files |
| ~/.claude/shell-snapshots/ | Shell state snapshots | None - regenerated |
| ~/.claude/paste-cache/ | Clipboard cache | None - temporary |

### NOT Cleaned (Important Data)

- projects/ - Use `/chats delete` instead
- settings.json - User configuration
- skills/ - User skills
- commands/ - User commands
- CLAUDE.md - User instructions
- credentials.json - Authentication

### Behavior

1. For each directory:
   ```bash
   du -sh ~/.claude/[dir]/ 2>/dev/null
   rm -rf ~/.claude/[dir]/*
   ```

2. Display results:
   ```
   Cleaning Claude Code caches...

   | Directory        | Size    | Status |
   |------------------|---------|--------|
   | cache/           | 2.1 MB  |      |
   | debug/           | 18.4 MB |      |
   | file-history/    | 5.6 MB  |      |
   | shell-snapshots/ | 1.2 MB  |      |
   | paste-cache/     | 0.3 MB  |      |

   Freed 27.6 MB total
   ```

**No confirmation needed** - all data is regenerable/non-essential.

---

## Action: Open Chat

`/chats open [id]`

Show how to resume the chat:

1. Find the chat by ID
2. Display:
   - Full chat ID
   - Project path
   - Instructions: `cd [projectPath] && claude --resume [sessionId]`

---

## Action: Filter Chats

`/chats filter [project]`

Show only chats from a specific project:

1. Match project name against `projectPath` (last 2 segments, e.g., `gswarm-api/main`)
2. Display filtered table with same format

---

## Safety & Implementation Notes

- **Always show preview and require confirmation before deleting**
- `delete all` requires typing "yes" to confirm
- Preserve sessions-index.json structure (only modify entries array)
- Use `jq` for JSON parsing, ISO 8601 for date comparison
- Project directories use path encoding (e.g., `-home-dennis-Desktop-project`)
- Always update both .jsonl file AND sessions-index.json entry
- Sort by `modified` date descending (newest first)

---

## Action: Commits Manager

`/chats commits`

Interactive manager for browsing, viewing, and deleting commit.md files across all projects.

### Project Detection

Scan these directories for Git repositories and worktrees:
- `~/projects`
- `~/repos`
- `~/code`
- `~/work`

### Display Format

```
=== Commit Files ===

#  | Project                    | Entries | Last Updated
---|----------------------------|---------|-------------
1  | gswarm-api/main            | 15      | 2h ago

Actions: [1-N] View | [d] Delete | [a] Delete All | [q] Quit
```

Actions: View (number), Delete (d), Delete All (a - requires "yes"), Quit (q)

---

## Action: Plans Manager

`/chats plans`

Interactive manager for browsing, viewing, and deleting plan files.

### Plan Storage

Plan files are stored in: `/usr/share/claude/plans/`

### Display Format

```
=== Plan Files ===

#  | Filename                              | Modified         | Size | Project
---|---------------------------------------|------------------|------|------------------
1  | glittery-herding-panda.md             | 2026-01-21 09:29 | 26K  | gswarm-api/main

Actions: [1-N] View | [d] Delete | [a] Delete All | [q] Quit
```

Actions: View (number), Delete (d), Delete All (a - requires "yes"), Quit (q)

---

## Manager Safety Rules

Always preview before delete, require confirmation (bulk = "yes"), handle missing files gracefully, report deletions.
