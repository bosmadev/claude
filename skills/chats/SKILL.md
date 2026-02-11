---
name: chats
description: Manage Claude Code chats - list, rename, delete, and clean up old chats. Use when viewing chat history, cleaning up disk space, or resuming previous work.
argument-hint: "[id|rename|delete|cache|open|filter|commits|plans|help]"
user-invocable: true
---

## EXECUTE IMMEDIATELY — DO NOT ANALYZE

**CRITICAL: When `/chats` is invoked, you MUST run the Python script below IMMEDIATELY. Do NOT research the codebase, do NOT analyze the skill, do NOT write a report. JUST RUN THE SCRIPT.**

```bash
python "~/.claude/skills/chats/display-chats.py" <command> [args...]
```

**Argument mapping from user input to script args:**

| User types | Script args |
|---|---|
| `/chats` | `list` |
| `/chats [id]` | `[id]` |
| `/chats rename [id] [name]` | `rename [id] [name]` |
| `/chats delete [id\|days\|all]` | `delete [id\|days\|all]` |
| `/chats delete-confirm [id\|all]` | `delete-confirm [id\|all]` |
| `/chats cache` | `cache` |
| `/chats open [id]` | `open [id]` |
| `/chats filter [project]` | `filter [project]` |
| `/chats commits` | `commits` |
| `/chats plans` | `plans` |
| `/chats help` | `help` |

**CRITICAL: After running the script, you MUST copy the ENTIRE script output into your text response as a markdown code block. Bash tool output is NOT visible to the user — they cannot see tool results. You MUST paste the output as text.**

**Do NOT summarize, explain, or analyze the output. Just paste it raw.**

**STOP. Run the script NOW. Do not read further.**

---

## Reference (for context only — do not read before executing)

### Delete workflow

Delete uses a two-step preview/confirm pattern:
1. `delete [arg]` — shows preview with machine-readable markers (`PREVIEW_DELETE_ID:`, `PREVIEW_DELETE_ALL`, `PREVIEW_DELETE_DAYS:`)
2. Agent confirms with user
3. `delete-confirm [arg]` — executes the deletion

### Post-delete cleanup

After `delete all`, run `cleanup-preview` to show additional cleanable items.
Each item can be cleaned with `cleanup-item [name]`.

### Machine-readable markers

The script outputs markers for agent coordination:
- `PREVIEW_DELETE_ID:<sessionId>` — confirm single delete
- `PREVIEW_DELETE_ALL` — confirm delete all
- `PREVIEW_DELETE_DAYS:<N>` — confirm delete by age
- `CLEANUP_ITEMS:<comma-separated>` — available cleanup items
- `COMMIT_FILES:<pipe-separated-paths>` — commit file paths
- `PLAN_FILES:<pipe-separated-paths>` — plan file paths
