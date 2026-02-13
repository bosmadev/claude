---
name: review
description: "Code review with security (OWASP) and design (a11y). Default: 10 agents, 3 iterations, Sonnet."
argument-hint: "[agents] [iterations] [opus|sonnet|haiku] [working|impact|branch|staged|pr|help]"
user-invocable: true
---

# /review - Multi-Aspect Code Review

**When invoked, immediately output:** `**SKILL_STARTED:** review`

Unified code review that runs ALL aspects by default, including security (OWASP Top 10) and design (accessibility/UI). Spawns parallel review agents to analyze code comprehensively.

**Review agents ONLY leave TODO-P1/P2/P3 comments in code. They do NOT auto-fix issues.**

## Help Command

```
/review help
```

Displays usage information and examples.

## Usage & Defaults

| Parameter | Default | Range |
|-----------|---------|-------|
| Agents | 10 | 1-10 (hard cap) |
| Iterations | 3 | 1-5 |
| Model | Opus 4.5 | opus / sonnet / haiku |
| Scope | working | working / impact / branch / staged / path / pr |

### Override Syntax

```
/review                          → 10 agents, 3 iterations, Opus 4.5, working scope
/review N                        → N agents, 3 iterations, Opus 4.5
/review N M                      → N agents, M iterations, Opus 4.5
/review N M sonnet               → N agents, M iterations, Sonnet 4.5
/review N M haiku                → N agents, M iterations, Haiku
/review working                  → 10 agents, working tree only (R1)
/review impact                   → 10 agents, working tree + impact radius (R2)
/review branch                   → 10 agents, full branch diff since main (R3)
/review 5 2 sonnet branch        → 5 agents, 2 iter, Sonnet, full branch diff
/review src/                     → 10 agents, 3 iter, review src/ directory only
/review 5 2 haiku impact         → 5 agents, 2 iter, Haiku, impact radius analysis
/review pr                       → Current branch PR with full review
/review pr 123                   → PR #123 with full review
```

## Model Routing (3-Layer System)

This skill runs in the **main Opus conversation** (no `context: fork`) to maintain context continuity across all review agents. Review agents are spawned via Task tool with explicit model routing.

**Why no fork?** Review requires cross-agent context synthesis. Running in main conversation allows the orchestrator to aggregate findings from all agents and generate unified reports without context loss.

This differs from `/commit` which forks because it performs isolated pattern matching with no need for cross-agent synthesis.

| Layer | Mechanism | Effect |
|-------|-----------|--------|
| L1: Global Default | `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` (SessionStart) | Subagents default to Sonnet |
| L3: Per-Agent Override | `model="opus"` in Task() calls | Each review agent uses parsed model (default: opus) |

**Implementation:** When spawning Task agents, pass the parsed model explicitly (default to "opus"):
```
Task(subagent_type="general-purpose", model=parsed_model or "opus", ...)
```

## Scope Definitions

### R1: Working Tree Only (`working`, default)
```
Scope: git diff --name-only (unstaged) + git diff --cached --name-only (staged)
Agents review ONLY files with uncommitted modifications.
```

### R2: Impact Radius (`impact`)
```
Scope: git diff files
     + files that import/reference changed files (1-hop via native code search)
```

### R3: Full Branch Diff (`branch`)
```
Scope: git diff main...HEAD --name-only (all changes since branch creation)
     + all files touched in any commit on this branch
```

## Review Aspects (ALL Run by Default)

Review agents use criteria from `agents/review-coordinator.md` and specialized agent configs (`security-reviewer.md`, `a11y-reviewer.md`).

