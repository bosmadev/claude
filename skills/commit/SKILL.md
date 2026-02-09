---
name: commit
description: Two-phase commit workflow - generate pending-commit.md for review, then confirm to execute. Uses scope-prefix style with auto-staging and tracked changes.
user-invocable: true
context: fork
argument-hint: "[confirm|abort|show|clear|log|summary|help]"
---

# Commit Workflow

## EXECUTE IMMEDIATELY — DO NOT ANALYZE

**CRITICAL: When `/commit` is invoked with NO arguments, you MUST execute the Phase 1 workflow below IMMEDIATELY. Do NOT research the codebase, do NOT analyze the skill architecture, do NOT write a report about the commit system. JUST DO THE STEPS.**

**Output first:** `**SKILL_STARTED:** commit`

**Then IMMEDIATELY execute these steps in order:**

1. Run `git rev-parse --show-toplevel` to find repo root
2. Run `git status --porcelain` to show what will be staged
3. Run `git add -A` to stage everything
4. Run `git diff --cached --stat` to show staged changes
5. Read `.claude/commit.md` for tracked changes
6. Analyze ALL staged changes (read diffs, understand what changed)
7. **Auto Build ID (main branch only):** Check current branch with `git branch --show-current`. If `main` or `master`, read `CHANGELOG.md` from repo root, extract highest Build N via regex `/Build\s+(\d+)/g`, and set `nextBuildId = max(N) + 1`. If no CHANGELOG or no Build entries, start at `Build 1`.
8. Generate a scope-prefix subject line (feat/fix/refactor/cleanup/config/docs/test/perf). **If on main/master, prepend Build ID:** `Build {nextBuildId}: scope: description`
9. Generate categorized bullet points describing the changes
10. Write the subject + bullets to the `## Ready` section of `.claude/commit.md`
11. Clear the `## Pending` section
12. Display the generated commit message as preview
13. Tell user: "Run `/commit confirm` to execute"

**STOP. Execute the steps above NOW. Do not read further until done.**

---

## Subcommand Reference

| Command | Action |
|---------|--------|
| `/commit` (no args) | Execute Phase 1 above — stage, generate, preview |
| `/commit confirm` | Execute the commit and push |
| `/commit abort` | Cancel pending commit |
| `/commit help` | Show help text |
| `/commit log <path> <action> <desc>` | Log a file change |
| `/commit show` | Display commit.md contents |
| `/commit clear` | Clear all pending changes |
| `/commit summary` | Generate AI summary |

## Naming Convention

Commits use scope-prefix style — no branch numbering. Squash-merge collapses them anyway.

**Format (feature branches):** `scope: descriptive summary`

**Format (main/master):** `Build {N}: scope: descriptive summary`

### Auto Build ID Injection (Main Branch Only)

When committing directly to `main` or `master`, the skill automatically:

1. Reads `CHANGELOG.md` from repo root
2. Finds highest existing Build N via regex `/Build\s+(\d+)/g`
3. Increments to `Build N+1`
4. Prepends to subject: `Build 3: feat: add auth`

**Why:** The `changelog.ts` GitHub Action requires `Build N` in the commit subject to trigger CHANGELOG + version bump automation. Feature branches get Build IDs from their branch name (`feature/b101-auth`) via the `/openpr` squash merge.

| Branch | Build ID Source | Format |
|--------|----------------|--------|
| `main`/`master` | Auto from CHANGELOG.md | `Build N: scope: desc` |
| `feature/b101-*` | Branch name via `/openpr` | `scope: desc` (PR adds Build ID) |
| Other branches | None | `scope: desc` |

**Fallback:** If CHANGELOG.md doesn't exist or has no Build entries, starts at `Build 1`.

| Scope | When to Use | Example |
|-------|-------------|---------|
| `feat` | New features or functionality | `feat: add user avatar component` |
| `fix` | Bug fixes | `fix: resolve token expiry race condition` |
| `refactor` | Code restructuring, no behavior change | `refactor: extract auth middleware` |
| `cleanup` | Removing dead code, simplifying | `cleanup: remove unused browser integrations` |
| `docs` | Documentation only | `docs: update API endpoint reference` |
| `config` | Configuration, CI, tooling | `config: add Haiku model to CI workflow` |
| `test` | Test additions or fixes | `test: add E2E tests for checkout flow` |
| `perf` | Performance improvements | `perf: parallelize git status queries` |

