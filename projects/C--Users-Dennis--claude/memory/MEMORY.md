# Auto Memory — ~/.claude Config Project

## Statusline Debug Findings (2026-02-05)
- Effort level is NOT in statusline stdin JSON — use `CLAUDE_CODE_EFFORT_LEVEL` env var fallback
- Model comes as `{"id": "claude-opus-4-6", "display_name": "Opus 4.6"}` object
- Context window size field: `context_window.context_window_size` (200000 for standard, 1000000 for 1M)
- `exceeds_200k_tokens` flag available for detecting extended context

## Model ID Parsing
- `claude-opus-4-6` = date-less alias (no `\d{8,}` suffix)
- Requires separate regex patterns `_MODEL_PATTERN_FULL_NO_DATE` / `_MODEL_PATTERN_SHORT_NO_DATE`
- Safe `date` group access: `m.group("date") if "date" in m.groupdict() and m.group("date") else ""`

## Settings.json Schema (Based on claude-code: 2.1.34)
- `teammateMode` is NOT a valid schema field — Agent Teams enabled via env var only
- `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in env block is sufficient

## Session Naming
- `sessions-index.json` has: `customTitle` (from /rename), `summary` (auto), `firstPrompt` (raw msg)
- `firstPrompt` is NOT the conversation name — it's the literal first user message
- Display priority: `customTitle` → `summary` → plan slug fallback

## Ralph Agents — CRITICAL
- After plan approval (ExitPlanMode), ALWAYS spawn Ralph agents via `/start` skill
- NEVER implement manually after plan approval — user demands Ralph agents every time

## D: Drive Temp Cleanup (2026-02-06)
- `CLAUDE_CODE_TMPDIR` added to settings.json → `${TMPDIR}/claude-tmp`
- Cache-break diffs were landing in `D:\tmp\claude\` — TMPDIR config prevents this
- Windows NUL files (reserved device name) require Git Bash `rm` to delete
- Known upstream issue: anthropics/claude-code#17886, #20568
- Cleanup script: `scripts/cleanup-d-drive.py`

## CC 2.1.34 Upgrade Findings (2026-02-06)
- TeammateIdle/TaskCompleted are MESSAGE TYPES in Agent Teams protocol, NOT hook events
- Do NOT add them to settings.json hooks — system delivers them automatically
- TeammateTool renamed to TeamCreate in .33; TeamDelete tool added in .33 for cleanup
- sandbox-boundary.py was running PostToolUse (ineffective) — fixed to PreToolUse
- security-gate.py post_edit_check was reading tool_input in PostToolUse (empty) — fixed
- VERIFY_FIX_MODEL now configurable via CLAUDE_CODE_VERIFY_FIX_MODEL env var