| Aspect | What It Checks | Agent Reference |
|--------|---------------|----------------|
| **Code Quality** | Bugs, logic errors, patterns, architecture | `review-coordinator` |
| **Security (OWASP)** | OWASP Top 10, injection, auth, secrets | `security-reviewer` |
| **Standards** | Biome lint, TypeScript types, React patterns | Pre-review quality check |
| **Documentation** | Missing docs, incorrect comments | `review-coordinator` |
| **Design & A11y** | WCAG AAA, UI/UX patterns, consistency | `a11y-reviewer` |
| **Architecture** | SOLID, coupling, layer violations | `architecture-reviewer` |
| **Tests** | Missing coverage, test quality | `review-coordinator` |
| **Performance** | Bottlenecks, memory leaks, inefficiencies | `performance-reviewer` |

**Review agents reference specialized agent configs for domain-specific criteria but adapt to working in parallel batches.**

## Security & Design Included by Default

Security (OWASP Top 10) and Design (WCAG AAA) are now **always included** in default `/review` runs. No separate flags needed.

### OWASP Top 10 Quick Reference (Always Checked)

| ID | Category | Key Checks |
|----|----------|------------|
| A01 | Broken Access Control | RBAC, privilege escalation, IDOR |
| A02 | Security Misconfiguration | Default creds, verbose errors, debug modes |
| A03 | Supply Chain | Dependency pinning, lockfiles, vulnerability scanning |
| A04 | Cryptographic Failures | Plaintext passwords, weak encryption, hardcoded secrets |
| A05 | Injection | SQL, NoSQL, XSS, command injection |
| A06 | Outdated Components | Unused deps, CVE monitoring |
| A07 | Auth Failures | MFA, session management, failed login limits |
| A08 | Data Integrity | Signed data, secure CI/CD |
| A09 | Logging Failures | Auth logging, immutable logs, alerting |
| A10 | SSRF | URL validation, allowlists |

### WCAG AAA Quick Reference (Always Checked)

| Level | Criteria | Key Checks |
|-------|----------|------------|
| A (Must) | Basic accessibility | Alt text, semantic HTML, keyboard access |
| AA (Should) | Enhanced accessibility | 4.5:1 contrast, focus indicators, error messages |
| AAA (Best) | Premium accessibility | 7:1 contrast, descriptive links, plain language |

### Framework-Specific Security

**Next.js 16+:**
- Server Components can access secrets safely
- Filter sensitive data before passing to Client Components
- Use Server Actions for mutations (built-in CSRF protection)
- Use `taintObjectReference` for sensitive server data

**Node.js:**
- Input validation with Zod at API boundaries
- Rate limiting on auth endpoints
- Security headers with Helmet.js
- Never hardcode secrets - use `.env.local`

### TODO Format for Security & Design Issues

```typescript
// TODO-P1: SQL injection risk in user input - Review agent [ID]
// TODO-P1: Missing rate limit on auth endpoint - Review agent [ID]
// TODO-P1: Image missing alt text - WCAG 1.1.1 - Review agent [ID]
// TODO-P2: Color contrast 3.2:1 below 4.5:1 minimum (WCAG AA requires 4.5:1 for normal text, 3:1 for large text) - Review agent [ID]
```

## VERIFY+FIX Checklist Integration

Review agents include verification checks from `agents/verify-fix.md`, but in read-only/TODO-leaving mode (NOT auto-fixing). These checks ensure comprehensive review coverage beyond code logic.

### Additional Review Checks (TODO-Leaving Mode)

Review agents check these items and leave TODO comments where issues are found:

1. **Build Compatibility**
   - Verify changes don't introduce build errors
   - Check for breaking changes in imports/exports
   - TODO-P1 if build would fail

2. **Type Safety**
   - Missing type annotations
   - Unsafe type assertions (`any`, `as any`)
   - TODO-P2 for missing types, TODO-P1 for unsafe casts

3. **Lint & Code Style**
   - Violations of project lint rules (Biome/ESLint)
   - Inconsistent formatting patterns
   - TODO-P3 for style issues

4. **Dead Code Detection**
   - Unused imports in reviewed files
   - Unreferenced private functions
   - TODO-P3 for dead code cleanup