For large commits spanning multiple scopes, pick the dominant one or use a general scope:
- `config: Windows migration + Serena workflow integration`
- `cleanup: browser removal + statusline restructure`

## File Precedence & Migration

The skill has evolved to use a **single source of truth**: `.claude/commit.md`

| File | Status | Purpose | When to Delete |
|------|--------|---------|----------------|
| `.claude/commit.md` | **Primary** | Single source - `## Pending` (hook tracking) + `## Ready` (user message) | Never (only clear sections) |
| `.claude/pending-commit.md` | **Deprecated/Legacy** | Old format from commit-helper.py script | **After every `/commit confirm`** |
| `.claude/pending-pr.md` | Optional | PR message preparation (separate workflow) | User's choice |

**Migration Notes:**
- If both `commit.md ## Ready` and `pending-commit.md` exist, `commit.md ## Ready` takes precedence
- Always delete `pending-commit.md` after successful commit to prevent stale content
- The commit-helper.py script may still generate `pending-commit.md` - ignore it if `commit.md` exists

## Commit.md File Structure (Single File with Sections)

The `.claude/commit.md` file uses a two-section structure:

```markdown
# .claude/commit.md

## Pending
<!-- Auto-written by change-tracker hook - file changes detected during development -->
- Modified: src/auth.ts
- Added: src/utils.ts
- Deleted: src/old-file.ts

## Ready
<!-- Generated by /commit: subject + blank line + bullets -->
feat: add OAuth2 authentication

- Added OAuth2 authentication with Google provider
- Fixed token refresh race condition
- Updated API documentation
```

| Section | Who Writes | When Read |
|---------|-----------|-----------|
| `## Pending` | change-tracker hook (hooks/git.py) | For reference only |
| `## Ready` | User (you) | By `/commit` for commit message |

**Key benefits:**
- Your bullet points preserved in `## Ready` section - survives commit failures
- Hook tracking separate in `## Pending` section - auto-populated reference
- Single file - no confusion about which file to edit
- Clear separation - hooks write to `## Pending`, you write to `## Ready`

**Hook integration:**
The change-tracker hook in `hooks/git.py` automatically writes file changes to the `## Pending` section during development. When you're ready to commit, you create bullet points in the `## Ready` section describing the changes at a higher level.

## Workflow

### Phase 1: Generate Pending Commit (`/commit`)

**Single command does everything up to confirmation:**

1. **Detect repository root**
   ```bash
   git rev-parse --show-toplevel
   ```

2. **Auto-stage all changes (with file preview)**

   Show the user what files will be staged before proceeding:
   ```bash
   # Show unstaged changes
   git status --porcelain
   ```

   If new (untracked) files exist, list them for transparency. Then stage all:
   ```bash
   git add -A
   ```

   **Note:** `git add -A` stages all changes including new files. The change-tracker hook ensures visibility by logging all modifications to commit.md.

3. **Read commit.md and merge sections**
   - Read `## Pending` section (hook-tracked changes)
   - Read `## Ready` section (user additions, if any)
   - Merge into final bullet list for `## Ready`

4. **Generate scope-prefix subject**
   - Analyze bullet points for dominant scope (feat/fix/refactor/cleanup/config/docs/test/perf)
   - Generate descriptive summary

5. **Auto-encrypt .env files (if dotenvx configured)**
   ```bash
   if grep -q '"env:encrypt"' package.json 2>/dev/null; then
       # Run with 30s timeout to prevent hanging
       timeout 30 pnpm env:encrypt || {
           echo "Warning: env:encrypt timed out after 30s"
           echo "Run manually: pnpm env:encrypt"
           exit 1
       }
       git add .env .env.local .env.production .env.keys 2>/dev/null || true
   fi
   ```

   **Timeout handling:** If `pnpm env:encrypt` hangs, it times out after 30 seconds and the commit is aborted with an error message. The user should run encryption manually and investigate the hang.

