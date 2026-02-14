---
context: fork
name: ask
description: Query multiple AI models (Gemini via GSwarm, GPT/O3, Ollama) in parallel or individually for comparison, consensus, or code review
when_to_use: When you need to compare responses across different models, get multi-model consensus on complex decisions, or run parallel code reviews
---

# /ask - Multi-Model Query System

Query multiple AI models directly via their native APIs for comparison, consensus, or specialized review.

## Architecture

Direct API calls (no MCP overhead):
- **GSwarm/Gemini**: `http://localhost:4000/v1/chat/completions` (OpenAI-compatible proxy)
- **OpenAI**: `https://api.openai.com/v1/chat/completions` (GPT-4, O3, requires `OPENAI_API_KEY`)
- **Ollama**: `http://localhost:11434/api/generate` (local models for privacy)

## Usage

```bash
# Single model query (chat mode)
/ask "Explain async/await in Python"
/ask "Explain async/await" --models gemini-2.0-flash

# Multi-model consensus
/ask "Should I use REST or GraphQL?" --mode consensus --models gemini-2.0-flash,gpt-4o,llama3.2

# Code review with multiple models
/ask "Review this auth flow" --mode codereview --models gemini-2.0-flash,gpt-4o

# Custom timeout and format
/ask "Complex query here" --timeout 60 --format json --models gemini-2.0-flash,gpt-4o
```

## Modes

| Mode | Description | Output |
|------|-------------|--------|
| `chat` | Single model query (default) | Plain text response |
| `consensus` | All models answer independently, compare results | Side-by-side table with differences highlighted |
| `codereview` | Send code context to all models, aggregate findings | Unified findings list with severity, file, line |

## Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `question` | string | (required) | Question or instruction to send to models |
| `--models` | string | `gemini-2.0-flash` | Comma-separated model list |
| `--mode` | string | `chat` | Query mode: `chat`, `consensus`, `codereview` |
| `--timeout` | int | 30 | Timeout per model (seconds) |
| `--format` | string | `table` | Output format: `table`, `markdown`, `json` |

## Supported Models

Provider auto-detection from model name:

| Model Pattern | Provider | Endpoint |
|---------------|----------|----------|
| `gemini*` | GSwarm | `http://localhost:4000` |
| `gpt*`, `o3*` | OpenAI | `https://api.openai.com` |
| `llama*`, `codellama*`, `deepseek*` | Ollama | `http://localhost:11434` |

**Common models:**
- GSwarm: `gemini-2.0-flash`, `gemini-2.0-flash-thinking`, `gemini-1.5-pro`
- OpenAI: `gpt-4o`, `gpt-4o-mini`, `o3-mini`
- Ollama: `llama3.2`, `codellama`, `deepseek-coder`

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENAI_API_KEY` | For GPT/O3 | — | OpenAI API key |
| `GSWARM_BASE_URL` | No | `http://localhost:4000` | GSwarm Gemini proxy |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama local endpoint |

## Examples

### Chat Mode (Single Model)

```bash
/ask "What's the difference between composition and inheritance?"
```

**Output:**
```
[gemini-2.0-flash]:
Composition and inheritance are both mechanisms for code reuse, but they differ in their approach...
```

### Consensus Mode (Multi-Model Comparison)

```bash
/ask "Should I use microservices for a 5-person team?" --mode consensus --models gemini-2.0-flash,gpt-4o,llama3.2
```

**Output:**
```
┌───────────────────┬─────────────────────────────────────────────┬─────────────┐
│ Model             │ Response (first 200 chars)                  │ Consensus   │
├───────────────────┼─────────────────────────────────────────────┼─────────────┤
│ gemini-2.0-flash  │ For a 5-person team, microservices are...  │ No (3/3) ❌ │
│ gpt-4o            │ I'd recommend starting with a modular...    │ No (3/3) ❌ │
│ llama3.2          │ Microservices add complexity for small...   │ No (3/3) ❌ │
└───────────────────┴─────────────────────────────────────────────┴─────────────┘

**Consensus:** All models agree — avoid microservices for small teams
**Common themes:** Complexity overhead, small team agility, monolith-first approach
```

### Code Review Mode

```bash
/ask "Review authentication flow in src/auth.ts" --mode codereview --models gemini-2.0-flash,gpt-4o
```

**Output:**
```
┌──────────┬─────────────────┬──────────┬───────────────────────────────────────────┐
│ Severity │ File            │ Line     │ Finding                                   │
├──────────┼─────────────────┼──────────┼───────────────────────────────────────────┤
│ HIGH     │ src/auth.ts     │ 42       │ JWT secret hardcoded (gemini-2.0-flash)   │
│ HIGH     │ src/auth.ts     │ 42       │ Exposed secret key (gpt-4o)               │
│ MEDIUM   │ src/auth.ts     │ 58       │ No rate limiting on login (gemini)        │
│ LOW      │ src/auth.ts     │ 73       │ Consider refresh tokens (gpt-4o)          │
└──────────┴─────────────────┴──────────┴───────────────────────────────────────────┘
```

## Error Handling

- **Timeout**: Per-model timeout (default 30s), continues with other models if one times out
- **Unavailable provider**: Gracefully skips unavailable endpoints, reports in output
- **Partial success**: Returns responses from successful models, warns about failures

**Exit codes:**
- `0`: All models succeeded
- `1`: All models failed
- `2`: Partial success (some models failed)

## When to Use

✅ **Use /ask when:**
- Comparing model perspectives on architectural decisions
- Getting consensus on ambiguous requirements
- Running parallel code reviews with different model strengths
- Testing prompt quality across providers
- Debugging LLM responses (one model explains another's output)

❌ **Don't use /ask when:**
- You need context from files in the repo (use main Claude Code session instead)
- Task requires tool use (Read/Write/Bash) — /ask is query-only
- Single model is sufficient (wastes resources running multiple APIs)

## Implementation Notes

**Parallel execution:** Uses `asyncio` for concurrent API calls (consensus/codereview modes)

**Provider detection:** Regex match on model name prefix:
```python
if re.match(r'^gemini', model):
    provider = 'gswarm'
elif re.match(r'^(gpt|o3)', model):
    provider = 'openai'
elif re.match(r'^(llama|codellama|deepseek)', model):
    provider = 'ollama'
```

**Context preservation:** For `codereview` mode, automatically reads changed files from `git diff` and includes in context

**Output formatting:**
- `table`: Rich terminal tables (default)
- `markdown`: GitHub-flavored markdown tables
- `json`: Structured JSON for programmatic use

---

## Argument Hints

| Command | Description |
|---------|-------------|
| `/ask "question"` | Single model query (gemini-2.0-flash) |
| `/ask "question" --models gpt-4o` | Query specific model |
| `/ask "question" --mode consensus --models gemini-2.0-flash,gpt-4o` | Multi-model consensus |
| `/ask "question" --mode codereview --models gemini-2.0-flash,gpt-4o` | Multi-model code review |
| `/ask "question" --timeout 60` | Custom timeout |
| `/ask "question" --format json` | JSON output |
| `/ask help` | Show usage |