5. **CLAUDE.md Adherence**
   - Check if changes follow patterns documented in CLAUDE.md
   - Verify hook registrations match settings.json (if modified)
   - TODO-P2 if deviating from documented patterns

6. **Symbol Integrity**
   - Use code search to check for broken references
   - Verify changed symbols don't break downstream code
   - TODO-P1 if symbol changes break references

**Key Difference from verify-fix agent:**
- verify-fix: Auto-fixes simple issues immediately
- review agents: Leave TODO-P1/P2/P3 comments for ALL findings
- review agents: Do NOT modify code directly

**Reference:** See `agents/verify-fix.md` for full verification criteria. Review agents apply the same checklist but in read-only reporting mode.

**PR Review Integration:** See `agents/pr-review-base.md` for shared design review criteria used by both verify-fix and review agents.

## Workflow

### Step 0: Emit Start Signal

Output the skill started signal immediately, before any other processing:

```
**SKILL_STARTED:** review
```

### Step 1: Parse Arguments

```
Parse arguments left-to-right:
1. If "help" → show usage and exit
2. If "pr" → PR review mode (next arg = PR number or current branch)
3. First number → agent count (default: 10, hard cap: 10)
4. Second number → iteration count (default: 3)
5. Model keyword → "opus" | "sonnet" | "haiku" (default: "opus")
6. Scope keyword → "working" | "impact" | "branch" | "staged" (default: "working")
7. Remaining path → file or directory scope override
```

### Step 1.5: Quality Context Injection (Pre-Review)

Before spawning review agents, run quality checks to provide context:

```bash
# Check if tools are available before running
if command -v pnpm &>/dev/null; then
    # Run Biome linting with 2min timeout
    timeout 120 pnpm biome check --diagnostic-level=warn . 2>/dev/null || echo "Biome check failed or timed out"

    # Run Knip for dead code detection with 3min timeout
    timeout 180 pnpm knip --include unused,exports 2>/dev/null || echo "Knip check failed or timed out"

    # Run TypeScript type checking with 5min timeout
    timeout 300 pnpm tsc --noEmit 2>/dev/null || echo "TypeScript check failed or timed out"
else
    echo "Warning: pnpm not found - skipping quality checks"
fi
```

**Timeout specifications:**
- **Biome:** 2 minutes (fast linter, should complete quickly)
- **Knip:** 3 minutes (analyzes dependency graph, can be slow on large projects)
- **TypeScript:** 5 minutes (type-checking can be expensive on large codebases)

**Tool availability:** If `pnpm`, `biome`, or `knip` are not installed, the checks are skipped gracefully with warnings. Review continues with code-only analysis.

**Output handling:**
Capture results and inject into review agent prompts as context:
- Known lint issues → agents can reference in findings
- Dead exports → helps identify unused code
- Type errors → guides review to type safety issues

**If quality checks fail critically (blocking errors), report to user and ask if review should continue.**

### Step 2: Get Files to Review

```bash
# File extension filter for code files only
CODE_EXTS='\.ts$|\.tsx$|\.js$|\.jsx$|\.py$|\.go$|\.rs$|\.java$|\.kt$|\.c$|\.cpp$|\.h$'

# For working scope (default) - deduplicate unstaged + staged
FILES=$(git diff --name-only 2>/dev/null && git diff --cached --name-only 2>/dev/null | sort -u | grep -E "$CODE_EXTS")

# Handle git errors gracefully
if [ $? -ne 0 ]; then
    # Check for common issues
    if ! git rev-parse --git-dir &>/dev/null; then
        echo "Error: Not a git repository"
        exit 1
    elif git rev-parse --verify HEAD &>/dev/null; then
        # Detached HEAD or initial commit - use different commands
        if [ -z "$(git log --oneline -1 2>/dev/null)" ]; then
            echo "Error: No commits yet - cannot generate diff"
            exit 1
        fi
    fi
fi

# For staged scope
FILES=$(git diff --cached --name-only 2>/dev/null | grep -E "$CODE_EXTS")

# For impact scope
FILES=$(git diff --name-only 2>/dev/null | grep -E "$CODE_EXTS")
# PLUS: Use code search for each changed symbol

# For branch scope (with fallback for detached HEAD)
MAIN_BRANCH=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "main")
FILES=$(git diff ${MAIN_BRANCH}...HEAD --name-only 2>/dev/null | grep -E "$CODE_EXTS")

# For PR scope
gh pr diff [PR_NUMBER] --name-only | grep -E "$CODE_EXTS"

# For path scope
find "$SCOPE" -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.py" -o -name "*.go" -o -name "*.rs" \)
```