6. **Update commit.md**
   - Move generated content to `## Ready` section
   - Clear `## Pending` section
   - This makes `## Ready` the single source of truth

7. **Show preview**
   - Display generated commit message
   - Prompt: "Run `/commit confirm` to execute"

**No back-and-forth** — single `/commit` prepares everything.

### Phase 2: Confirm Commit

When user runs `/commit confirm`:

1. **Detect commit message source (with validation)**
   ```bash
   # Check which file has the commit message
   COMMIT_SOURCE=""

   if [ -f .claude/commit.md ] && grep -q "^## Ready" .claude/commit.md; then
       # Check if Ready section has content (not just the header)
       if grep -A 999 "^## Ready" .claude/commit.md | tail -n +2 | grep -q "[^[:space:]]"; then
           COMMIT_SOURCE="commit.md"
           echo "Using commit message from: commit.md ## Ready section"
       fi
   fi

   if [ -z "$COMMIT_SOURCE" ] && [ -f .claude/pending-commit.md ]; then
       COMMIT_SOURCE="pending-commit.md"
       echo "Warning: Using legacy pending-commit.md (will be deleted after commit)"
   fi

   if [ -z "$COMMIT_SOURCE" ]; then
       echo "Error: No commit message found in commit.md ## Ready or pending-commit.md"
       exit 1
   fi
   ```

2. **Re-read the detected source file**
3. **Parse `## Ready` section (if using commit.md) or entire content (if using pending-commit.md)**
   - Extract bullet points
   - Generate subject line from content
   - Use bullet points as commit body

   Example from `## Ready`:
   ```
   - Added OAuth2 authentication with Google provider
   - Fixed token refresh race condition
   ```

   Generates commit:
   - Subject: `feat: add OAuth2 authentication and fix token refresh`
   - Body: The bullet points from `## Ready`

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
   # Push with 60s timeout for slow networks
   timeout 60 git push origin HEAD || {
       EXIT_CODE=$?
       if [ $EXIT_CODE -eq 124 ]; then
           echo "Error: Push timed out after 60s"
           echo "Check network connection or try: git push origin HEAD"
           exit 1
       else
           echo "Error: Push failed (exit code $EXIT_CODE)"
           # Check if remote is configured
           if ! git remote get-url origin &>/dev/null; then
               echo "No remote 'origin' configured"
               echo "Add remote: git remote add origin <url>"
           else
               echo "Possible diverged history - try: git pull --rebase origin $(git branch --show-current)"
           fi
           exit 1
       fi
   }
   ```

   **Error handling:**
   - **No remote configured:** If `origin` doesn't exist, instruct user to add remote: `git remote add origin <url>`
   - **Timeout:** If push hangs for >60s, abort and suggest manual push
   - **Diverged history:** If push fails due to conflicts, suggest `git pull --rebase`
   - **Never force push** — let the user resolve merge conflicts manually
   - This ensures commits are never stranded locally

8. **Clean up**
   - Clear both `## Pending` and `## Ready` sections in `.claude/commit.md`
   - Keep the file structure intact:
     ```markdown
     # Pending Changes

     ## Pending

     ## Ready
     ```
   - **Delete `.claude/pending-commit.md` if it exists** (prevents stale legacy content)
   - Check for and offer to delete `.claude/pending-pr.md` if it exists
   - This prevents stale content from being included in future commits

   **Cleanup commands:**
   ```bash
   # Clear commit.md sections
   cat > .claude/commit.md << 'EOF'
   # Pending Changes

   ## Pending

   ## Ready
   EOF

   # Delete legacy pending-commit.md
   rm -f .claude/pending-commit.md

   # Optionally remove pending-pr.md
   if [ -f .claude/pending-pr.md ]; then
       echo "Note: .claude/pending-pr.md still exists (for PR workflow)"
   fi
   ```

### Phase 3: Abort

When user runs `/commit abort`:

1. Report cancellation
2. Keep `.claude/commit.md` intact (user may want to retry)
3. Optionally offer to clear the `## Ready` section

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

