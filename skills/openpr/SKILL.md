---
name: openpr
description: Squash commits and create a pull request with auto-generated summary. Creates .claude/pending-pr.md for review before execution.
argument-hint: [base-branch]
user-invocable: true
context: main
---

# Open PR Workflow

**When invoked, immediately output:** `**SKILL_STARTED:** openpr`

Create a pull request with squashed commits and auto-generated summary.

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
  1. Gathers all commits from current branch
  2. Generates .claude/pending-pr.md for review
  3. On confirm: squashes commits, pushes, creates PR
  4. Amends commit with PR URL reference

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

### 1. Gather Commit Information

Get all commits from the branch (commits since diverging from base):

```bash
BASE_BRANCH="${BASE_BRANCH:-main}"
git log ${BASE_BRANCH}..HEAD --pretty=format:'%h|%s|%b---COMMIT_END---' 2>/dev/null
```

If the above fails (no upstream), use all commits on branch:

```bash
git log --pretty=format:'%h|%s|%b---COMMIT_END---'
```

### 2. Parse Commits

For each commit, extract:
- **Short hash**: `%h`
- **Subject line**: `%s` (the first line / title)
- **Body**: `%b` (everything after the first line)

### 3. Generate Summary

Auto-generate a summary by:
1. Collecting all commit subject lines
2. Grouping by conventional commit type (feat, fix, refactor, docs, test, chore, etc.)
3. Creating a concise paragraph summarizing the changes

### 4. Format Commits List

Format each commit as:
- `{branch}-{increment}: {commit-subject}`

Example:
```
- b101-1: feat: Add user validation
- b101-2: fix: Handle edge case in parser
- b101-3: refactor: Extract helper function
```

The increment is the commit order (1 = oldest, N = newest).

### 5. Write .claude/pending-pr.md

Create `.claude/pending-pr.md` in the repository:

```markdown
# Pull Request: Build {number}

## Summary

{Auto-generated summary paragraph describing the overall changes}

## Commits Included

{List of commits in branch-increment format}

## Detailed Changes

{Combined body content from all commits, separated by headers}

---
**Note:** Edit this file as needed. Run `/openpr` again or type "confirm" to squash and create the PR.
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

Format the squash commit message:

```
{PR Title}

{Summary section content}

Commits squashed:
{Commits list}

{Detailed Changes content}
```

### 3. Soft Reset to Base

```bash
BASE_BRANCH="${BASE_BRANCH:-main}"
MERGE_BASE=$(git merge-base ${BASE_BRANCH} HEAD)
git reset --soft ${MERGE_BASE}
```

This stages all changes while removing individual commits.

### 4. Create Squash Commit

```bash
git commit -m "$(cat <<'EOF'
{Squash commit message here}
EOF
)"
```

### 5. Push to Origin

```bash
git push origin HEAD --force-with-lease
```

Use `--force-with-lease` for safety (fails if remote has new commits).

### 6. Create Pull Request

```bash
BASE_BRANCH="${BASE_BRANCH:-main}"
gh pr create \
  --title "Build {number}" \
  --body "$(cat <<'EOF'
## Summary

{Summary content}

## Commits Included

{Commits list}

## Detailed Changes

{Details content}
EOF
)" \
  --base "${BASE_BRANCH}"
```

### 7. Get PR URL

```bash
PR_URL=$(gh pr view --json url -q '.url')
echo "$PR_URL"
```

### 8. Amend Commit with PR Reference

Update the commit body to reference the PR URL:

```bash
git commit --amend -m "$(cat <<'EOF'
{Original squash message}

PR: {PR_URL}
EOF
)"
```

Push the amended commit:

```bash
git push origin HEAD --force-with-lease
```

### 9. Success Output

```
Pull Request Created Successfully!

Title: Build {number}
URL: {PR_URL}
Branch: {branch} -> {base-branch}

The squashed commit now references: {PR_URL}
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

Claude: Gathering commits from branch b101...

Created: .claude/pending-pr.md

## Summary
This PR adds user validation and fixes edge case handling in the parser.

## Commits Included
- b101-1: feat: Add user validation
- b101-2: fix: Handle edge case in parser

Please review and edit .claude/pending-pr.md if needed.
Type "confirm" to squash and create the PR.

User: confirm

Claude: Squashing commits...
Pushing to origin...
Creating pull request...

Pull Request Created Successfully!

Title: Build 101
URL: https://github.com/user/repo/pull/42
Branch: b101 -> main

Would you like to delete .claude/pending-pr.md? (yes/no)

User: yes

Claude: Deleted .claude/pending-pr.md. Done!
```
