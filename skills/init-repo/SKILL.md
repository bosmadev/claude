---
name: init-repo
description: Initialize Claude Code workflows and configuration in any repository. Copies templates for GitHub Actions, CLAUDE.md, and .gitignore.
argument-hint: "[interactive|workflows|all|help]"
user-invocable: true
context: fork
---
# Initialize Repository for Claude Code

**When invoked, immediately output:** `**SKILL_STARTED:** init-repo`

Set up Claude Code automation in any repository by installing workflow templates and configuration files.

## Help Command

When arguments equal "help":

```
/init-repo - Initialize Claude Code in a repository

Usage:
  /init-repo [mode]

Modes:
  (no args)     Interactive setup - prompts for each component
  workflows     Install GitHub workflows only
  all           Full setup (workflows + CLAUDE.md + structure)
  help          Show this help

What gets installed:

  workflows mode:
    ├─ .github/workflows/claude.yml  (GitHub Actions automation)
    └─ CHANGELOG.md                  (if missing)

  all mode (workflows plus):
    ├─ CLAUDE.md                     (Project configuration)
    ├─ .claude/                      (Working directory)
    ├─ .claude/commit.md             (Commit template)
    └─ .gitignore updates            (Claude patterns)

Workflow features:
  - @claude comment triggers in PRs/issues
  - claude[bot] issue assignment
  - 'claude' label automation
  - Manual "Summarize PR" button
  - Model selection (Sonnet/Opus/Haiku)
  - MCP integration (Sequential thinking + Context7)

Prerequisites:
  - Git repository initialized
  - GitHub repo created
  - CLAUDE_CODE_OAUTH_TOKEN secret configured

Token setup:
  1. Run: claude auth login
  2. Copy the access token
  3. Add to GitHub: Settings → Secrets → Actions
     Name: CLAUDE_CODE_OAUTH_TOKEN
     Value: [paste token]

Examples:
  /init-repo              # Interactive mode (prompts for options)
  /init-repo workflows    # Minimal setup (just workflow)
  /init-repo all          # Complete setup (recommended)

Next steps after install:
  1. Review: git status
  2. Edit CLAUDE.md with project details
  3. Commit: git add -A && git commit -m "config: initialize Claude Code"
  4. Push: git push
  5. Test: Create PR and comment @claude
```

## Arguments

**$ARGUMENTS**: "$ARGUMENTS"

Parse arguments:

- `(empty)` or `interactive`: Interactive mode - prompt for each component
- `workflows`: Install only GitHub workflow templates
- `all`: Full setup with all components
- `help`: Show usage information

## Pre-flight Checks

### 1. Verify Git Repository

```bash
git rev-parse --is-inside-work-tree 2>/dev/null || echo "NOT_A_REPO"
```

If not a git repo, abort with: "Error: Not inside a git repository. Run `git init` first."

### 2. Get Repository Root

```bash
REPO_ROOT=$(git rev-parse --show-toplevel)
echo "$REPO_ROOT"
```

### 3. Check Existing Files

```bash
# Check what already exists
[ -f .github/workflows/claude.yml ] && echo "WORKFLOW_EXISTS"
[ -d .claude ] && echo "CLAUDE_DIR_EXISTS"
```

## Installation Modes

### Mode: workflows

Install GitHub workflow templates only.

**Steps:**

1. Create `.github/workflows/` directory if needed:

   ```bash
   mkdir -p .github/workflows
   ```
2. Copy workflow template from Claude config:

   ```bash
   # Template location
   TEMPLATE="C:/Users/Dennis/.claude/.github/workflows/claude.yml"

   # Destination
   DEST=".github/workflows/claude.yml"

   # Copy if template exists
   if [ -f "$TEMPLATE" ]; then
       cp "$TEMPLATE" "$DEST"
   else
       echo "Error: Template not found at $TEMPLATE"
       exit 1
   fi
   ```
3. If `claude.yml` already exists, show warning and skip:

   ```
   ⚠️  .github/workflows/claude.yml already exists

   Use `git diff .github/workflows/claude.yml` to compare with template.
   Skipping to avoid overwriting.
   ```