## Categorized Bullet Format

For commits with many files (10+), use **categorized bullets** with bold labels and file counts:

```markdown
## Ready
config: Windows migration, security hooks, init-repo skill

- **Category Name (N files):** Verbose description explaining purpose and function, not just file listing
- **Another Category (N files):** Detailed purpose statement with "for [reason]" clarifications
```

### Category Examples

| Category | When to Use | Example |
|----------|-------------|---------|
| **Scripts Removal** | Deleting multiple related files | `- **Linux Scripts Removal (13 files):** Removed legacy Linux-specific scripts after Windows migration including systemd services for token refresh, bash hooks for auto-allow, and shell utilities for status display` |
| **Hooks Added** | New hook files | `- **Security Hooks Added (4 files):** Created background-scanner.py for automated security scanning, sandbox-boundary.py for execution boundary enforcement, emergency-stop.py for critical halt mechanism, security-gate.py for pre-operation validation` |
| **Skills Updated** | Multiple skill changes | `- **Skills Updated (8 modified):** Enhanced commit skill with categorized bullets, launch skill with browser fallback chain, openpr skill with build ID extraction, repotodo skill with verification mode` |
| **Config Files** | Configuration changes | `- **Config Files Updated (3):** Updated settings.json with hook registrations for Ralph protocol, .gitignore with pending-commit patterns, .claude.json with Windows-specific paths` |
| **Core Scripts** | Main codebase scripts | `- **Core Scripts Updated (3):** Enhanced git.py with change-tracker hook for commit.md logging, guards.py with skill-parser validation, ralph.py with agent-tracker performance metrics` |

### Rules

1. **Bold the category label** with `**Label (N files):**`
2. **Include file count** in parentheses
3. **Describe purpose/function** using "for [purpose]" pattern, NOT just file names
4. **Explain WHY** changes were made, not just WHAT files changed
5. **Group by feature/purpose**, not by file type
6. **Be comprehensive** — mention all significant changes, don't truncate
7. **Use verbose descriptions** — file names alone are not sufficient
8. **Use action + purpose format** — "Created X for Y", "Enhanced X with Y", "Removed X after Y"
9. **Never just list file names** — Always include what each file/change accomplishes

### Verbose Format Examples

**BAD (lazy file listing):**
```markdown
- **Hooks Added (4 files):** background-scanner.py, sandbox-boundary.py, emergency-stop.py, security-gate.py
- **Scripts Removed (13 files):** Deleted .linux/hooks/*, .linux/scripts/*
- **Config Updated (3 files):** settings.json, .gitignore, .claude.json
```

**GOOD (verbose with purpose):**
```markdown
- **Security Hooks Added (4 files):** Created background-scanner.py for automated security scanning, sandbox-boundary.py for execution boundary enforcement, emergency-stop.py for critical halt mechanism, security-gate.py for pre-operation validation
- **Linux Scripts Removed (13 files):** Deleted .linux/hooks/* and .linux/scripts/* after Windows migration - statusline moved to scripts/statusline.py, token management unified in scripts/claude-github.py
- **Configuration Updated (3 files):** Enhanced settings.json with hook registrations for security gates, updated .gitignore to exclude browser cache directories, added .claude.json model routing for 3-layer model assignment
```

### Mixed Changes Example

For commits with both categorized sections (10+ files) and simple changes (1-2 files), combine both formats:

```markdown
## Ready
refactor: Windows migration and commit workflow update

- **Security Hooks Added (4 files):** Created background-scanner.py for automated security scanning, sandbox-boundary.py for execution boundary enforcement, emergency-stop.py for critical halt mechanism, security-gate.py for pre-operation validation
- **Linux Scripts Removed (13 files):** Deleted .linux/hooks/* and .linux/scripts/* after Windows migration
- Fixed typo in README.md documentation header
- Updated package.json scripts to use Windows-compatible paths
```

**Guideline:** Use categorized format for groups of 3+ related files. Use simple bullets for standalone changes (1-2 files). Mix both in the same commit when appropriate.

### Small Commits (< 10 files)

For smaller commits, simple bullets without categories are fine:

