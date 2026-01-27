---
name: youtube
description: Transcribe YouTube videos and manage transcripts. Use for video analysis, content extraction, or research.
argument-hint: <video_id_or_url> | list | delete <id> | delete all
user-invocable: true
context: main
---

# YouTube Transcription Skill

**When invoked, immediately output:** `**SKILL_STARTED:** youtube`

Transcribe YouTube videos to markdown files and manage your transcript library.

## Workflow

1. **FIRST:** Output `**SKILL_STARTED:** youtube` before any parsing or logic
2. Parse `$ARGUMENTS` to determine action
3. Execute the appropriate action below

## Usage

```
/youtube <video_id_or_url>   - Transcribe a YouTube video
/youtube list                - List all transcribed videos
/youtube delete <id>         - Delete a specific transcript
/youtube delete all          - Delete ALL transcripts
/youtube help                - Show this help
```

## Argument Routing

From `$ARGUMENTS`, determine the action:

| Input | Action |
|-------|--------|
| `""` or `help` | Show usage help |
| `list` | List all transcripts in table |
| `delete <id>` | Delete specific transcript |
| `delete all` | Delete all transcripts |
| URL or video ID | Transcribe video |

---

## Action: Transcribe Video (default)

When user provides a video ID or URL:

### 1. Run Transcription Script

```bash
export YOUTUBE_PROJECT_DIR="$PWD" && cd /usr/share/claude/skills/youtube/scripts && uv run transcribe.py "$VIDEO_ID_OR_URL"
```

The `YOUTUBE_PROJECT_DIR` environment variable ensures the session tracker is created in the current project directory, not the script directory.

### 2. Track Session Usage

The script automatically tracks usage in `.claude/youtube-session.json` for RALPH cleanup.

### 3. Display Result

Show:
- Video title, author, duration
- Language detected
- File location
- First 500 characters of transcript as preview

---

## Action: List Transcripts

`/youtube list`

### 1. Scan Transcripts Directory

Find all `.md` files in `~/.claude/youtube/transcriptions/`

### 2. Parse YAML Frontmatter

For each file, extract:
- `video_id`
- `title`
- `author`
- `duration`
- `created`

### 3. Get Session Information

For each transcript, check which sessions have used it by scanning:
- `~/.claude/projects/*/sessions-index.json` for session metadata
- `.claude/youtube-session.json` files in project directories

### 4. Display Table

```
YouTube Transcripts:

ID          | Title                              | Author         | Duration | Created  | Project          | Session
------------|------------------------------------|--------------------|----------|----------|------------------|----------------
dQw4w9WgXcQ | Never Gonna Give You Up            | Rick Astley        | 3:32     | 2h ago   | gswarm-api/main  | f4799e2a: Can we add...

Total: 1 transcript (45 KB)

Actions: delete <id> | delete all
```

### 5. Calculate Total Size

```bash
du -sh ~/.claude/youtube/transcriptions 2>/dev/null | cut -f1
```

---

## Action: Delete Transcript

`/youtube delete <id>`

### 1. Find Transcript

Match video_id prefix (first 4+ chars) against filenames:
```bash
find ~/.claude/youtube/transcriptions -name "youtube-${VIDEO_ID}*.md" 2>/dev/null
```

### 2. Show Confirmation

Display transcript metadata and ask for confirmation:
```
Delete transcript for "Video Title" by "Author" (3:32)?
File: ~/.claude/transcriptions/youtube-dQw4w9WgXcQ.md
Size: 45 KB

Type "yes" to confirm:
```

### 3. Execute Deletion

On confirmation:
```bash
rm -f ~/.claude/youtube/transcriptions/youtube-${VIDEO_ID}.md
```

### 4. Update Session Tracker

Remove entry from `.claude/youtube-session.json` if present.

---

## Action: Delete All Transcripts

`/youtube delete all`

### 1. Count and Size

```bash
count=$(ls ~/.claude/youtube/transcriptions/*.md 2>/dev/null | wc -l)
size=$(du -sh ~/.claude/youtube/transcriptions 2>/dev/null | cut -f1)
```

### 2. Preview

```
Found X transcripts (Y total)

This action cannot be undone.
```

### 3. Require Confirmation

**Ask: "Delete ALL transcripts? Type 'yes' to confirm:"**

### 4. Execute

On "yes":
```bash
rm -f ~/.claude/youtube/transcriptions/*.md
rm -f .claude/youtube-session.json
```

### 5. Report

```
Deleted X transcripts, freed Y
```

---

## Session Tracking

### Tracker File Location

`.claude/youtube-session.json` (project-local)

### Format

```json
{
  "transcripts_used": [
    {
      "video_id": "dQw4w9WgXcQ",
      "title": "Never Gonna Give You Up",
      "file_path": "~/.claude/transcriptions/youtube-dQw4w9WgXcQ.md",
      "added_at": "2026-01-21T10:00:00Z"
    }
  ]
}
```

### RALPH Integration

When `<promise>RALPH_COMPLETE</promise>` is detected, the ralph-orchestrator.py hook will:
1. Check for `.claude/youtube-session.json`
2. Prompt user to delete session transcripts
3. Clean up on confirmation

---

## Safety Rules

- **Always confirm before deletion**
- **`delete all` requires typing "yes"**
- **Never auto-delete transcripts**
- **Keep transcripts in global location (`~/.claude/transcriptions/`)**
- **Track per-session usage in project-local file**

## File Locations

| File | Purpose |
|------|---------|
| `/usr/share/claude/skills/youtube/scripts/transcribe.py` | Main transcription script |
| `~/.claude/youtube/transcriptions/*.md` | Stored transcripts (global, per-user) |
| `.claude/youtube-session.json` | Session usage tracker (project-local) |
