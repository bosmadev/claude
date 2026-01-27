---
name: review
description: "Code review: multi-aspect analysis OR PR review. Use '/review' for code quality, '/review pr [N]' for pull requests, '/review security' for OWASP audit."
argument-hint: "[agents] [iterations] [scope|pr number|security]"
user-invocable: true
context: main
---

# /review - Multi-Aspect Code Review

**When invoked, immediately output:** `**SKILL_STARTED:** review`

Unified code review that runs ALL aspects by default. Spawns parallel review agents to analyze code comprehensively.

## Help Command

```
/review help
```

Displays usage information and examples.

## Usage

### Default (5 agents, 2 iterations, all aspects)

```
/review
```

Runs all review aspects on git diff files.

### With Agent and Iteration Count

```
/review 10 3
```

Runs 10 agents with 3 iterations each on all aspects.

### With Scope

```
/review 5 2 staged          # Only staged files
/review 5 2 src/components/  # Specific directory
/review 5 2 path/to/file.ts  # Specific file
```

### PR Review

```
/review pr                   # Current branch PR
/review pr 123               # PR #123
```

## Default Values

- **Agents:** 5
- **Iterations:** 2
- **Scope:** git (uncommitted changes)
- **Aspects:** ALL (no aspect filtering)

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
// TODO-security: SQL injection risk in user input - Review agent [ID]
// TODO-security: Missing rate limit on auth endpoint - Review agent [ID]
// TODO-security: Hardcoded API key detected - Review agent [ID]
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
1. If "pr" -> PR review mode
2. First number -> agent count (default: 5)
3. Second number -> iteration count (default: 2)
4. Remaining text -> scope (default: "git")
```

### Step 2: Get Files to Review

```bash
# For git scope
FILES=$(git diff --name-only)

# For staged scope
FILES=$(git diff --cached --name-only)

# For PR scope
gh pr diff [PR_NUMBER] --name-only

# For path scope
find "$SCOPE" -type f \( -name "*.ts" -o -name "*.tsx" \)
```

### Step 3: Spawn Review Agents

Each agent receives:
- Files to review
- All review aspects checklist
- Context from CLAUDE.md and README.md

Agents work in parallel analyzing:
1. Code quality and bugs
2. Security vulnerabilities
3. Standards compliance
4. Documentation gaps
5. Design issues
6. Architecture concerns
7. Test coverage
8. Performance problems

### Step 4: Generate Report

Output to `.claude/review-agents.md`:

```markdown
# Review Summary

**Started:** [timestamp]
**Completed:** [timestamp]
**Scope:** [scope]
**Agents:** [N]
**Iterations:** [M]

## Findings by Category

| Category | Count | Critical | High | Medium | Low |
|----------|-------|----------|------|--------|-----|
| Security | 3 | 1 | 2 | 0 | 0 |
| Code Quality | 5 | 0 | 2 | 2 | 1 |
| Standards | 8 | 0 | 0 | 5 | 3 |
...

## TODOs Added

| File | Line | Category | Comment |
|------|------|----------|---------|
| src/auth.ts | 42 | security | SQL injection risk |
| src/api.ts | 156 | perf | Consider memoization |

## Next Steps

- Run `/repotodo list` to see all TODOs
- Run `/repotodo security 1` to fix security issues
- Re-run `/review` to verify fixes
```

## TODO Comment Format

Review agents leave inline comments:

```typescript
// TODO-fix: [description] - Review agent [ID]
// TODO-security: [description] - Review agent [ID]
// TODO-perf: [description] - Review agent [ID]
// TODO-a11y: [description] - Review agent [ID]
// TODO-docs: [description] - Review agent [ID]
// TODO-test: [description] - Review agent [ID]
// TODO-arch: [description] - Review agent [ID]
```

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
# Quick review of uncommitted changes (all aspects)
/review

# Thorough review with more agents
/review 10 3

# Review only staged files
/review 5 2 staged

# Review a specific file
/review 3 1 src/components/Button.tsx

# Review entire directory
/review 5 2 src/utils/

# Review current branch PR
/review pr

# Review specific PR
/review pr 123
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

## Notes

- ALL aspects run by default (no filtering)
- Review agents work in parallel
- TODO comments use standardized format
- Use `/repotodo` to process findings
- Re-run `/review` after fixes to verify
- Prefer Serena tools for semantic code analysis
