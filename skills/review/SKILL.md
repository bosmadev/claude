---
name: review
description: "Code review: multi-aspect analysis OR PR review. Use '/review' for code quality, '/review pr [N]' for pull requests, '/review security' for OWASP audit."
argument-hint: "[agents] [iterations] [opus|sonnet|haiku] [working|impact|branch|staged|pr|security]"
user-invocable: true
---

# /review - Multi-Aspect Code Review

**When invoked, immediately output:** `**SKILL_STARTED:** review`

Unified code review that runs ALL aspects by default. Spawns parallel review agents to analyze code comprehensively.

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
| Model | Sonnet 4.5 | opus / sonnet / haiku |
| Scope | working | working / impact / branch / staged / path / pr |

### Override Syntax

```
/review                          → 10 agents, 3 iterations, Sonnet 4.5, working scope
/review N                        → N agents, 3 iterations, Sonnet 4.5
/review N M                      → N agents, M iterations, Sonnet 4.5
/review N M opus                 → N agents, M iterations, Opus 4.5
/review N M haiku                → N agents, M iterations, Haiku
/review working                  → 10 agents, working tree only (R1)
/review impact                   → 10 agents, working tree + Serena impact radius (R2)
/review branch                   → 10 agents, full branch diff since main (R3)
/review 5 2 opus branch          → 5 agents, 2 iter, Opus, full branch diff
/review pr                       → Current branch PR
/review pr 123                   → PR #123
/review security                 → Security-focused OWASP audit
/review security --owasp         → Full OWASP Top 10 audit
```

## Model Routing (3-Layer System)

This skill runs in the **main Opus conversation** (no `context: fork`). It spawns review Task agents with explicit model routing via L3 per-agent override:

| Layer | Mechanism | Effect |
|-------|-----------|--------|
| L1: Global Default | `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` (SessionStart) | Subagents default to Sonnet |
| L3: Per-Agent Override | `model="sonnet"` in Task() calls | Each review agent uses parsed model |

**Implementation:** When spawning Task agents, pass the parsed model explicitly:
```
Task(subagent_type="general-purpose", model=parsed_model, ...)
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
     + files that import/reference changed files (1-hop via Serena)
     + mcp__serena__find_referencing_symbols for changed symbols
```

### R3: Full Branch Diff (`branch`)
```
Scope: git diff main...HEAD --name-only (all changes since branch creation)
     + all files touched in any commit on this branch
```

## Review Aspects (ALL Run by Default)

| Aspect | What It Checks |
|--------|---------------|
| **Code Quality** | Bugs, logic errors, patterns, architecture |
| **Security** | OWASP vulnerabilities, injection, auth issues |
| **Standards** | Biome lint, TypeScript types, React patterns |
| **Documentation** | Missing docs, incorrect comments |
| **Design** | UI/UX patterns, accessibility, consistency |
| **Architecture** | SOLID, coupling, layer violations |
| **Tests** | Missing coverage, test quality |
| **Performance** | Bottlenecks, memory leaks, inefficiencies |

## Security-Focused Review

`/review security` or `/review security --owasp`

Runs OWASP Top 10:2025 focused security audit.

### OWASP Top 10 Quick Reference

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

### Security TODO Format

```typescript
// TODO-P1: SQL injection risk in user input - Review agent [ID]
// TODO-P1: Missing rate limit on auth endpoint - Review agent [ID]
// TODO-P1: Hardcoded API key detected - Review agent [ID]
```

### Key Security Checks

1. Are sensitive data (API keys, tokens) hardcoded?
2. Is `target="_blank"` used without `rel="noopener"`?
3. Is user input validated at API boundaries?
4. Are passwords stored in plaintext?
5. Is RBAC enforced server-side?

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
3. If "security" → security-focused mode
4. First number → agent count (default: 10, hard cap: 10)
5. Second number → iteration count (default: 3)
6. Model keyword → "opus" | "sonnet" | "haiku" (default: "sonnet")
7. Scope keyword → "working" | "impact" | "branch" | "staged" (default: "working")
8. Remaining path → file or directory scope override
```

### Step 2: Get Files to Review

```bash
# For working scope (default)
FILES=$(git diff --name-only && git diff --cached --name-only)

# For staged scope
FILES=$(git diff --cached --name-only)