4. Create CHANGELOG.md if missing:

   ```bash
   if [ ! -f "CHANGELOG.md" ]; then
       cat > CHANGELOG.md << 'EOF'
   <!-- This file is auto-updated by .github/workflows/claude.yml on merge to main -->
   # Changelog

   All notable changes to this project will be documented in this file.

   ## [Unreleased]

   EOF
       echo "✅ Created CHANGELOG.md"
   fi
   ```
5. Output success:

   ```
   ✅ Installed .github/workflows/claude.yml

   This workflow provides:
   - PR comment triggers (@claude)
   - Manual workflow dispatch (Actions tab)
   - Issue/PR automation
   - Automatic CHANGELOG updates

   Features:
   - Comment with @claude for PR reviews
   - Assign issues to claude[bot]
   - Label PRs with 'claude' for auto-review
   - Manual "Summarize PR" button in Actions tab

   Next steps:
   1. Add CLAUDE_CODE_OAUTH_TOKEN secret to GitHub repo
   2. Commit the workflow file
   3. Push to enable automation
   ```

### Mode: all

Full setup including workflows, CLAUDE.md, and configuration.

**Steps:**

1. Run `workflows` mode first
2. Create `.claude/` directory:

   ```bash
   mkdir -p .claude
   ```
3. Create basic CLAUDE.md if not present:

   ```bash
   if [ ! -f "CLAUDE.md" ]; then
       cat > CLAUDE.md << 'EOF'
   # Claude Code Configuration

   ## Project Overview

   [Describe your project here]

   ## Stack

   - Language/Framework: [e.g., TypeScript, Python, React]
   - Build tool: [e.g., pnpm, npm, cargo]
   - Package manager: [e.g., pnpm, npm]

   ## Commands

   | Command | Description |
   |---------|-------------|
   | `pnpm dev` | Start development server |
   | `pnpm build` | Build for production |
   | `pnpm test` | Run tests |
   | `pnpm lint` | Run linter |

   ## Development Workflow

   1. Make changes
   2. Run tests: `pnpm test`
   3. Commit: Use `/commit` skill
   4. Push: Changes auto-pushed after commit

   ## Conventions

   ### Commit Format

   Use scope-prefix style:
   - `feat: description` - New features
   - `fix: description` - Bug fixes
   - `refactor: description` - Code restructuring
   - `config: description` - Configuration changes
   - `docs: description` - Documentation only

   ### Code Style

   [Add project-specific conventions]

   EOF
       echo "✅ Created CLAUDE.md"
   fi
   ```
4. Update `.gitignore` with Claude patterns:

   ```bash
   # Check if patterns already exist
   if ! grep -q "# Claude Code" .gitignore 2>/dev/null; then
       cat >> .gitignore << 'EOF'

   # Claude Code
   .claude/pending-commit.md
   .claude/pending-pr.md
   .claude/review-*.md
   .claude/debug/
   EOF
       echo "✅ Updated .gitignore"
   else
       echo "ℹ️  .gitignore already has Claude patterns"
   fi
   ```
5. Create commit.md template:

   ```bash
   if [ ! -f ".claude/commit.md" ]; then
       cat > .claude/commit.md << 'EOF'
   # .claude/commit.md

   ## Pending
   <!-- Auto-written by change-tracker hook - file changes detected during development -->

   ## Ready
   <!-- You edit this section for the final commit message -->

   EOF
       echo "✅ Created .claude/commit.md"
   fi
   ```
6. Output success:

   ```
   ✅ Full Claude Code setup complete

   Installed:
   - .github/workflows/claude.yml
   - CLAUDE.md (project configuration)
   - CHANGELOG.md (if missing)
   - .claude/ directory
   - .claude/commit.md (commit template)
   - Updated .gitignore

   Next steps:
   1. Edit CLAUDE.md with project details
   2. Add CLAUDE_CODE_OAUTH_TOKEN to GitHub secrets
   3. Review changes: `git status`
   4. Commit: `git add -A && git commit -m "config: initialize Claude Code"`
   5. Push to enable workflows
   ```

