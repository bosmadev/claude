---
name: commit
description: Create commits with branch-aware naming ({branch}-{increment}). Reads from .claude/commit.md and generates .claude/pending-commit.md for review before committing.
user-invocable: true
context: fork
---

# Commit Workflow

**When invoked, immediately output:** `**SKILL_STARTED:** commit`

Create git commits with branch-aware naming and action verb bullet style.

## Usage

```
/commit                  - Generate .claude/pending-commit.md from .claude/commit.md
/commit confirm          - Execute the pending commit
/commit abort            - Cancel and delete .claude/pending-commit.md
/commit help             - Show this help
```

### Change Tracking Subcommands

```
/commit log <path> <action> <desc>  - Log a file change to .claude/commit.md
/commit show                         - Display current commit.md contents
/commit clear                        - Clear all pending changes
/commit summary                      - Generate AI summary of pending changes
```

| Subcommand | Arguments | Description |
|------------|-----------|-------------|
| `log` | `<path> <action> <desc>` | Log a file change (action: create/modify/delete) |
| `show` | none | Display contents of .claude/commit.md |
| `clear` | none | Clear all entries from .claude/commit.md |
| `summary` | none | Generate an AI summary of all pending changes |

## Help Command

When arguments equal "help":

```
/commit - Create commits with branch-aware naming

Usage:
  /commit [command]

Commands:
  (no args)        Generate .claude/pending-commit.md from .claude/commit.md
  confirm          Execute the pending commit
  abort            Cancel and delete .claude/pending-commit.md
  help             Show this help

Change Tracking:
  log <path> <action> <desc>   Log a file change to .claude/commit.md
  show                         Display current commit.md contents
  clear                        Clear all pending changes
  summary                      Generate AI summary of pending changes

Action Verbs (used in commit.md):
  Added      New files, features, or functionality
  Updated    Modifications to existing files
  Fixed      Bug fixes, error corrections
  Removed    Deleted files or removed features
  Improved   Enhancements, better UX, performance
  Changed    Altered existing behavior

Environment:
  check-env            Check .env encryption status
  encrypt              Run pnpm env:encrypt if dotenvx enabled

Note: If dotenvx is configured (env:encrypt in package.json),
.env files are automatically encrypted before commit generation.

Examples:
  /commit                    # Generate commit from change log
  /commit confirm            # Execute the commit
  /commit abort              # Cancel pending commit
  /commit log src/app.ts modify "Added new feature"  # Log a change
  /commit show               # View pending changes
  /commit clear              # Clear change log
  /commit summary            # Generate summary
```

## Naming Convention

Commits follow the format: `{branch}-{increment}`

| Branch | First Commit | Second Commit |
|--------|--------------|---------------|
| `main` | `main-1` | `main-2` |
| `b101` | `b101-1` | `b101-2` |
| `feature/login` | `feature-login-1` | `feature-login-2` |

## Branch Detection

The skill detects the current branch from two sources:

### 1. Git Branch (Primary)

```bash
git branch --show-current
```

### 2. Worktree Folder Name (Fallback)

For git worktrees, extracts branch from the folder name:

```
C:\Users\user\project\b101  -> branch: b101
C:\Users\user\gswarm-api\main -> branch: main
```

Detection logic:
```bash
# Get the worktree directory name
basename "$(git rev-parse --show-toplevel)"
```

## Workflow

### Phase 1: Generate Pending Commit

1. **Detect repository root**
   ```bash
   git rev-parse --show-toplevel
   ```

2. **Read change log** from `{repo-root}/.claude/commit.md`
   - If no commit.md exists, fallback to `git diff --stat`

3. **Detect branch**
   - Try `git branch --show-current`
   - If detached HEAD or empty, use worktree folder name

4. **Calculate increment**
   ```bash
   # Find last commit matching {branch}-{N} pattern
   git log --oneline --all | grep -E "^[a-f0-9]+ ${branch}-[0-9]+" | head -1
   # Extract N and increment
   ```

5. **Auto-encrypt .env files (if dotenvx configured)**
   ```bash
   # Check if project uses dotenvx
   if grep -q '"env:encrypt"' package.json 2>/dev/null; then
       echo "Detected dotenvx - encrypting .env files..."
       pnpm env:encrypt

       # Stage encrypted .env files (if any exist)
       git add .env .env.local .env.production .env.keys 2>/dev/null || true
   fi
   ```

   **Why auto-encrypt:**
   - Prevents blocked commits from env-check hook
   - Ensures .env files are always encrypted before staging
   - Runs silently if no dotenvx configured

