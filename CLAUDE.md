# Claude Code Configuration

#### Based on claude-code: 2.1.34

**Stack:** Next.js 16.1+, React 19+, Node.js 25+, Python 3.14+, FastAPI, TypeScript 5.9.3+, Tailwind CSS v4+, Shadcn UI, Radix, Playwright, Vitest, Biome 2.3.10+, Knip 5.77.1+, uv 0.9.18+, pnpm 10.26.2+.

**Build:** `pnpm build` | **Validate:** `pnpm validate`

## Directory Structure

```
~/.claude\
├── .github\                    # GitHub templates and workflows
│   ├── PULL_REQUEST_TEMPLATE.md
│   ├── ISSUE_TEMPLATE\
│   └── workflows\claude.yml
├── agents\                     # Agent configuration files (20 files)
├── hooks\                      # Claude Code hook handlers
├── output-styles\              # Response formatting styles
├── scripts\                    # CLI utilities
├── skills\                     # Skill definitions (/commands)
├── CLAUDE.md                   # Core patterns (this file)
├── USAGE.md                    # Commands & infrastructure reference
├── settings.json               # Hook registrations
└── README.md                   # Documentation
```

## Pending Files Convention

All temporary pending files MUST be created in `{repo}/.claude/` directory, never in repo root:

| File              | Correct Location                     | Wrong Location               |
| ----------------- | ------------------------------------ | ---------------------------- |
| pending-commit.md | `{repo}/.claude/pending-commit.md` | `{repo}/pending-commit.md` |
| pending-pr.md     | `{repo}/.claude/pending-pr.md`     | `{repo}/pending-pr.md`     |
| commit.md         | `{repo}/.claude/commit.md`         | Already correct              |

This keeps repo root clean and prevents accidental commits of temporary files.

## ACID Data Integrity

All state files use transactional primitives from `hooks/transaction.py`:

| File | Pattern | Timeout | Why |
|------|---------|---------|-----|
| `sessions-index.json` | OCC (lockless) | N/A | Low write contention |
| `ralph/progress.json` | Locked R/W | 5s | High-conflict agent updates |
| `commit.md` | Atomic write | N/A | Sequential hooks, crash safety |
| `receipts.json` | Locked append | 5s | Audit trail integrity |
| `emergency-state.json` | Locked R/W | 5s | Cross-platform safety |

**Import pattern:**
```python
from hooks.transaction import atomic_write_json, transactional_update, locked_read_json
```

**Error handling:** Catch `LockTimeoutError` for graceful degradation, `ValidationError` for schema issues.

**Test coverage:** Run `python -m pytest scripts/test_transaction.py -v` (21 tests)

## Frontend Visual Verification

When editing frontend files (pages, components, styles), verify changes visually:

**Files requiring verification:**
- `app/**/*.tsx` - Next.js pages and layouts
- `components/**/*.tsx` - React components
- `styles/**/*.css` - Stylesheets
- `public/**/*` - Static assets

**Verification workflow:**
1. PostToolUse hook detects frontend edit → outputs suggestion
2. Run `/launch` to start dev server and open browsers
3. Check for visual regressions, console errors, network issues
4. Document findings in response

**Exceptions (skip verification):**
- README/documentation changes
- Test file edits (`*.test.tsx`, `*.spec.tsx`)
- Type definition changes (`*.d.ts`)
- Config files (`*.config.ts`, `*.config.js`)

## Plan Files (MANDATORY)

All plans in `/plans/` MUST follow Plan Change Tracking:

**Required Frontmatter:**

```markdown
# Plan Title

**Created:** YYYY-MM-DD
**Last Updated:** YYYY-MM-DDTHH:MM:SSZ
**Status:** Pending Approval | In Progress | Completed
**Session:** {session-name}
```

**On every plan update:**

1. Remove ALL existing 🟧 (Orange Square) markers
2. Add 🟧 marker AT END of modified lines (not beginning - avoids breaking markdown)
3. Update "Last Updated" timestamp
4. If `USER:` comments found - process, remove, mark changed line with 🟧 at end

**Change Marker Format (Markdown-Safe Rules):**

```markdown
### Section Title 🟧    <- Correct: marker at END
Some changed content 🟧

🟧 ### Title            <- WRONG: breaks markdown heading
```

**Element-specific rules:**

