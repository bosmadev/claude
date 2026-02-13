---
name: quality
description: "[DEPRECATED] Use /review for quality checks. Migrate to: /rule for behavior rules, VERIFY+FIX for audits."
argument-hint: "(deprecated - use /review instead)"
user-invocable: false
---

# Quality Skill

⚠️ **DEPRECATED**: This skill is deprecated and will be removed in a future release.

**Use instead:**
- **Quality checks (lint, types, dead-code)**: Run automatically in VERIFY+FIX phase during `/start`
- **CLAUDE.md audit**: Automatic in VERIFY+FIX phase (agent uses AskUserQuestion for proposals)
- **Setup recommendations**: Automatic in VERIFY+FIX phase (agent uses AskUserQuestion for proposals)
- **Design review**: Included in default `/review` and VERIFY+FIX phase
- **Security audit**: Included in default `/review`
- **Behavior rules**: Use `/rule add` command directly

---

**When invoked, immediately output:** `**SKILL_STARTED:** quality`

Unified code quality and Claude Code configuration management.

## Usage

```
/quality                     - Run all quality checks (lint, types, dead-code)
/quality audit               - Audit CLAUDE.md files
/quality setup               - Analyze codebase for Claude automations
/quality design [path]       - Frontend design review
/quality rule "<behavior>"   - Add behavior rule to settings.json
/quality help                - Show this help
```

## Help Command

When arguments equal "help":

```
/quality - Code quality and Claude configuration

Usage:
  /quality [command] [args]

Commands:
  (no args)        Run all quality checks (Biome, Knip, TypeScript)
  audit            Audit CLAUDE.md files (score, recommend improvements)
  setup            Analyze codebase for Claude automations
  design [path]    Frontend design review
  rule "<text>"    Add behavior rule to settings.json
  help             Show this help

Examples:
  /quality
  /quality audit
  /quality setup
  /quality design src/components/
  /quality rule "Never use eval()"
```

---

## Command: /quality (default)

Run all code quality checks on the current project.

**Checks performed:**
1. **Biome lint** - Run `pnpm biome check --write .`
2. **Knip dead-code** - Run `pnpm knip`
3. **Type check** - Run `pnpm tsc --noEmit`

**Workflow:**
```bash
# 1. Run Biome
pnpm biome check --write .

# 2. Run Knip
pnpm knip

# 3. Type check
pnpm tsc --noEmit
```

**Output:** Report violations grouped by category with file paths and line numbers.

---

## Command: /quality audit

Audit and improve CLAUDE.md files across the codebase.

### File Types & Locations

| Type | Location | Purpose |
|------|----------|---------|
| Project root | `./CLAUDE.md` | Primary project context (shared) |
| Local overrides | `./.claude.local.md` | Personal settings (gitignored) |
| Global defaults | `~/.claude/CLAUDE.md` | User-wide defaults |
| Package-specific | `./packages/*/CLAUDE.md` | Module-level context |

### Quality Assessment Criteria

| Criterion | Weight | Check |
|-----------|--------|-------|
| Commands/workflows documented | High | Are build/test/deploy commands present? |
| Architecture clarity | High | Can Claude understand codebase structure? |
| Non-obvious patterns | Medium | Are gotchas and quirks documented? |
| Conciseness | Medium | No verbose explanations or obvious info? |
| Currency | High | Does it reflect current codebase state? |
| Actionability | High | Are instructions executable, not vague? |

**Quality Scores:**
- **A (90-100)**: Comprehensive, current, actionable
- **B (70-89)**: Good coverage, minor gaps
- **C (50-69)**: Basic info, missing key sections
- **D (30-49)**: Sparse or outdated
- **F (0-29)**: Missing or severely outdated

### Workflow

1. **Discovery**: Find all CLAUDE.md files
2. **Assessment**: Evaluate each file against criteria
3. **Report**: Output quality scores before any updates
4. **Updates**: After user confirmation, apply targeted improvements

---

## Command: /quality setup

Analyze codebase and recommend Claude Code automations.

### What It Recommends

- **MCP Servers** - External integrations (context7, Playwright)
- **Skills** - Packaged expertise (Plan agent, frontend-design)
- **Hooks** - Automatic actions (auto-format, auto-lint)
- **Subagents** - Specialized reviewers (security, performance)

---

## Command: /quality design [path]

Review frontend code for design quality.

### Design Thinking

Before coding, understand context and commit to a BOLD aesthetic direction:
- **Purpose**: What problem does this interface solve?
- **Tone**: Pick an extreme (minimal, maximalist, retro-futuristic, luxury, playful, etc.)
- **Constraints**: Framework, performance, accessibility
- **Differentiation**: What makes this UNFORGETTABLE?

### Aesthetics Guidelines

Focus on:
- **Typography**: Distinctive fonts, not generic (avoid Arial, Inter)
- **Color & Theme**: Cohesive aesthetic with CSS variables
- **Motion**: Animations for effects and micro-interactions
- **Spatial Composition**: Asymmetry, overlap, diagonal flow, negative space
- **Backgrounds**: Atmosphere and depth, not just solid colors

---

## Command: /quality rule "<behavior>"

Add a behavior rule to prevent unwanted actions.

### Rule Types

| Type | Trigger | Example |
|------|---------|---------|
| bash | Bash commands | "Never use rm -rf" |
| file | File writes | "Block console.log in production code" |
| all | Any action | "Always ask before deleting files" |

---

## Quick Reference

### Biome (JS/TS)

- If code isn't Biome compliant, it isn't finished
- Enforce strict linting - if Biome complains, the code is wrong
- Sort imports automatically
- **PROHIBIT** eslint or prettier configurations

### Knip (Dead Code)

- Aggressive dead code stripping - export only what is used
- If a file is not imported by entry or tests, suggest deletion

### TypeScript

- Never use any or unknown as type constraints
- Use as const instead of enums
- Use export type and import type for types
- No @ts-ignore or non-null assertions (!)

### React/JSX

- Don't define components inside other components
- Specify all dependencies in hooks
- Use <>...</> instead of <Fragment>
- No Array index as keys
- Accompany onClick with keyboard handlers

### Accessibility (a11y)

- Use semantic elements instead of ARIA roles where possible
- Ensure keyboard navigation for all interactive elements
- Always include type attribute for buttons

---

