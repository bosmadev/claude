---
name: openpr
description: Create PR with squashed commits and auto-generated summary
argument-hint: "[confirm|update|merge|base-branch|help]"
user-invocable: true
context: fork
---

# Open PR Workflow

**When invoked, immediately output:** `**SKILL_STARTED:** openpr`

Create a pull request with squashed commits and auto-generated summary.

**Key integration:** Uses `~/.claude/scripts/aggregate-pr.py` for commit aggregation.

**Why local aggregation?**
- Saves GitHub Actions minutes (no need for @claude prepare workflow)
- Faster feedback - immediate PR body preview in .claude/pending-pr.md
- Consistent formatting between local and CI environments
- Works offline/without GitHub Actions setup

## Help Command

When arguments equal "help":

```
/openpr - Squash commits and create a pull request

Usage:
  /openpr [base-branch]
  /openpr confirm

Commands:
  (no args)        Auto-detect target branch, generate preview
  confirm          Squash + create PR (uses existing pending-pr.md or generates fresh)
  [branch]         Create PR targeting specified branch
  help             Show this help

Branch Hierarchy (auto-detected when no base-branch given):
  *-night-dev branches → PR targets main (nightshift agents)
  *-dev branches       → PR targets main (Build N+1 from CHANGELOG)
  feature/* branches   → PR targets {repo}-dev (no Build ID)
  anything else        → PR targets {repo}-dev if exists, else main

Workflow:
  1. Auto-detects target branch from hierarchy
  2. Checks if branch is behind target — auto-rebases if needed
  3. Runs aggregate-pr.py to generate unified PR body
  4. Shows preview, asks for confirm
  5. On confirm: pushes individual commits, creates PR (no squash)
  6. /commit auto-updates PR body after each push
  7. /openpr merge squash-merges with crafted commit message

PR Format:
  dev→main:     Title: "Build {N+1}", Build ID from CHANGELOG
  feature→dev:  Title: conventional commit summary, no Build ID

Subcommands:
  /openpr              # Preview + create PR
  /openpr confirm      # Create PR directly (skip preview)
  /openpr update       # Regenerate PR body with latest commits
  /openpr merge        # Squash merge the open PR
  /openpr main         # Force PR to main
  /openpr help         # Show this help
```

---

## Arguments

**$ARGUMENTS**: "$ARGUMENTS"

Parse arguments:
- `(no args)`: Generate preview, ask for confirm
- `confirm`: Push individual commits + create PR directly (skip preview)
- `update`: Regenerate PR body for existing open PR with latest commits
- `merge`: Squash merge open PR with unified format commit message
- `[base-branch]`: Target branch for PR (auto-detected if omitted)
- `help`: Show usage information

## Branch Hierarchy Detection

When no base branch is explicitly provided, auto-detect using this logic:

```
Current Branch                   → Target Base Branch
────────────────────────────────────────────────────────
*-night-dev (e.g. gswarm-night-dev) → main
*-dev (e.g. cwchat-dev)             → main
feature/*, anything else            → {repo}-dev (if exists on remote, else main)
main/master                         → BLOCKED (abort with error)
```

**Detection steps:**

1. If user provided a base branch arg → use it directly
2. Get current branch: `git branch --show-current`
3. If current branch ends with `-night-dev` → base = `main` (nightshift branch)
4. Else if current branch ends with `-dev` → base = `main`
5. Else → check if `{repo}-dev` exists on remote:
   ```bash
   REPO=$(basename "$(git rev-parse --show-toplevel)")
   DEV_BRANCH="${REPO}-dev"
   git ls-remote --heads origin "${DEV_BRANCH}" | grep -q "${DEV_BRANCH}"
   ```
   - If exists → base = `{repo}-dev`
   - If not → base = `main` (with info message: "No {repo}-dev found, targeting main")

**Output the detected target:**
```
Current branch: {branch} → Target: {base}
```

## Pre-PR Sync Check

Before generating the PR, ensure the branch is up-to-date with the target:

```bash
BASE_BRANCH="${BASE_BRANCH}"  # from hierarchy detection above
git fetch origin "${BASE_BRANCH}"
BEHIND=$(git rev-list --count HEAD..origin/${BASE_BRANCH})
```

**If behind > 0:**
```
⚠️  Branch is ${BEHIND} commits behind origin/${BASE_BRANCH}
Rebasing on origin/${BASE_BRANCH}...
```