| Element        | Rule                                                      | Example                              |
| -------------- | --------------------------------------------------------- | ------------------------------------ |
| Headings       | Marker at END of heading text                             | `### Section Title 🟧`             |
| Paragraphs     | Marker at END of line                                     | `Some changed content 🟧`          |
| Lists          | After item text                                           | `- Item description 🟧`            |
| Tables (cells) | INSIDE last cell, before closing `\|`                    | `\| value \| changed 🟧 \|`           |
| Table headers  | INSIDE last header cell, before closing `\|`             | `\| Col A \| Col B 🟧 \|`             |
| Separator rows | NEVER mark (`\|---\|---\|` rows)                           | Leave untouched                      |
| Code blocks    | NEVER inside fences -- mark the line ABOVE the code block | `Changed code below 🟧` then fence |
| Inline code    | Marker OUTSIDE backticks                                  | `` `value` 🟧 ``                     |

**Marker Lifecycle:**

1. **Strip first**: Remove ALL existing 🟧 markers from the entire document
2. **Then mark**: Add 🟧 only to lines changed in this edit pass
3. **Result**: Only current changes are marked; stale markers never accumulate

**Never ask user:**

- "How do you want to provide feedback?"
- "Should I proceed with the plan?"
- Any confirmation about plan workflow itself

**To process USER comments:** Run `/reviewplan`

**Emoji formatting (all plans):**

- Section headers get category emojis (🔒🏗️⚡📝🧪🎨)
- Table rows get status emojis (✅⚠️❌🟢🟡🔴)
- Decision tables use emoji-first compact format
- Comparison matrices use emoji column headers

## Mermaid Theme Standard

Claude Code Orange theme with rounded shapes (no diamonds):

```mermaid
%%{init: {'theme': 'dark', 'themeVariables': { 'primaryColor': '#0c0c14', 'primaryTextColor': '#fcd9b6', 'primaryBorderColor': '#c2410c', 'lineColor': '#ea580c', 'edgeLabelBackground': '#18181b'}}}%%
graph TD
    A["Node"] --> B(["Decision?"])
    style A fill:#0c0c14,stroke:#ea580c,stroke-width:3px,color:#fcd9b6
    style B fill:#18181b,stroke:#fb923c,stroke-width:3px,color:#fff7ed
```

**Shape Guide:**

- `["text"]` = Rectangle (actions, endpoints)
- `(["text"])` = Stadium/pill (decisions) - USE THIS instead of diamonds
- Avoid `{"text"}` diamonds - makes charts look like chess boards

**Color Palette:**

- Background: `#09090b` (near-black)
- Node fill: `#0c0c14` (dark navy)
- Decision fill: `#18181b` (zinc-900)
- Border/Lines: `#ea580c` (orange-600)
- Text: `#fcd9b6` (peach)
- Success nodes: `#16a34a` border (green)
- Debug nodes: `#8b5cf6` border (violet)

## Build Numbering Convention

Branch names include build IDs to track work across non-linear merges:

**Format:** `{type}/b{id}-{description}`

**Examples:**

- `feature/b101-user-auth` - Feature branch for build 101
- `fix/b102-login-bug` - Bugfix for build 102
- `refactor/b103-api-cleanup` - Refactor for build 103

**Build ID Assignment:**

- Build IDs are manually assigned (no auto-generation)
- Sequential but can have gaps (e.g., 101, 102, 105)
- Use next available number when creating branches
- Check existing branches to avoid conflicts

**Why Build IDs:**

- Track changes across non-linear merge history
- Link PR summaries to specific work items
- Enable automated CHANGELOG grouping
- Survive squash merges and rebases

**Branch Types:**

- `feature/` - New functionality
- `fix/` - Bug fixes
- `refactor/` - Code restructuring
- `docs/` - Documentation only
- `chore/` - Maintenance tasks

## CHANGELOG Automation

Automated changelog generation via GitHub Actions workflow (`claude.yml`):

### Workflow: @claude prepare → Review → Squash Merge → Auto CHANGELOG

1. **@claude prepare** - Bot creates PR with:

   - Aggregated commit summary (grouped by file)
   - Build ID extracted from branch name
   - Review checklist
2. **Review** - Team reviews PR via GitHub UI

   - Add comments, request changes
   - Approve when ready
3. **Squash Merge** - Merge PR to main:

   - GitHub Actions triggers automatically
   - Reads PR body for commit aggregation
   - Extracts build ID from branch name
   - Generates CHANGELOG entry