```markdown
## Ready
fix: resolve token expiry race condition

- Fixed validateJWT to handle expired refresh tokens
- Updated middleware timeout from 30s to 60s
- Added retry logic for auth failures
```

## Auto-Detection of Action Verb

The change-tracker hook detects action type from git status:

| Git Status | Action Verb |
|------------|-------------|
| New file (untracked or staged new) | `Added` |
| Modified file | `Updated` |
| Deleted file | `Removed` |

For semantic context (Fixed, Improved, Changed), manually specify in descriptions.

## Implementation Details

### Parse Commit Log

Read `.claude/commit.md` to extract:
- Bullet points from `## Ready` section (user-written commit message)
- File list from `## Pending` section (for reference only)
- Detect action verb and scope from `## Ready` bullet points

## Example Session

```
User: /commit

Claude: Staged 12 files. Generated commit:

feat: add JWT authentication with refresh token support

- **Auth Module Added (3 files):** Created auth.ts for session management, jwt.ts for token signing/verification with RS256, types/auth.ts for TypeScript interfaces
- **Middleware Updated (2 files):** Enhanced middleware/index.ts with auth guards, added middleware/rateLimit.ts for brute-force protection
- **Config Updated (2 files):** Added JWT secrets to .env.example, updated tsconfig.json with strict null checks
- **Tests Added (3 files):** Created auth.test.ts for unit tests, jwt.test.ts for token lifecycle, e2e/login.test.ts for integration

Run `/commit confirm` to execute.

User: /commit confirm

Claude: Commit created: feat: add JWT authentication with refresh token support (a1b2c3d)
Pushed to origin/feature/auth.
```

## Integration with Change Tracking

The change-tracker hook in `hooks/git.py` automatically logs file changes to the `## Pending` section:

1. **During development**: Changes are automatically logged to `.claude/commit.md ## Pending` by the git hook
2. **Prepare commit message**: Review `## Pending` section and write high-level bullet points in `## Ready` section
3. **Generate commit**: Run `/commit` to see the generated commit message
4. **Commit**: Run `/commit confirm` to execute the commit
5. **Clean up**: Both sections are cleared after successful commit

## Post-Commit Cleanup

After a successful commit, always clean up ALL commit-related files to prevent stale content:

### Files to Clean

| File | Action | When |
|------|--------|------|
| `.claude/commit.md` | Clear both `## Pending` and `## Ready` sections | After `/commit confirm` succeeds |
| `.claude/pending-commit.md` | **DELETE entirely** | After `/commit confirm` succeeds |
| `.claude/pending-pr.md` | Optionally delete | User's choice (separate PR workflow) |

### Cleanup Commands

```bash
# Clear commit.md sections but keep structure
cat > .claude/commit.md << 'EOF'
# Pending Changes

## Pending

## Ready
EOF

# Delete legacy pending-commit.md (prevents stale content)
rm -f .claude/pending-commit.md

# Optionally handle pending-pr.md
if [ -f .claude/pending-pr.md ]; then
    echo "Note: .claude/pending-pr.md exists (for PR workflow)"
    echo "Delete? (y/n)"
fi
```

### Why Cleanup Matters

- **Stale commit.md content**: Content in `## Ready` will be included in the next commit if not cleared
- **Legacy pending-commit.md**: If not deleted, may cause confusion about which file is the source of truth
- **Old pending entries**: File entries in `## Pending` may cause confusion about what's actually changed
- **File precedence**: Only commit.md should exist after cleanup - pending-commit.md is deprecated
- Keeping clean state makes the next development cycle unambiguous

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
| Duplicate content in commit.md | Remove duplicates before commit |
| Empty ## Ready section | Abort and prompt user to add content |
| Missing subject line | Generate from bullets or abort |
| User edited file after /commit | Use edited version (re-read fresh) |
| Both commit.md and pending-commit.md exist | Prefer commit.md ## Ready, warn about pending-commit.md |
| pending-commit.md used instead of commit.md | Warn user about legacy format, delete after commit |

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
Check encryption status: `python C:/Users/Dennis/.claude/skills/commit/scripts/commit-helper.py check-env .`

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