6. **Generate .claude/pending-commit.md**:

```markdown
{branch}-{increment}

- Added new-file.ts
- Updated existing-file.ts
- Fixed bug in handler.ts

Extended description here if needed.

---

**Actions:**

- Run `/commit confirm` to create this commit
- Run `/commit abort` to cancel
- Edit this file to modify the commit message
```

**Note:** The format uses NO markdown headings - just plain text:
- **Line 1** → Commit subject (`{branch}-{increment}`)
- **Lines 2+** → Bullet list with action verbs (Added, Updated, Fixed, etc.)
- **After bullets** → Optional extended description (blank line, then body text)

Do NOT include markdown headings like `## Message`, `## Changes`, or `## Body`.

### Phase 2: Confirm Commit

When user runs `/commit confirm`:

1. **Read .claude/pending-commit.md**
2. **Parse simple format (no headings)**
   - **First line** = commit subject
   - **Everything after first blank line** = commit body (optional)

   Example pending-commit.md:
   ```
   main-42

   - Added auth.ts, jwt.ts, types/auth.ts
   - Updated middleware/index.ts
   ```
   Parsed as:
   - Subject: `main-42`
   - Body: `- Added auth.ts...` (everything after blank line)

3. **Validate all files are staged**
   ```bash
   git status --porcelain
   ```
4. **Check for unencrypted .env files (BLOCKING)**

   Before executing the commit, validate that no staged .env files are unencrypted when dotenvx is enabled:

   ```bash
   # Check if dotenvx is enabled (has env:encrypt script)
   if grep -q '"env:encrypt"' package.json 2>/dev/null; then
       # Get list of staged .env files
       staged_env=$(git diff --cached --name-only | grep -E '\.env')

       for file in $staged_env; do
           if [ -f "$file" ]; then
               # Check if file has dotenvx encryption header
               if ! head -1 "$file" | grep -q '#/---'; then
                   echo "BLOCKED: Unencrypted .env file staged: $file"
                   echo "Run: pnpm env:encrypt && git add $file"
                   exit 1
               fi
           fi
       done
   fi
   ```

   **If unencrypted .env files found:**
   - BLOCK the commit immediately
   - Display error: "BLOCKED: Unencrypted .env file staged: {filename}"
   - Instruct user: "Run `pnpm env:encrypt` then re-stage the files"
   - Do NOT proceed to execute the commit

5. **Execute the commit with Subject + Body**
   ```bash
   # IMPORTANT: Always include Body if present
   git commit -m "$(cat <<'EOF'
   {Subject}

   {Body}
   EOF
   )"
   ```
   **Note:** The commit message MUST include both Subject and Body separated by a blank line. Never omit the Body if it exists in pending-commit.md.

6. **Verify success**
   ```bash
   git log -1 --oneline
   ```
7. **Push to remote (ALWAYS)**
   After every successful commit, immediately push (non-force):
   ```bash
   git push origin HEAD
   ```
   - If push fails due to diverged history, report the error and suggest: `git pull --rebase origin <branch>` then retry push
   - **Never force push** — let the user resolve merge conflicts manually
   - This ensures commits are never stranded locally

8. **Clean up**
   - Delete `.claude/pending-commit.md`
   - Clear `.claude/commit.md` contents
   - Check for and offer to delete `.claude/pending-pr.md` if it exists
   - This prevents stale pending files from causing confusion in future commits

### Phase 3: Abort

When user runs `/commit abort`:

1. Delete `.claude/pending-commit.md`
2. Report cancellation
3. Keep `.claude/commit.md` intact for retry

## Action Verb Format

Commit.md entries use action verbs instead of conventional commit prefixes:

| Action Verb | When to Use | Example |
|-------------|-------------|---------|
| `Added` | New files, features, functionality | `- Added user authentication` |
| `Updated` | Modifications to existing files | `- Updated API endpoints` |
| `Fixed` | Bug fixes, error corrections | `- Fixed login validation` |
| `Removed` | Deleted files or removed features | `- Removed deprecated code` |
| `Improved` | Enhancements, better UX, performance | `- Improved query performance` |
| `Changed` | Altered existing behavior | `- Changed default timeout` |