4. **Auto Release** - GitHub Actions creates tag + release:

   - Reads new version from package.json
   - Creates annotated git tag `v{version}`
   - Creates GitHub Release with CHANGELOG entry as notes
   - Skips if tag already exists
5. **CHANGELOG Entry Format:**

```markdown
## Build {id} | {version}

**Branch:** {type}/b{id}-{description}
**Merged:** {timestamp}

{pr_summary}

### Changes
- {file_section_1}
- {file_section_2}
- ...
```

6. **Release Format:**

- Tag: `v{version}` (e.g., `v1.2.3`)
- Title: `Release v{version}`
- Body: Extracted CHANGELOG entry for the build
- Created by: `github-actions[bot]`

### Key Points

**Worktree Behavior:**

- Working branches do NOT edit CHANGELOG directly
- All CHANGELOG updates happen via GitHub Actions post-merge
- Prevents merge conflicts and duplication

**Build ID Extraction:**

- Workflow parses branch name: `feature/b101-auth` → Build 101
- Used in CHANGELOG header and grouping
- Enables non-linear merge tracking

**Version Bumping:**

- Uses `scripts/aggregate-pr.py --bump` logic
- Follows semantic versioning (major.minor.patch)
- Auto-detects version type from PR labels or commit messages

**Manual Override:**

- Edit CHANGELOG directly on main if needed
- Use conventional commit format in PR title to influence versioning
- Add `skip-changelog` label to PR to bypass automation
- Add `skip-release` label to PR to bypass release creation

## 3-Layer Model Routing

Token-efficient model assignment via permanent, native mechanisms:

| Layer                            | Mechanism                                                      | Scope             | Effect                                 |
| -------------------------------- | -------------------------------------------------------------- | ----------------- | -------------------------------------- |
| **L1: Global Default**     | `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` in `settings.json` env | ALL subagents     | All forked skills run as Sonnet        |
| **L2: Skill Fork**         | `context: fork` in SKILL.md frontmatter                      | The skill itself  | Skill runs as Sonnet subagent (via L1) |
| **L3: Per-Agent Override** | `model="opus"` in `Task()` calls                           | Individual agents | Overrides L1 for agents needing Opus   |

### Skills Model Assignment

| Skill           | Fork?   | Model       | Rationale                                      |
| --------------- | ------- | ----------- | ---------------------------------------------- |
| `/start`      | No      | Opus (main) | Complex orchestration, spawns Opus agents (L3) |
| `/repotodo`   | No      | Opus (main) | Critical code changes across files             |
| `/reviewplan` | No      | Opus (main) | Spawns research agents                         |
| `/review`     | No fork | Opus (main) | Spawns Task agents with model="sonnet"         |
| `/commit`     | Fork    | Sonnet (L1) | Pattern matching, no code changes              |
| `/openpr`     | Fork    | Sonnet (L1) | Reads commits, generates PR body               |
| `/screen`     | Fork    | Sonnet (L1) | Screenshot management                          |
| `/youtube`    | Fork    | Sonnet (L1) | Transcription management                       |
| `/launch`     | Fork    | Sonnet (L1) | Browser verification                           |
| `/token`      | Fork    | Sonnet (L1) | Token status/refresh                           |

---

## Agent Shutdown Protocol

All team agents (IMPL, VERIFY+FIX, review) MUST handle shutdown gracefully:

When you receive a `shutdown_request` message (JSON with `type: "shutdown_request"`), respond by calling `SendMessage` with `type="shutdown_response"`, `request_id` from the message, and `approve=true`. This terminates your process. **Never** respond with "I can't exit" or "close the window" — always use the `SendMessage` tool.

## Skills & Infrastructure

See [USAGE.md](./USAGE.md) for complete reference:

- **Skill Commands:** `/start`, `/review`, `/commit`, `/openpr`, `/init-repo`, `/repotodo`, `/reviewplan`, `/launch`, `/screen`, `/youtube`, `/token`, `/rule`
- **Token Management:** 4-layer defense, troubleshooting
- **Ralph Architecture:** Defense-in-depth, push gate, VERIFY+FIX
- **Hook Registration:** Complete settings.json config
- **GitHub Actions:** Workflow setup, triggers, examples
- **Serena Tools:** Semantic code analysis workflows