```bash
git rebase origin/${BASE_BRANCH}
```

- If rebase succeeds: `✓ Rebase successful` → continue
- If rebase conflicts: abort rebase and show resolution instructions:
  ```
  ✗ Rebase failed due to conflicts.

  To resolve manually:
    git rebase origin/${BASE_BRANCH}
    # Fix conflicts in each file
    git add <resolved-files>
    git rebase --continue

  Then run /openpr again.
  ```
  Abort with: `git rebase --abort` and cancel PR.

**If behind = 0:** `✓ Branch is up to date with origin/${BASE_BRANCH}` → continue

## Error Handling Examples

### Example 1: PR Already Exists

```
User: /openpr

Claude: Running aggregate-pr.py...
Squashing commits...
Creating pull request...

Error: A pull request already exists for this branch.

Existing PR: https://github.com/user/repo/pull/42 (Open)
Title: Build 101
Created: 2 days ago

Would you like to:
1. Update the existing PR description
2. Close the existing PR and create a new one
3. Cancel

User: 1

Claude: Updating PR #42 description...
Done! PR updated with latest changes.
```

### Example 2: Push Rejected (Diverged History)

```
User: /openpr confirm

Claude: Squashing commits...
Pushing to origin...

Error: Push rejected - remote branch has commits not present locally.

This usually happens when:
- Someone else pushed to your branch
- You rebased locally but remote has the old commits

Recommended fix:
git pull --rebase origin claude-dev
# Resolve any conflicts
/openpr confirm  # Try again

Or force push (CAUTION - overwrites remote):
git push origin HEAD --force-with-lease

Cancel PR creation? (yes/no)

User: yes

Claude: PR creation cancelled. Please resolve the diverged history and try again.
```

### Example 3: No Commits to Include

```
User: /openpr

Claude: Checking for commits...

Error: No commits found to include in PR.

Current branch: claude-dev
Base branch: main
Commits ahead: 0

Possible causes:
- All commits have already been merged
- Branch is up to date with main
- You're on the main branch (use a dev branch instead)

Check your branch: git log main..HEAD
```

## Pre-flight Checks

### 1. Verify Git Repository

```bash
git rev-parse --is-inside-work-tree 2>/dev/null || echo "NOT_A_REPO"
```

If not a git repo, abort with: "Error: Not inside a git repository."

### 2. Get Current Branch

```bash
BRANCH=$(git branch --show-current)
echo "$BRANCH"
```

If on `main` or `master`, abort with: "Error: Cannot create PR from main/master branch. Switch to a dev branch first (e.g., claude-dev, pulsona-dev)."

### 3. Extract Build Number (Conditional)

Build ID is **only injected for PRs targeting `main`** (i.e., `*-dev` → `main` PRs).

| Source Branch     | Target         | Build ID?                                     |
| ----------------- | -------------- | --------------------------------------------- |
| `*-dev`         | `main`       | Yes — `Build N+1` from CHANGELOG            |
| `feature/*`     | `{repo}-dev` | No — conventional commit summary as PR title |
| Legacy `b{N}-*` | any            | Yes — from branch name (backward compat)     |

**When Build ID applies** (target = `main`):
1. **Branch name pattern:** `b101`, `feature/b42-auth` → numeric ID from name
2. **CHANGELOG.md + git log auto-detect:** Run this exact bash command:
   ```bash
   CL=$(grep '^## ' CHANGELOG.md 2>/dev/null | grep -oP 'Build \K\d+' | sort -rn | head -1); GL=$(git log --oneline -50 2>/dev/null | grep -oP 'Build \K\d+' | sort -rn | head -1); MAX=$(echo -e "${CL:-0}\n${GL:-0}" | sort -rn | head -1); echo $((MAX + 1))
   ```
   **CRITICAL:** Use bash output as-is. Checks BOTH CHANGELOG headings AND git log (covers race between push and GitHub Action updating CHANGELOG).
3. **Fallback:** `Build 1` if no CHANGELOG or no existing builds

PR Title: `Build {number}` (e.g., "Build 3")

**When Build ID does NOT apply** (target = `{repo}-dev`):
- PR Title = conventional commit summary from aggregated commits
- No `Build N` prefix in squash commit message
- aggregate-pr.py generates title from commit types (e.g., "feat: auth + fix: parser")