## Auto-Detection of Action Verb

The change-tracker hook detects action type from git status:

| Git Status | Action Verb |
|------------|-------------|
| New file (untracked or staged new) | `Added` |
| Modified file | `Updated` |
| Deleted file | `Removed` |

For semantic context (Fixed, Improved, Changed), manually specify in descriptions.

## Implementation Details

### Get Last Commit Number

```bash
#!/bin/bash
branch="$1"
# Sanitize branch name for commit ID (replace / with -)
safe_branch=$(echo "$branch" | tr '/' '-')

# Search commit messages for pattern
last_num=$(git log --oneline -100 | grep -oE "^[a-f0-9]+ ${safe_branch}-([0-9]+)" | head -1 | grep -oE '[0-9]+$')

if [ -z "$last_num" ]; then
    echo 1
else
    echo $((last_num + 1))
fi
```

### Parse Commit Log

Read `.claude/commit.md` to extract:
- File list from "## Changes" section
- Summary from "## Summary" section
- Detect action verb from file patterns and git status

## Example Session

```
User: /commit

Claude: Generated .claude/pending-commit.md:

main-42

- Added auth.ts, jwt.ts, types/auth.ts
- Updated middleware/index.ts

Run `/commit confirm` to create this commit, or `/commit abort` to cancel.

User: /commit confirm

Claude: Commit created: main-42 (a1b2c3d)

Delete .claude/pending-commit.md and clear .claude/commit.md? (yes/no)

User: yes

Claude: Cleaned up commit files.
```

## Integration with Change Tracking

The change-tracker hook in `hooks/git.py` automatically logs file changes to `.claude/commit.md`:

1. **During development**: Changes are automatically logged to `.claude/commit.md` by the git hook
2. **When ready to commit**: Run `/commit` to generate .claude/pending-commit.md
3. **Review and adjust**: Edit the pending file if needed
4. **Commit**: Run `/commit confirm`
5. **Clean up**: Delete tracking files (see Post-Commit Cleanup below)

## Post-Commit Cleanup

After a successful commit, always clean up temporary pending files to prevent confusion:

### Files to Delete

| File | When to Delete |
|------|----------------|
| `.claude/pending-commit.md` | After `/commit confirm` succeeds |
| `.claude/pending-pr.md` | After PR is created via `/openpr` |
| `.claude/commit.md` | Clear contents after commit (keep file for future tracking) |

### Cleanup Commands

```bash
# Delete pending commit file
rm -f .claude/pending-commit.md

# Delete pending PR file (if exists)
rm -f .claude/pending-pr.md

# Clear commit tracking log (preserve file)
> .claude/commit.md
```

### Why Cleanup Matters

- Stale `.claude/pending-commit.md` files can cause confusion on next commit
- Leftover `.claude/pending-pr.md` files may contain outdated PR descriptions
- Old `.claude/commit.md` entries may accidentally be included in future commits

## Error Handling

| Error | Action |
|-------|--------|
| Not a git repo | Display error with instructions |
| No changes to commit | Show git status and suggest staging |
| No commit.md found | Fallback to git diff analysis |
| Detached HEAD | Use worktree folder name as branch |
| Pending commit exists | Ask to overwrite or abort |
| Unpushed commits exist | Push with `git push origin HEAD` before signaling done |
| Push rejected | Pull with rebase: `git pull --rebase origin main` then push |
| dotenvx detected but encrypt fails | Run manually with `pnpm env:encrypt` and check errors |
| Unencrypted .env staged | Encrypt first with `pnpm env:encrypt` |

## Safety Rules

- Never force push or modify history
- Always show preview before committing
- Preserve commit.md on abort (user may want to retry)
- Validate staged changes match commit.md before committing
- Use HEREDOC for commit messages to preserve formatting
- **Push commits before completion** (Ralph stop hook blocks on unpushed commits)
- **Encrypt .env files before committing** (env-check hook blocks unencrypted .env files)

## .env Encryption Pre-Check

Before generating `pending-commit.md`, the skill automatically encrypts `.env` files if dotenvx is configured.

### How dotenvx is Detected

1. Reads `package.json` in the repository root
2. Checks for `scripts.env:encrypt` property
3. If present, encryption is enabled for the project

