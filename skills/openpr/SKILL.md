---
name: openpr
description: Create PR with squashed commits and auto-generated summary
argument-hint: "[base-branch|help]"
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

Commands:
  (no args)        Auto-detect target branch (see hierarchy below)
  [branch]         Create PR targeting specified branch
  help             Show this help

Branch Hierarchy (auto-detected when no base-branch given):
  *-dev branches     → PR targets main (Build N+1 from CHANGELOG)
  feature/* branches → PR targets {repo}-dev (no Build ID)
  anything else      → PR targets {repo}-dev if exists, else main

Workflow:
  1. Auto-detects target branch from hierarchy
  2. Checks if branch is behind target — auto-rebases if needed
  3. Runs ~/.claude/scripts/aggregate-pr.py to gather and format commits
  4. Generates .claude/pending-pr.md for review
  5. On confirm:
     - Creates squash commit with formatted message
     - Pushes to origin
     - Creates PR with auto-generated body
     - Amends commit with PR URL reference

PR Format:
  dev→main:     Title: "Build {N+1}", Build ID from CHANGELOG
  feature→dev:  Title: conventional commit summary, no Build ID

Examples:
  /openpr              # Auto-detect target from branch hierarchy
  /openpr main         # Force PR to main
  /openpr cwchat-dev   # Force PR to cwchat-dev
```

---

## Arguments

**$ARGUMENTS**: "$ARGUMENTS"

Parse arguments:
- `base-branch` (optional): Target branch for PR (auto-detected if omitted)
- `help`: Show usage information

## Branch Hierarchy Detection

When no base branch is explicitly provided, auto-detect using this logic:

```
Current Branch              → Target Base Branch
────────────────────────────────────────────────
*-dev (e.g. cwchat-dev)      → main
feature/*, anything else     → {repo}-dev (if exists on remote, else main)
main/master                  → BLOCKED (abort with error)
```

**Detection steps:**

1. If user provided a base branch arg → use it directly
2. Get current branch: `git branch --show-current`
3. If current branch ends with `-dev` → base = `main`
4. Else → check if `{repo}-dev` exists on remote:
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
2. **CHANGELOG.md auto-detect:** reads `CHANGELOG.md` for highest `Build N`, uses `N+1`
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

Use the aggregation script to gather and format all commit data.
The `BASE_BRANCH` was determined in the Branch Hierarchy Detection step above.

```bash
# BASE_BRANCH already set from hierarchy detection
cd "$(git rev-parse --show-toplevel)"

# For non-main targets, pass --no-build-id to skip Build ID injection
if [ "${BASE_BRANCH}" != "main" ] && [ "${BASE_BRANCH}" != "master" ]; then
  python ~/.claude/scripts/aggregate-pr.py --no-build-id "${BASE_BRANCH}" > .claude/pending-pr-raw.md 2>&1
else
  python ~/.claude/scripts/aggregate-pr.py "${BASE_BRANCH}" > .claude/pending-pr-raw.md 2>&1
fi
```

The script handles:
- Extracting build ID from branch name (e.g., `b101` → `101`)
- Parsing all commits since base branch
- Grouping commits by conventional type (feat, fix, refactor, etc.)
- Generating summary paragraph from commit types
- Formatting commits with `b{buildId}-{n}: {subject}` pattern
- Collecting detailed changes from commit bodies

**Output format from script:**
```markdown
# Build {number}

## Summary

{Auto-generated summary paragraph: "This PR includes X feat, Y fixes, and Z refactoring."}

## Commits

### feat
- b{buildId}-1: feat(scope): description
- b{buildId}-2: feat: another feature

### fix
- b{buildId}-3: fix(scope): bug description

## Details

**{hash}**: {commit body content}
**{hash}**: {commit body content}
```

### 2. Verify Script Success

Check that aggregate-pr.py ran successfully:

```bash
if [ ! -f .claude/pending-pr-raw.md ] || [ ! -s .claude/pending-pr-raw.md ]; then
  echo "Error: Failed to generate PR summary. Check that you have commits to include."
  exit 1
fi
```

### 3. Write .claude/pending-pr.md

Transform the raw output into the pending PR format:

```bash
# Extract components from raw output
TITLE=$(grep '^# Build' .claude/pending-pr-raw.md | sed 's/^# //')
SUMMARY=$(sed -n '/^## Summary$/,/^## /p' .claude/pending-pr-raw.md | grep -v '^## ')
COMMITS=$(sed -n '/^## Commits$/,/^## /p' .claude/pending-pr-raw.md | grep -v '^## ')
DETAILS=$(sed -n '/^## Details$/,$p' .claude/pending-pr-raw.md | grep -v '^## Details')

# Write formatted pending PR
cat > .claude/pending-pr.md <<EOF
# Pull Request: ${TITLE}

## Summary

${SUMMARY}

## Commits Included

${COMMITS}

## Detailed Changes

${DETAILS}

---
**Note:** Edit this file as needed. Run \`/openpr\` again or type "confirm" to squash and create the PR.
EOF

# Cleanup temp file
rm .claude/pending-pr-raw.md
```

### 6. Prompt User

After creating `.claude/pending-pr.md`, display:

```
Created: .claude/pending-pr.md

Please review and edit the PR description if needed.

When ready, type "confirm" to:
1. Squash all commits into a single commit
2. Push to origin
3. Create the pull request

Or type "cancel" to abort.
```

**STOP HERE** and wait for user response.

---

## Phase 2: Squash and Create PR

**Only proceed when user confirms (types "confirm", "yes", "ok", "proceed", or similar).**

### 1. Read Final PR Content

```bash
cat .claude/pending-pr.md
```

Parse the file to extract:
- **Title**: From the `# Pull Request:` header
- **Summary**: From `## Summary` section
- **Commits**: From `## Commits Included` section
- **Details**: From `## Detailed Changes` section

### 2. Create Squash Commit Message

Use aggregate-pr.py to generate the properly formatted squash commit message:

```bash
BASE_BRANCH="${BASE_BRANCH:-main}"
cd "$(git rev-parse --show-toplevel)"

# Generate squash message format (without PR URL - will be added after PR creation)
python ~/.claude/scripts/aggregate-pr.py --squash "${BASE_BRANCH}" > .claude/squash-message.txt

# Verify the message was generated
if [ ! -s .claude/squash-message.txt ]; then
  echo "Error: Failed to generate squash commit message"
  exit 1
fi
```

The `--squash` flag outputs the commit in this format:
```
Build {id}: {summary title}

## Summary
{summary paragraph}

## Changes
- b{id}-1: {commit subject}
- b{id}-2: {commit subject}

## Details
{commit body content}
```

Note: The `PR: {url}` line will be appended after the PR is created (step 8).

### 3. Soft Reset to Base

```bash
BASE_BRANCH="${BASE_BRANCH:-main}"
MERGE_BASE=$(git merge-base ${BASE_BRANCH} HEAD)
git reset --soft ${MERGE_BASE}
```

This stages all changes while removing individual commits.

### 4. Create Squash Commit

Use the generated squash message file:

```bash
git commit -F .claude/squash-message.txt
```

### 5. Push to Origin

```bash
git push origin HEAD --force-with-lease
```

Use `--force-with-lease` for safety (fails if remote has new commits).

### 6. Create Pull Request

Read the pending PR file to extract the title and use aggregate-pr.py to generate the PR body:

```bash
BASE_BRANCH="${BASE_BRANCH:-main}"
cd "$(git rev-parse --show-toplevel)"

# Extract title from pending PR
PR_TITLE=$(grep '^# Pull Request:' .claude/pending-pr.md | sed 's/^# Pull Request: //')

# Generate PR body using aggregate-pr.py (outputs the markdown body directly)
PR_BODY=$(python ~/.claude/scripts/aggregate-pr.py "${BASE_BRANCH}")

# Verify PR body was generated
if [ -z "$PR_BODY" ]; then
  echo "Error: Failed to generate PR body"
  exit 1
fi

# Create the PR
gh pr create \
  --title "${PR_TITLE}" \
  --body "${PR_BODY}" \
  --base "${BASE_BRANCH}"
```

### 7. Get PR URL

```bash
PR_URL=$(gh pr view --json url -q '.url')
echo "$PR_URL"
```

### 8. Amend Commit with PR Reference

Append the PR URL to the squash commit message:

```bash
cd "$(git rev-parse --show-toplevel)"

# Append PR URL to the squash message file
echo "" >> .claude/squash-message.txt
echo "PR: ${PR_URL}" >> .claude/squash-message.txt

# Amend the commit with the updated message
git commit --amend -F .claude/squash-message.txt

# Push the amended commit
git push origin HEAD --force-with-lease
```

### 9. Success Output

Display the success message with cleanup of temporary files:

```bash
cd "$(git rev-parse --show-toplevel)"

# Cleanup temporary files
rm -f .claude/squash-message.txt

echo "Pull Request Created Successfully!"
echo ""
echo "Title: ${PR_TITLE}"
echo "URL: ${PR_URL}"
echo "Branch: ${BRANCH} -> ${BASE_BRANCH}"
echo ""
echo "The squashed commit now references: ${PR_URL}"
```

---

## Phase 3: Cleanup

### Prompt for Cleanup

Ask the user:

```
Would you like to delete .claude/pending-pr.md? (yes/no)
```

### If Yes:

```bash
rm .claude/pending-pr.md
git status
```

Confirm: "Deleted .claude/pending-pr.md"

### If No:

Keep the file and inform:

```
Keeping .claude/pending-pr.md for reference.
You can delete it manually later with: rm .claude/pending-pr.md
```

---

## Error Handling

### No Remote Tracking

If push fails due to no upstream:

```bash
git push -u origin HEAD --force-with-lease
```

### PR Already Exists

If PR creation fails because one already exists:

```bash
gh pr view --json url,state -q '.url + " (" + .state + ")"'
```

Show the existing PR and ask if user wants to update it instead.

### Merge Conflicts

If reset fails due to conflicts, abort and inform user:

```
Error: Cannot squash due to conflicts with ${BASE_BRANCH}.
Please resolve conflicts first:
  git rebase ${BASE_BRANCH}
Then run /openpr again.
```

---

## Safety Rules

1. **Never run on main/master** - Always verify branch first
2. **Use --force-with-lease** - Never use --force directly
3. **Show preview before squash** - User must confirm
4. **Preserve commit content** - All original commit messages are preserved in PR body
5. **Handle errors gracefully** - Provide clear recovery instructions

---

## Example Workflows

### Example 1: Dev → Main (with Build ID)

```
User: /openpr

Claude: **SKILL_STARTED:** openpr

Current branch: cwchat-dev → Target: main

Checking branch currency...
✓ Branch is up to date with origin/main

Gathering commits...
Auto-detected Build 3 from CHANGELOG.md (highest: Build 2)

Created: .claude/pending-pr.md
[... shows PR preview ...]

Type "confirm" to squash and create the PR.

User: confirm

Claude: Pull Request Created Successfully!
Title: Build 3
URL: https://github.com/bosmadev/cwchat/pull/5
Branch: cwchat-dev -> main
```

### Example 2: Feature → Dev (no Build ID)

```
User: /openpr

Claude: **SKILL_STARTED:** openpr

Current branch: feature/auth → Target: cwchat-dev (auto-detected)

Checking branch currency...
⚠️  Branch is 2 commits behind origin/cwchat-dev
Rebasing on origin/cwchat-dev...
✓ Rebase successful

Gathering commits...

Created: .claude/pending-pr.md

# Pull Request: feat: auth system with JWT validation
[... conventional commit summary, no Build ID ...]

User: confirm

Claude: Pull Request Created Successfully!
Title: feat: auth system with JWT validation
URL: https://github.com/bosmadev/cwchat/pull/6
Branch: feature/auth -> cwchat-dev
```