# For impact scope
FILES=$(git diff --name-only)
# PLUS: Use mcp__serena__find_referencing_symbols for each changed symbol

# For branch scope
FILES=$(git diff main...HEAD --name-only)

# For PR scope
gh pr diff [PR_NUMBER] --name-only

# For path scope
find "$SCOPE" -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.py" \)
```

### Step 3: Spawn Review Agents

Spawn agents using the **Task tool** with explicit model parameter:

```
Task(
  subagent_type="general-purpose",
  model=parsed_model,       # "sonnet" default, "opus"/"haiku" if overridden
  description="Review: [aspect] [files]",
  prompt="...",
)
```

Each agent receives:
- Files to review (distributed across agents)
- All review aspects checklist
- Context from CLAUDE.md and README.md

**Agent naming convention:** `ralph-review-{aspect}-{n}` (e.g., `ralph-review-security-1`)

**Hard cap:** Maximum 10 agents regardless of input. If user requests >10, cap at 10.

Agents work in parallel analyzing:
1. Code quality and bugs
2. Security vulnerabilities
3. Standards compliance
4. Documentation gaps
5. Design issues
6. Architecture concerns
7. Test coverage
8. Performance problems

### Step 4: TODO Comment Enforcement (MANDATORY)

All `/review` agents **MUST** leave TODO-P1/P2/P3 inline comments in source files. This is non-negotiable.

Review agents do NOT auto-fix issues. They REPORT findings as TODO comments.

### Step 5: Generate Report

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
| Model | Sonnet 4.5 (default) | Opus 4.5 |
| Agents | 10 (default) | 2-5 (dynamic) |
| Iterations | 3 (default) | 2-3 |
| TODOs | MUST leave TODO-P1/P2/P3 | NEVER leave TODOs |
| Behavior | Report only | Auto-fix + AskUserQuestion |
| Max Agents | 10 (hard cap) | 10 (hard cap) |

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
# Default review (10 agents, 3 iter, Sonnet, working tree)
/review

# Thorough Opus review of full branch
/review 10 3 opus branch

# Quick Haiku scan
/review 3 1 haiku

# Review only staged files
/review 5 2 staged

# Impact-radius review
/review impact

# Review a specific file
/review 3 1 src/components/Button.tsx

# Review entire directory
/review 5 2 src/utils/

# Review current branch PR
/review pr

# Review specific PR
/review pr 123

# Security audit
/review security
/review security --owasp
```

## Serena-Powered Semantic Analysis

Leverage Serena MCP tools for deeper code understanding:

### Pre-Review Setup

```
1. mcp__serena__activate_project - Ensure project is active
2. mcp__serena__get_symbols_overview - Get file structure before reading
```

### Symbol Analysis Workflow

For each modified file:

```
1. mcp__serena__get_symbols_overview(relative_path=<file>)
   → Understand class/function structure

2. For each modified symbol:
   mcp__serena__find_symbol(name_path=<symbol>, include_body=True)
   → Get full implementation context

3. mcp__serena__find_referencing_symbols(name_path=<symbol>)
   → Find all callers to assess impact
```

### Impact Assessment Checklist

Use Serena to verify:

- [ ] All modified public APIs have updated callers
- [ ] Renamed symbols are updated across codebase
- [ ] Deleted symbols have no remaining references
- [ ] New symbols follow existing naming conventions

### Dead Code Detection

Cross-reference symbols with no references:

```
1. mcp__serena__get_symbols_overview(depth=2) - Get all symbols
2. For each symbol: mcp__serena__find_referencing_symbols
3. Report symbols with 0 references as potential dead code
```

### Coupling Analysis

Use `mcp__serena__find_referencing_symbols` to detect:

- Highly coupled modules (>20 references)
- Circular dependencies (A→B→A)
- Orphan code (0 references)

### Serena Memory for Review Context

```
mcp__serena__write_memory("review-context", <architectural decisions>)
mcp__serena__read_memory("review-context") - Recall for subsequent reviews
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

- ALL aspects run by default (no filtering)
- Review agents work in parallel
- TODO comments use standardized format
- Use `/repotodo` to process findings
- Re-run `/review` after fixes to verify
- Prefer Serena tools for semantic code analysis
- Hard cap: 10 agents maximum
- Default model: Sonnet 4.5 (cost-effective for bulk scanning)