### Mode: interactive (default)

Prompt for each component.

**Steps:**

1. Show current status:

   ```
   Repository: {repo-name}

   Current state:
   - .github/workflows/claude.yml: [exists/missing]
   - .claude/: [exists/missing]

   What would you like to install?
   ```

2. Use AskUserQuestion to prompt for components:

   **Implementation guidance:**
   - Use AskUserQuestion with multiple choice format
   - Each component is a separate question (not checkboxes)
   - Ask sequentially: workflows → claude directory → gitignore
   - Format:

   ```
   Question 1: "Install GitHub workflows (.github/workflows/claude.yml)?"
   Options: ["Yes", "No"]

   Question 2: "Create .claude directory structure?"
   Options: ["Yes", "No"]

   Question 3: "Update .gitignore with Claude patterns?"
   Options: ["Yes", "No"]
   ```

   **Note:** AskUserQuestion doesn't support checkbox UI. Use individual yes/no questions instead.

3. Install selected components based on user responses
4. Show summary of changes

## Template Locations

All templates are sourced from Claude Code's configuration directory:

| Template  | Source                                                   | Destination                      |
| --------- | -------------------------------------------------------- | -------------------------------- |
| Workflows | `C:/Users/Dennis/.claude/.github/workflows/claude.yml` | `.github/workflows/claude.yml` |

**Note:** On Windows, use forward slashes in paths for cross-platform compatibility.

### Template File Verification

Before copying any template, verify it exists:

```bash
TEMPLATE="C:/Users/Dennis/.claude/.github/workflows/claude.yml"

if [ ! -f "$TEMPLATE" ]; then
    echo "Error: Template file not found at $TEMPLATE"
    echo ""
    echo "This usually means:"
    echo "  - Claude Code installation is incomplete"
    echo "  - Template files were not installed"
    echo "  - Installation directory is not ~/.claude/"
    echo ""
    echo "Resolution:"
    echo "  1. Check installation: ls ~/.claude/.github/workflows/"
    echo "  2. Reinstall Claude Code if template is missing"
    echo "  3. Verify you're using the correct Claude Code version"
    exit 1
fi

# Proceed with copy only if verification passes
cp "$TEMPLATE" ".github/workflows/claude.yml"
```

**Graceful failure:** If template is missing, provide detailed troubleshooting steps instead of a cryptic error.

## File Content: claude.yml

The workflow template is copied from `C:/Users/Dennis/.claude/.github/workflows/claude.yml`.

Key features:

- **Comment triggers**: @claude in PR/issue comments
- **Assignment triggers**: Assign issues to claude[bot]
- **Label triggers**: Label PRs with 'claude'
- **Manual dispatch**: "Summarize PR" button in Actions tab
- **Model selection**: Sonnet (default), Opus, or Haiku
- **MCP integration**: Sequential thinking + Context7
- **Security**: Signed commits, OIDC authentication

## File Content: .gitignore additions

```gitignore
# Claude Code
.claude/pending-commit.md
.claude/pending-pr.md
.claude/review-*.md
.claude/debug/
```

## File Content: CLAUDE.md template

Basic project configuration file created with:

- Project overview section
- Stack definition
- Common commands table
- Development workflow
- Commit conventions
- Code style guidelines

The template uses scope-prefix commit format (feat, fix, refactor, etc.).

## Error Handling

| Error                                                                      | Action                                                  |
| -------------------------------------------------------------------------- | ------------------------------------------------------- |
| Not a git repo                                                             | Instruct to run `git init` first                      |
| No write permission                                                        | Report permission error                                 |
| Template not found at C:/Users/Dennis/.claude/.github/workflows/claude.yml | Report missing template, check Claude Code installation |
| File exists                                                                | Show warning and skip to avoid overwriting              |
| Cannot create directory                                                    | Check filesystem permissions                            |

## Safety Rules

1. **Never overwrite without confirmation** - Always show diff first
2. **Idempotent operations** - Safe to run multiple times
3. **Preserve existing content** - Append to .gitignore, don't replace
4. **Clear output** - Show exactly what was installed