```json
{
  "scripts": {
    "env:encrypt": "dotenvx encrypt"
  }
}
```

### When Encryption Runs

Encryption runs **before** generating `.claude/pending-commit.md`:

1. User runs `/commit`
2. Skill detects dotenvx via `package.json`
3. Runs `pnpm env:encrypt` (or `npm run env:encrypt`)
4. Stages encrypted `.env` files
5. Generates `pending-commit.md` with encrypted files included

### Files That Get Encrypted

All `.env*` files in the repository root:

| File Pattern | Example |
|--------------|---------|
| `.env` | Main environment file |
| `.env.local` | Local overrides |
| `.env.development` | Development settings |
| `.env.production` | Production secrets |
| `.env.staging` | Staging environment |
| `.env.test` | Test configuration |

**Note:** Only unencrypted files are processed. Already-encrypted files (containing `#/---` header) are skipped.

### How to Skip Encryption

To disable automatic encryption:

1. **Remove the script** from `package.json`:
   ```json
   {
     "scripts": {
       // Remove or comment out this line
       // "env:encrypt": "dotenvx encrypt"
     }
   }
   ```

2. **Alternative**: Don't stage `.env` files:
   ```bash
   git reset HEAD .env .env.local
   ```

---

## .env Encryption Pre-Commit Check

If the project uses dotenvx (has `env:encrypt` script in package.json), the commit will be **blocked** if any staged `.env` files are unencrypted.

### How It Works

1. Hook checks if `package.json` has `env:encrypt` script
2. If yes, scans staged `.env*` files for encryption header (`#/---`)
3. Blocks commit if unencrypted .env files are found

### Fix Blocked Commits

```bash
# Encrypt all .env files
pnpm env:encrypt

# Re-stage the encrypted files
git add .env .env.local .env.production

# Retry commit
git commit -m "message"
```

### Skip Check (Not Recommended)

The check only applies to projects with dotenvx configured. To skip:
- Remove `env:encrypt` script from package.json (disables check permanently)
- Or don't stage .env files (commit other files first)

## Dotenvx Integration Workflow

When dotenvx is configured in the project:

### Detection
The skill checks `package.json` for `env:encrypt` script at two points:
1. **Pre-generation**: Before creating pending-commit.md
2. **Pre-commit**: Before executing `git commit`

### Automatic Encryption
If dotenvx is detected and unencrypted .env files exist:
1. Runs `pnpm env:encrypt` automatically
2. Re-stages the encrypted files
3. Proceeds with commit generation

### Manual Override
To skip automatic encryption:
- Remove `env:encrypt` from package.json scripts
- Or use `.env.example` files (ignored by encryption check)

### Verification
Check encryption status: `python commit-helper.py check-env .`

---

## Serena-Powered Semantic Diff Analysis

Leverage Serena MCP tools for richer commit message generation.

### Enhanced Diff Analysis Workflow

Before generating commit message:

```
1. For each changed file:
   mcp__serena__get_symbols_overview(relative_path=<file>)
   → Identify which symbols were modified

2. For each modified symbol:
   mcp__serena__find_referencing_symbols(name_path=<symbol>)
   → Identify impact scope (how many callers affected)
```

### Impact-Aware Commit Messages

Serena enables more descriptive bullet entries:

| Without Serena | With Serena |
|----------------|-------------|
| `- Updated auth.ts` | `- Fixed token validation in validateJWT (affects 5 endpoints)` |
| `- Updated api.ts` | `- Changed handleRequest to processAPICall (12 callers updated)` |
| `- Added UserAvatar.tsx` | `- Added UserAvatar component with Suspense boundary` |

### Semantic Commit Body

Use Serena to generate detailed commit body:

```markdown
## Changes

### Modified Symbols
- `validateToken` → Renamed to `verifyJWT`
- `AuthMiddleware.handle` → Added rate limiting check

### Impact Analysis
- 5 API endpoints affected
- 3 test files updated
- No breaking changes (backward compatible)

### Files
- src/auth/jwt.ts (modify)
- src/middleware/auth.ts (modify)
- tests/auth.test.ts (modify)
```

### Serena Memory for Commit Context

Store commit conventions for consistency:

```
mcp__serena__write_memory("commit-conventions", <project commit style>)
mcp__serena__read_memory("commit-conventions") - Recall for message generation
```