**Error handling:**
- **Not a git repo:** Detect and abort with clear error
- **No commits:** Detect initial state and abort (cannot diff)
- **Detached HEAD:** Use fallback logic to find main branch dynamically
- **File filtering:** Only review code files (not images, binaries, vendor files)
- **Deduplication:** `sort -u` removes duplicate files from unstaged + staged

### Step 3: Spawn Review Agents

Spawn agents using the **Task tool** with explicit model parameter:

```
Task(
  subagent_type="general-purpose",
  model=parsed_model or "opus",  # Default: "opus", override with "sonnet"/"haiku"
  description="Review: [aspect] [files]",
  prompt="...",
)
```

Each agent receives:
- Files to review (distributed across agents)
- All review aspects checklist (security + design + quality)
- Quality check results (Biome/Knip/TSC output)
- Context from CLAUDE.md and README.md
- Reference to specialized agent configs for domain criteria

**Agent naming convention:** `ralph-review-{aspect}-{n}` (e.g., `ralph-review-security-1`)

**Hard cap:** Maximum 10 agents regardless of input. If user requests >10, cap at 10.

Agents work in parallel analyzing ALL aspects:
1. Code quality and bugs
2. Security vulnerabilities (OWASP Top 10)
3. Standards compliance (Biome/TypeScript/React)
4. Documentation gaps
5. Design & accessibility (WCAG AAA)
6. Architecture concerns
7. Test coverage
8. Performance problems

### Step 4: TODO Comment Enforcement (MANDATORY)

All `/review` agents **MUST** leave TODO-P1/P2/P3 inline comments in source files. This is non-negotiable.

Review agents do NOT auto-fix issues. They REPORT findings as TODO comments.

### Step 5: Generate Report

**Report behavior:** ALWAYS **overwrites** `.claude/review-agents.md` on each review run. Previous findings are archived by appending timestamp to the old report (`.claude/review-agents-{timestamp}.md`).

Output to `.claude/review-agents.md`:

```markdown
# Review Summary

**Started:** [timestamp]
**Completed:** [timestamp]
**Scope:** [scope]
**Agents:** [N]
**Iterations:** [M]
**Model:** [model]

## Findings by Category

| Category | Count | Critical | High | Medium | Low |
|----------|-------|----------|------|--------|-----|
| Security | 3 | 1 | 2 | 0 | 0 |
| Code Quality | 5 | 0 | 2 | 2 | 1 |
| Standards | 8 | 0 | 0 | 5 | 3 |
...

## TODOs Added

| File | Line | Priority | Comment |
|------|------|----------|---------|
| src/auth.ts | 42 | P1 | SQL injection risk |
| src/api.ts | 156 | P2 | Consider memoization |

## Next Steps

- Run `/repotodo list` to see all TODOs
- Run `/repotodo P1 all` to fix critical issues first
- Re-run `/review` to verify fixes
```

## TODO Comment Format

Review agents leave inline comments using priority-based format:

```typescript
// TODO-P1: [critical issue] - Review agent [ID]     // Security, crashes, blocking
// TODO-P2: [important issue] - Review agent [ID]    // Bugs, performance, quality
// TODO-P3: [improvement] - Review agent [ID]        // Refactoring, docs, tests
```