## Example Sessions

### Workflows Only

```
User: /init-repo workflows

Claude: **SKILL_STARTED:** init-repo

Detecting repository root...
Repository: C:/projects/my-app

Installing GitHub workflows...

✅ Created .github/workflows/claude.yml
✅ Created CHANGELOG.md

Workflow installed successfully!

Features enabled:
- Comment with @claude for PR reviews
- Assign issues to claude[bot]
- Label PRs with 'claude' for auto-review
- Manual "Summarize PR" in Actions tab
- Model selection (Sonnet/Opus/Haiku)

Next steps:
1. Add CLAUDE_CODE_OAUTH_TOKEN to GitHub secrets
2. Commit: git add .github CHANGELOG.md
3. Push to enable automation
```

### Full Setup

```
User: /init-repo all

Claude: **SKILL_STARTED:** init-repo

Detecting repository root...
Repository: C:/projects/my-app

Installing full Claude Code setup...

✅ Created .github/workflows/claude.yml
✅ Created CLAUDE.md
✅ Created CHANGELOG.md
✅ Created .claude/
✅ Created .claude/commit.md
✅ Updated .gitignore

Full setup complete!

Installed components:
- GitHub workflow automation (PR/issue triggers)
- Project configuration (CLAUDE.md)
- Changelog template
- Commit tracking structure
- Gitignore patterns

Next steps:
1. Edit CLAUDE.md with project details
2. Add CLAUDE_CODE_OAUTH_TOKEN to GitHub secrets
3. Review: git status
4. Commit: git add -A && git commit -m "config: initialize Claude Code"
5. Push to enable workflows
```

### Interactive Mode

```
User: /init-repo

Claude: **SKILL_STARTED:** init-repo

Repository: my-project

Current state:
- .github/workflows/claude.yml: missing
- .claude/: exists

Which components would you like to install?

User: [selects workflows]

Claude: Installing workflows...
Created: .github/workflows/claude.yml
✅ Done
```

## Integration Points

### With /commit

After running `/init-repo`, the workflow files can be committed:

```bash
/commit  # Will include claude.yml in the commit
```

### With /openpr

The installed `claude.yml` workflow enables `@claude prepare` comments on PRs.

### With CHANGELOG

The workflow automatically updates CHANGELOG.md when PRs are merged to main.

## Implementation Notes

### Cross-Platform Paths

Use forward slashes for paths in bash commands:

```bash
TEMPLATE="C:/Users/Dennis/.claude/.github/workflows/claude.yml"
```

This ensures compatibility when running from Git Bash on Windows.

### Idempotency

The skill is safe to run multiple times:

- Existing files are skipped with warnings
- .gitignore patterns only added if missing
- Directories created with `mkdir -p` (no error if exists)

### Template Verification

Before copying, verify the template exists:

```bash
if [ ! -f "$TEMPLATE" ]; then
    echo "Error: Template not found at $TEMPLATE"
    echo "Check Claude Code installation: C:/Users/Dennis/.claude/"
    exit 1
fi
```

### GitHub Secret Setup

After installation, configure the Claude OAuth token as a GitHub secret:

**Option 1: Automatic sync (recommended)**

Use the `/token sync` command to automatically push your Claude token to GitHub:

```bash
# First, ensure you're authenticated
claude auth login

# Then sync to current repository
/token sync

# Or sync to all detected repositories
/token sync all
```

The `/token sync` command handles the entire process: reading your local Claude token, pushing it to GitHub repository secrets, and verifying the setup.

**Option 2: Manual setup**

If `/token sync` is unavailable:

1. Get token: Run `claude auth login` and copy the access token
2. Go to GitHub repo → Settings → Secrets and variables → Actions
3. Click "New repository secret"
4. Name: `CLAUDE_CODE_OAUTH_TOKEN`
5. Value: Paste the token from step 1

**Verification:**

After setup, verify the secret exists:
```bash
gh secret list | grep CLAUDE_CODE_OAUTH_TOKEN
```

The workflow will fail with authentication errors until this secret is properly configured. See `/token help` for more token management options.