```bash
BRANCH=$(git branch --show-current)
# aggregate-pr.py handles all detection logic automatically
# Pass --no-build-id flag when targeting non-main branches
if [ "${BASE_BRANCH}" != "main" ] && [ "${BASE_BRANCH}" != "master" ]; then
  EXTRA_FLAGS="--no-build-id"
fi
```

**Typical workflows:**
- `cwchat-dev` → `/openpr` → targets `main` → `Build 3` → CHANGELOG entry
- `feature/auth` → `/openpr` → targets `cwchat-dev` → "feat: auth system" → no CHANGELOG

### 4. Check for Unpushed Commits

```bash
git log @{u}..HEAD --oneline 2>/dev/null || git log --oneline
```

If no commits to include, abort with: "Error: No commits found to include in PR."

---

## Phase 1: Generate .claude/pending-pr.md

### 1. Run aggregate-pr.py

Use the aggregation script to generate the unified format (same output serves as commit message, PR body, and preview).

```bash
# BASE_BRANCH already set from hierarchy detection
cd "$(git rev-parse --show-toplevel)"

python ~/.claude/scripts/aggregate-pr.py "${BASE_BRANCH}" > .claude/pending-pr.md 2>&1
```

### 2. Verify Script Success

```bash
if [ ! -s .claude/pending-pr.md ]; then
  echo "Error: Failed to generate PR summary. Check that you have commits to include."
  exit 1
fi
```

### 3. Append Edit Note

```bash
echo "" >> .claude/pending-pr.md
echo "---" >> .claude/pending-pr.md
echo '**Note:** Edit this file as needed. Run `/openpr` again or `/openpr confirm` to squash and create the PR.' >> .claude/pending-pr.md
```

### 4. Prompt User

After creating `.claude/pending-pr.md`, display its contents and:

```
Created: .claude/pending-pr.md

Please review and edit the PR description if needed.

When ready, type **"confirm"** or run `/openpr confirm` to:
1. Squash all commits into a single commit
2. Push to origin
3. Create the pull request

Or type "cancel" to abort.
```

**STOP HERE** and wait for user response (unless invoked as `/openpr confirm`).

---

## Phase 2: Create PR (confirm)

**Proceed when user confirms OR when invoked as `/openpr confirm`.**

**No pre-squash.** Individual commits stay on the branch. Squash only happens at merge time (`/openpr merge`).

### 1. Push Individual Commits

```bash
git push origin HEAD || git push -u origin HEAD
```

### 2. Generate PR Title and Body On-The-Fly

```bash
BASE_BRANCH="${BASE_BRANCH:-main}"
cd "$(git rev-parse --show-toplevel)"

# Generate unified format (title = first line, body = rest)
PR_OUTPUT=$(python ~/.claude/scripts/aggregate-pr.py "${BASE_BRANCH}")
PR_TITLE=$(echo "$PR_OUTPUT" | head -1)
PR_BODY=$(echo "$PR_OUTPUT" | tail -n +3)
```

### 3. Create Pull Request

```bash
gh pr create \
  --title "${PR_TITLE}" \
  --body "${PR_BODY}" \
  --base "${BASE_BRANCH}" \
  --label "claude"
```

### 4. Handle PR Already Exists

If `gh pr create` fails because a PR already exists:

```bash
EXISTING=$(gh pr view --json url,number -q '.url')
echo "PR already exists: ${EXISTING}"
echo "Updating PR body instead..."
PR_NUMBER=$(gh pr view --json number -q '.number')
gh pr edit "$PR_NUMBER" --body "$PR_BODY"
```

### 5. Success Output

```bash
PR_URL=$(gh pr view --json url -q '.url')
echo "Pull Request Created Successfully!"
echo "Title: ${PR_TITLE}"
echo "URL: ${PR_URL}"
echo "Branch: ${BRANCH} -> ${BASE_BRANCH}"
echo ""
echo "Next steps:"
echo "  - @claude will auto-review (triggered by 'claude' label)"
echo "  - Add fix commits with /commit (PR body auto-updates)"
echo "  - When ready: /openpr merge"
```

### 6. Cleanup

```bash
rm -f .claude/pending-pr.md .claude/squash-message.txt
```

---

## Phase 3: Update PR Body (`/openpr update`)

Regenerate and update the PR body after adding new commits. Also triggered automatically by `/commit` after pushing to a branch with an open PR.

