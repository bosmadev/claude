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
  (no args)        Create PR targeting main branch
  [branch]         Create PR targeting specified branch
  help             Show this help

Workflow:
  1. Runs ~/.claude/scripts/aggregate-pr.py to gather and format commits
     - Extracts build ID from branch name (b101 -> 101)
     - Groups commits by type (feat, fix, refactor, etc.)
     - Generates summary paragraph from commit composition
  2. Generates .claude/pending-pr.md for review
  3. On confirm:
     - Creates squash commit with formatted message
     - Pushes to origin
     - Creates PR with auto-generated body
     - Amends commit with PR URL reference

PR Format:
  Title: Build {number}
  Body: Auto-generated summary + commits grouped by type
  Commit: Includes ## Summary, ## Changes, ## Details, PR: {url}

Examples:
  /openpr              # PR to main
  /openpr develop      # PR to develop branch
```

---

## Arguments

**$ARGUMENTS**: "$ARGUMENTS"

Parse arguments:
- `base-branch` (optional): Target branch for PR (default: `main`)
- `help`: Show usage information

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
git pull --rebase origin feature/b101
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

Current branch: feature/b101
Base branch: main
Commits ahead: 0

Possible causes:
- All commits have already been merged
- Branch is up to date with main
- You're on the main branch (use a feature branch instead)

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

If on `main` or `master`, abort with: "Error: Cannot create PR from main/master branch. Switch to a feature branch first."

### 3. Extract Build Number

Extract the numeric part from the branch name for the PR title:
- `b101` -> `101`
- `feature/b42` -> `42`
- `b101-feature` -> `101`

```bash
BRANCH=$(git branch --show-current)
BUILD_NUM=$(echo "$BRANCH" | grep -oE 'b[0-9]+' | head -1 | tr -d 'b')
echo "${BUILD_NUM:-$BRANCH}"
```

PR Title format: `Build {number}` (e.g., "Build 101")
- If no build number found, use the branch name: `Build: {branch-name}`

### 4. Check for Unpushed Commits

```bash
git log @{u}..HEAD --oneline 2>/dev/null || git log --oneline
```

If no commits to include, abort with: "Error: No commits found to include in PR."

---

## Phase 1: Generate .claude/pending-pr.md

### 1. Run aggregate-pr.py

Use the aggregation script to gather and format all commit data:

```bash
BASE_BRANCH="${BASE_BRANCH:-main}"
cd "$(git rev-parse --show-toplevel)"
python ~/.claude/scripts/aggregate-pr.py "${BASE_BRANCH}" > .claude/pending-pr-raw.md 2>&1
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

## Example Workflow

```
User: /openpr

Claude: **SKILL_STARTED:** openpr

Gathering commits from branch b101...
Running aggregate-pr.py to analyze commits...

Created: .claude/pending-pr.md

# Pull Request: Build 101

## Summary
This PR includes 2 new features and 1 bug fix.

## Commits Included

### feat
- b101-1: feat(auth): Add user validation
- b101-2: feat(api): Add rate limiting

### fix
- b101-3: fix(parser): Handle edge case in token parsing

## Detailed Changes

**abc123**: Implemented user validation middleware with email and password checks.
**def456**: Added rate limiting to protect API endpoints.
**ghi789**: Fixed parser crash when encountering malformed tokens.

---
**Note:** Edit this file as needed. Run `/openpr` again or type "confirm" to squash and create the PR.

Please review and edit .claude/pending-pr.md if needed.
Type "confirm" to squash and create the PR.

User: confirm

Claude: Squashing commits...
Creating squash commit message...
Pushing to origin...
Creating pull request...

Pull Request Created Successfully!

Title: Build 101
URL: https://github.com/user/repo/pull/42
Branch: b101 -> main

The squashed commit now references: https://github.com/user/repo/pull/42

Would you like to delete .claude/pending-pr.md? (yes/no)

User: yes

Claude: Deleted .claude/pending-pr.md. Done!
```