**Priority mapping for review findings:**
| Finding Type | Priority |
|--------------|----------|
| Security vulnerabilities | P1 |
| Breaking bugs, crashes | P1 |
| Performance issues | P2 |
| Missing error handling | P2 |
| Code quality issues | P2 |
| Refactoring suggestions | P3 |
| Documentation gaps | P3 |
| Test coverage | P3 |

## Two Review Modes (Context-Dependent)

This skill is the **manual review** mode (`/review` command). It differs from plan-spawned reviews after `/start`:

| Aspect | This Skill (/review) | Plan-Spawned (after /start) |
|--------|---------------------|---------------------------|
| Model | Opus 4.5 (default) | Opus 4.5 |
| Agents | 10 (default) | 2-5 (dynamic) |
| Iterations | 3 (default) | 2-3 |
| TODOs | MUST leave TODO-P1/P2/P3 | NEVER leave TODOs |
| Behavior | Report only | Auto-fix + AskUserQuestion |
| Max Agents | 10 (hard cap) | 10 (hard cap) |
| Includes Security | Yes (OWASP Top 10) | Yes (OWASP Top 10) |
| Includes Design | Yes (WCAG AAA) | Yes (WCAG AAA) |

## PR Review Mode

When using `/review pr`:

```bash
# Get PR metadata
gh pr view [NUMBER] --json number,title,body,author,baseRefName,headRefName,additions,deletions,changedFiles

# Get diff
gh pr diff [NUMBER]

# Get existing comments
gh pr view [NUMBER] --json comments,reviews
```

Includes summary of existing PR discussion and unresolved comments.

## Examples

```bash
# Default review (10 agents, 3 iter, Opus, working tree, includes security + design)
/review

# Quick Sonnet scan (faster, lower cost)
/review 5 2 sonnet

# Quick Haiku scan (fastest, cheapest)
/review 3 1 haiku

# Review only staged files
/review 5 2 staged

# Impact-radius review (working + dependency analysis)
/review impact

# Full branch review
/review branch

# Review a specific file
/review 3 1 src/components/Button.tsx

# Review entire directory
/review 5 2 src/utils/

# Review current branch PR (full review with security + design)
/review pr

# Review specific PR
/review pr 123
```


## Emoji Review Output Format (MANDATORY)

All review report tables MUST use emoji-prefixed headers for visual scanning:

**Findings tables:**
```markdown
| # | ⚠️ Category | 🔴 Severity | 📄 File | 📋 Description |
|---|------------|------------|---------|---------------|
| 1 | 🔒 Security | 🔴 Critical | auth.ts | SQL injection |
| 2 | ⚡ Perf     | 🟡 Medium   | api.ts  | N+1 queries   |
```

**Summary tables:**
```markdown
| ✅ Category     | 📊 Count | 🔴 Critical | 🟡 High | 🟢 Low |
|----------------|---------|-----------|--------|-------|
| 🔒 Security    | 3       | 1         | 2      | 0     |
| ⚡ Performance  | 5       | 0         | 2      | 3     |
```

**Priority items:** 🔴 Critical, 🟡 Medium, 🟢 Low.
**Decision tables:** Each row gets a leading emoji for visual scanning.
**Comparison matrices:** Use emoji columns for at-a-glance status.

## Notes

- ALL aspects run by default: code quality, security (OWASP), design (WCAG AAA), architecture, tests, performance
- Security and design are now **always included** - no separate flags needed
- Review agents work in parallel and ONLY leave TODO-P1/P2/P3 comments (NO auto-fix)
- Quality checks (Biome/Knip/TSC) run before review to provide context
- TODO comments use standardized format with agent attribution
- Use `/repotodo` to process findings after review
- Re-run `/review` after fixes to verify
- Hard cap: 10 agents maximum
- Default model: Opus 4.5 (comprehensive analysis with security + design)
- Use `sonnet` or `haiku` override for faster/cheaper scans