```bash
cd "$(git rev-parse --show-toplevel)"
BRANCH=$(git branch --show-current)

# Find open PR for current branch
PR_NUMBER=$(gh pr list --head "$BRANCH" --state open --json number -q '.[0].number')
if [ -z "$PR_NUMBER" ]; then
  echo "Error: No open PR found for branch $BRANCH"
  exit 1
fi

# Get base branch from PR
BASE=$(gh pr view "$PR_NUMBER" --json baseRefName -q '.baseRefName')

# Regenerate body from current commits
PR_OUTPUT=$(python ~/.claude/scripts/aggregate-pr.py "$BASE")
PR_BODY=$(echo "$PR_OUTPUT" | tail -n +3)

# Update PR
gh pr edit "$PR_NUMBER" --body "$PR_BODY"
echo "PR #${PR_NUMBER} body updated with latest commits."
```

---

## Phase 4: Merge PR (`/openpr merge`)

Squash merge with the unified format as commit message. Squash only happens here — never before.

```bash
cd "$(git rev-parse --show-toplevel)"
BRANCH=$(git branch --show-current)

# Find open PR
PR_NUMBER=$(gh pr list --head "$BRANCH" --state open --json number -q '.[0].number')
if [ -z "$PR_NUMBER" ]; then
  echo "Error: No open PR found for branch $BRANCH"
  exit 1
fi

# Get base and generate squash message
BASE=$(gh pr view "$PR_NUMBER" --json baseRefName -q '.baseRefName')
PR_OUTPUT=$(python ~/.claude/scripts/aggregate-pr.py "$BASE")
SQUASH_TITLE=$(echo "$PR_OUTPUT" | head -1)
SQUASH_BODY=$(echo "$PR_OUTPUT" | tail -n +3)

# Squash merge with crafted message
gh pr merge "$PR_NUMBER" --squash \
  --subject "${SQUASH_TITLE}" \
  --body "${SQUASH_BODY}"

PR_URL=$(gh pr view "$PR_NUMBER" --json url -q '.url')
echo "PR #${PR_NUMBER} merged!"
echo "Squash commit: ${SQUASH_TITLE}"
echo "URL: ${PR_URL}"
```

---

## Error Handling

### Push Rejected

If push fails due to diverged history:

```bash
git pull --rebase origin "$(git branch --show-current)"
git push origin HEAD
```

### No Remote Tracking

```bash
git push -u origin HEAD
```

### Merge Blocked

If merge fails (checks not passing, reviews needed):

```bash
gh pr checks "$PR_NUMBER"
gh pr view "$PR_NUMBER" --json reviewDecision -q '.reviewDecision'
```

Show status and instruct user to resolve before retrying.

---

## Safety Rules

1. **Never run on main/master** - Always verify branch first
2. **No pre-squash** - Individual commits stay on branch until merge
3. **Squash only at merge time** - Via `gh pr merge --squash`
4. **Preserve commit content** - All original commit messages in PR body
5. **Handle errors gracefully** - Clear recovery instructions

---

## Example Workflows

### Example 1: Dev → Main (full lifecycle)

```
User: /openpr

Claude: **SKILL_STARTED:** openpr

Current branch: gswarm-dev → Target: main
✓ Branch is up to date with origin/main
8 commits ahead of main.

Build 8

## Summary
This PR includes 4 new features, 2 bug fixes...

## Changes
### feat
- [x] b8-1: feat: add CLAUDE.md...
[...]

Type "confirm" or run /openpr confirm to create the PR.

User: confirm

Claude: Pull Request Created Successfully!
Title: Build 8
URL: https://github.com/bosmadev/gswarm/pull/5
Branch: gswarm-dev -> main

[... @claude reviews, user fixes issues ...]

User: /commit
Claude: [commits fix, pushes, auto-updates PR body]
PR #5 body updated with latest commits.

User: /openpr merge
Claude: PR #5 merged!
Squash commit: Build 8
```

### Example 2: Feature → Dev (no Build ID)

```
User: /openpr

Claude: Current branch: feature/auth → Target: cwchat-dev
[... preview ...]

User: confirm

Claude: PR Created: https://github.com/bosmadev/cwchat/pull/6

User: /openpr merge
Claude: PR #6 merged! Squash commit: feat: auth system with JWT
```
