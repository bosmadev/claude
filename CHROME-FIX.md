# Claude in Chrome – Windows Named Pipe Fix

**Created:** 2026-02-06
**Last Updated:** 2026-02-07
**Claude Code:** 2.1.34
**OS:** Windows 11 (NT 10.0.26100)
**Status:** FULLY FIXED (both Terminal CLI and VS Code IDE)

## The Bug

`claude-in-chrome` MCP tools always return "Browser extension is not connected" on Windows.

### Root Cause

Two independent bugs:

1. **Bun stdin crash**: `claude.exe` (Bun v1.3.5) panics on stdin in `--chrome-native-host` mode (GitHub #22901)
2. **Socket path discovery**: `Gc4()` function never includes Windows named pipe paths — only returns `os.tmpdir()` filesystem paths

```
Gc4() returns:
  C:\Users\...\AppData\Local\Temp\claude-mcp-browser-bridge-{user}  <- filesystem path
  /tmp/claude-mcp-browser-bridge-{user}                              <- Unix path

Native host listens on:
  \\.\pipe\claude-mcp-browser-bridge-{user}                          <- named pipe
```

Windows named pipes (`\\.\pipe\NAME`) and filesystem paths (`C:\path\file`) are in completely separate OS namespaces (Object Manager vs NTFS). `net.createConnection(tmpdirPath)` calls `CreateFileW` which searches NTFS — can never find the pipe.

### Why `.mcp.json` Override Doesn't Work

The name `claude-in-chrome` is **reserved** — `claude mcp add` rejects it, and `.mcp.json` entries are silently ignored at runtime. Different-named servers get tool name deduplication (tools hidden).

### Why `claude.exe` Can't Be Patched

`claude.exe` is a Bun standalone binary with embedded, compressed JavaScript. The source code (cli.js) is not stored as plain text.

## Complete Fix (WORKING)

### Fix Architecture

| Context | Problem | Solution |
|---------|---------|----------|
| **Native Host** | Bun crashes on stdin | `chrome-native-host.bat` uses `node.exe + patched cli.js` |
| **Terminal CLI** | `process.execPath` = `claude.exe` (Bun) | Use npm `claude.cmd` — `process.execPath` becomes `node.exe` |
| **VS Code IDE** | Extension uses bundled `claude.exe` | `claudeCode.claudeProcessWrapper` setting → `claude-chrome-wrapper.cmd` |

### 1. Native Host Crash (Bun stdin issue)

**Problem:** `claude.exe` (Bun v1.3.5) crashes on stdin in `--chrome-native-host` mode.
**Fix:** Isolated Node.js install with `cli.js`, `.bat` rewrites to use `node.exe + cli.js`.

| File | Purpose |
|------|---------|
| `~/.claude/chrome/chrome-native-host.bat` | Wrapper: uses `node.exe` instead of `claude.exe` |
| `~/.claude/chrome/node_host/` | Isolated npm install of `@anthropic-ai/claude-code` |
| `~/.claude/scripts/fix-chrome-native-host.py` | Self-healing hook: rewrites `.bat` if overwritten |

### 2. Gc4 Patch (in Node.js cli.js)

**Problem:** `Gc4()` doesn't include `\\.\pipe\` paths on Windows.
**Fix:** Patch injected before `return A}` in `Gc4()`:

```javascript
if(qCY()==="win32"){let W=`\\\\.\\pipe\\${K}`;if(!A.includes(W))A.push(W)}
```

Applied to BOTH:
- `~/.claude/chrome/node_host/node_modules/@anthropic-ai/claude-code/cli.js`
- `D:\nvm4w\nodejs\node_modules\@anthropic-ai\claude-code\cli.js` (npm global)

### 3. Terminal CLI Fix (npm install)

**Problem:** Standalone `claude.exe` uses `process.execPath` → itself (Bun binary) for MCP server spawning.
**Fix:** Install npm `@anthropic-ai/claude-code` globally. The npm wrapper `claude.cmd` uses `node.exe cli.js`, so `process.execPath` = `node.exe` and MCP servers use the patched cli.js.

```bash
npm install -g @anthropic-ai/claude-code@2.1.34
```

**PATH resolution:** `claude.cmd` (npm) takes precedence over `claude.exe` (standalone) because npm bin dir is earlier in PATH.

**Trade-offs:**
- No colored diffs in terminal (Bun feature, not available in Node.js)
- Manual version sync on updates (self-healing hook handles Gc4 re-patching)
- Slightly slower startup

### 4. VS Code IDE Fix (claudeProcessWrapper)

**Problem:** VS Code extension uses its own bundled `claude.exe` binary at `d:\VSC\extensions\anthropic.claude-code-{version}-win32-x64\resources\native-binary\claude.exe`.

**Discovery:** The extension's `package.json` defines `claudeCode.claudeProcessWrapper` — a VS Code setting that overrides the executable used to launch Claude processes.

**How it works (from extension.js `getClaudeBinary()`):**
```javascript
// Without wrapper:
// pathToClaudeCodeExecutable = "d:\VSC\...\claude.exe"
// executableArgs = []

// With wrapper:
// pathToClaudeCodeExecutable = wrapper_path
// executableArgs = ["d:\VSC\...\claude.exe"]
// Chrome MCP: wrapper_path --claude-in-chrome-mcp (no executableArgs)
// Normal:     wrapper_path d:\VSC\...\claude.exe [claude_args...]
```

**Fix:** Set `claudeCode.claudeProcessWrapper` in VS Code settings:

```json
{
  "claudeCode.claudeProcessWrapper": "~/.claude\\chrome\\claude-chrome-wrapper.cmd"
}
```

**Wrapper script** (`~/.claude/chrome/claude-chrome-wrapper.cmd`):
- Intercepts `--claude-in-chrome-mcp` → delegates to `node.exe + patched cli.js`
- Everything else → passes through to original binary (`%*`)

## Verification

### Manual MCP Test (PASSES)

```bash
# Direct: node.exe + patched cli.js
node ~/.claude/chrome/node_host/.../cli.js --claude-in-chrome-mcp
# -> INIT: {"name": "Claude in Chrome", "version": "1.0.0"}
# -> TOOLS (17): javascript_tool, read_page, find, ...

# Wrapper: same result through wrapper.cmd
wrapper.cmd --claude-in-chrome-mcp
# -> INIT: {"name": "Claude in Chrome", "version": "1.0.0"}
```

### IDE Connection Safety (PASSES)

- `mcp__ide__getDiagnostics` returns valid data
- VS Code extension continues to use its own bundled binary for normal operations
- Wrapper only intercepts `--claude-in-chrome-mcp`, passes everything else through

## File Inventory

| File | Location | Purpose |
|------|----------|---------|
| `chrome-native-host.bat` | `~/.claude/chrome/` | Native host launcher (node.exe) |
| `claude-chrome-wrapper.cmd` | `~/.claude/chrome/` | VS Code process wrapper (intercepts Chrome MCP) |
| `node_host/` | `~/.claude/chrome/` | Isolated npm install |
| `cli.js` (patched) | `~/.claude/chrome/node_host/.../` | Gc4 patch applied |
| `cli.js` (patched) | `D:\nvm4w\nodejs\node_modules\...` | Gc4 patch applied (npm global) |
| `fix-chrome-native-host.py` | `~/.claude/scripts/` | Self-healing hook |
| `.mcp.json` | Project root | Override (reserved name, limited effectiveness) |

## Setup Instructions

### Terminal CLI

```bash
# 1. Install npm version alongside standalone
npm install -g @anthropic-ai/claude-code@2.1.34

# 2. Patch Gc4 in npm cli.js (or let self-healing hook do it)
# The hook at ~/.claude/scripts/fix-chrome-native-host.py handles this

# 3. Launch via claude.cmd (npm) instead of claude.exe (standalone)
claude  # now uses npm version via PATH priority
```

### VS Code IDE

```json
// In VS Code settings.json:
{
  "claudeCode.claudeProcessWrapper": "~/.claude\\chrome\\claude-chrome-wrapper.cmd"
}
```

## What Anthropic Needs to Fix

### Option A: Patch Gc4() (minimal fix, 3 lines)

```javascript
// In function Gc4(), before 'return A}':
if (process.platform === "win32") {
  const pipePath = `\\\\.\\pipe\\${K}`;
  if (!A.includes(pipePath)) A.push(pipePath);
}
```

### Option B: Use `socketPath` as primary (best)

The `uW6()` function already returns the correct `\\.\pipe\` path on Windows. The bridge connector should include it in the search list.

### Option C: Allow `.mcp.json` to override reserved names

Let users substitute `node.exe + patched cli.js` for the built-in `claude.exe`.

## Related Issues

- GitHub #23828: Our bug report with full analysis and working fix
- GitHub #23526: Same root cause, community patch for npm installs
- GitHub #23739: Bun crash on `--chrome-native-host` (high-priority)
- GitHub #22890: "not connected despite native host running"
- GitHub #23082: "extension executes but CLI receives not connected"
- GitHub #23218, #22025, #21300: Various reports of Windows connection failure
- GitHub #22416, #21935: Bun named pipe crash reports
