---
name: launch
description: Run debug mode and browser testing for visual verification. Use when you need to visually verify UI changes, check for visual regressions, or test interactive elements. Manual invocation only - use /launch to run.
argument-hint: "[--only <browser>] [--skip <browser>] [help]"
user-invocable: true
context: fork
---

# Launch Workflow

**When invoked, immediately output:** `**SKILL_STARTED:** launch`

**Note:** This skill requires manual invocation (`/launch`). It does not auto-trigger.

## Purpose

Interactive launch tool with animated orange-themed UI providing:
- Dev server modes (debug + standard, hot reload)
- Production server mode (optimized build)
- Cloudflare tunnel support for public access
- ALL 3 browsers enabled by default
- Interactive browser toggle menu
- Automatic process cleanup and cache clearing
- System stats display (CPU, RAM, Node memory)

## Help Command

When arguments equal "help":

```
/launch - Interactive launch tool with visual app verification

Usage:
  /launch [options]

Interactive Menu:
  [1] Dev Debug      Hot reload, DEBUG=true, all browsers
  [2] Dev Standard   Hot reload, standard logging, all browsers
  [3] Production     Build + start optimized server
  [4] Tunnel         Production + Cloudflare tunnel
  [B] Browsers       Toggle individual browsers on/off
  [0] Exit

CLI Flags:
  --only=<browser>   Enable ONLY this browser
  --skip=<browser>   Disable this browser (can repeat)

Browsers (ALL enabled by default):
  system         - System default browser (start / Start-Process)
  playwriter     - Playwriter MCP (auth/sessions)
  chrome-mcp     - Chrome MCP (DevTools, inspection)

Examples:
  /launch                        # Interactive menu
  /launch --only=chrome-mcp      # Only Chrome MCP
  /launch --skip=system          # Skip system browser
  /launch --skip=system --skip=playwriter  # Multiple skips
```

---

## Invocation

- `/launch` - Opens interactive menu with all modes
- `/launch --only=<browser>` - Single browser mode
  - Valid: `system`, `playwriter`, `chrome-mcp`
- `/launch --skip=<browser>` - Skip specific browser(s)
- `/launch help` - Show usage information

## Interactive Menu Options

| Key | Mode | Description |
|-----|------|-------------|
| **1** | Dev Debug | Hot reload, DEBUG=true, launches browsers, port 3000 |
| **2** | Dev Standard | Hot reload, standard logging, launches browsers, port 3000 |
| **3** | Production | Runs `pnpm build` then `pnpm start`, optimized, port 3000 |
| **4** | Tunnel | Production build + Cloudflare tunnel to public URL |
| **B** | Browsers | Opens browser toggle submenu |
| **0** | Exit | Graceful shutdown |

## Browser Configuration

All 3 browsers are **enabled by default**:

| Browser | Name | Description |
|---------|------|-------------|
| `system` | System Browser | Opens URL in system default (start / Start-Process) |
| `playwriter` | Playwriter MCP | Chrome extension, maintains auth/sessions |
| `chrome-mcp` | Chrome MCP | Full DevTools access, network inspection |

### Browser Toggle Menu

Press `B` from main menu to toggle browsers:
- Press `1-3` to toggle individual browsers
- Press `A` to enable all
- Press `N` to disable all
- Press `0` to return to main menu

### CLI Browser Selection

```bash
# Only use Chrome MCP
pnpm launch --only=chrome-mcp

# Skip system browser (runs headless only)
pnpm launch --skip=system

# Skip multiple browsers
pnpm launch --skip=system --skip=playwriter
```

## Features

### Animated Header
- Orange gradient flowing animation at 30 FPS
- Displays app name, version, and description
- Crush-style decorative footer

### System Stats
Real-time display of:
- Current time
- CPU usage (color-coded: green/yellow/red)
- RAM usage (percentage + used amount)
- Node.js memory (RSS)

### Process Management
Before starting any server:
1. Kills blocking processes (`next dev`, `next start`, etc.)
2. Releases port 3000
3. Clears `.next` build cache

## Browser Selection (App Debugging)

| Browser | Use For |
|---------|---------|
| **Chrome MCP** | DevTools, network inspection, console logs, DOM debugging |
| **Playwriter** | If the app requires login/authenticated session |
| **System** | Visual verification in your daily driver browser |

### Selection Logic

```
Need DevTools/network/console?  - Chrome MCP
App requires login?             - Playwriter
Manual testing?                 - System browser
```

## Cross-Check Workflow

For critical visual verification, check with multiple browsers:

| Task | Primary | Verification |
|------|---------|--------------|
| UI layout check | Chrome MCP | Playwriter |
| Network debugging | Chrome MCP | Playwriter |
| Visual regression | Chrome MCP | System |

### Discrepancy Report Format

```
## Cross-Check Discrepancy

**Task:** [What was being verified]
**Primary:** [Browser A] - [Result]
**Verification:** [Browser B] - [Result]
**Discrepancy:** [Description of difference]
**Recommendation:** [Human review needed / likely browser-specific / etc.]
```

## Instructions

1. **Run launch tool**
   ```bash
   pnpm launch
   ```

2. **Select mode** from interactive menu (1-4)

3. **Monitor output**
   - Watch console for errors
   - Check browser windows
   - Review network activity

4. **Click around** - Test interactive elements and verify behavior

5. **Check for issues**
   - Console errors
   - Network failures
   - UI glitches
   - Performance issues

## What to Check

### Console
- JavaScript errors
- Warning messages
- Failed network requests

### Network
- API response times
- Failed requests
- Unexpected payloads

### UI
- Layout issues
- Responsive behavior
- Interactive element feedback
- Accessibility issues

### Performance
- Slow renders
- Memory leaks
- Large bundle sizes

## Output Format

```
## Launch Results

### Mode Used
[Dev Debug / Dev Standard / Production / Tunnel]

### Browsers Launched
[List of browsers that were started]

### Console Issues
- [List any console errors/warnings]

### Network Issues
- [List any network problems]

### UI Issues
- [List any visual problems]

### Cross-Check Results
- [If multiple browsers used, note any discrepancies]

### Improvement Proposals
1. [Proposal based on research]
   - Rationale: ...
   - Impact: ...
```

---

## Error Handling

| Error Scenario | Detection | Resolution |
|---------------|-----------|------------|
| **Port 3000 blocked** | `EADDRINUSE` error from server | Kill blocking process: `npx kill-port 3000`, then retry |
| **launch.js script not found** | `ENOENT` error when running `pnpm launch` | Check package.json scripts, verify launch.js exists in project root |
| **Browser unavailable** | MCP server timeout or connection refused | Check browser installation, verify MCP server running in settings.json |
| **Playwriter not connected** | Extension shows "Not connected" | Click Playwriter extension icon on the target tab to enable |
| **Chrome MCP tab creation fails** | Error creating tab in `tabs_create_mcp` | Ensure Chrome is running, extension installed, check MCP logs |
| **System browser doesn't open** | `start` command fails silently | URL not passed correctly - manually open http://localhost:3000 |
| **Server won't start** | Port blocked or build errors | Check `.next` cache corruption - delete and retry: `rm -rf .next` |
| **All browsers fail** | Network/firewall blocking localhost | Check firewall settings, verify localhost not blocked |

**Debugging steps:**
1. Check server logs for specific error messages
2. Verify port 3000 is free: `netstat -ano | findstr :3000` (Windows)
3. Check MCP server status in Claude Code settings
4. Verify browser processes: Task Manager (Windows) or Activity Monitor (macOS)
5. Try manual browser open as fallback: navigate to `http://localhost:3000`

---

## Browser Tool Reference

### Browser 1: System Browser

**Status:** Uses `start` / `Start-Process` to launch system default

**Capabilities:**
- Opens URL in user's preferred browser
- Full browser features available
- Manual interaction for testing

**Usage:**
Automatically opens `http://localhost:3000` when enabled.

---

### Browser 2: Chrome MCP (claude-in-chrome)

**Status:** Configured via MCP plugin

**Capabilities:**
- Direct Chrome DevTools Protocol access
- Network request interception
- Console log capture
- Full DOM traversal and inspection
- Screenshot and GIF recording

**Usage:**

```bash
# 1. Get tab context (required first)
mcp__claude-in-chrome__tabs_context_mcp

# 2. Create or navigate tab
mcp__claude-in-chrome__tabs_create_mcp
mcp__claude-in-chrome__navigate(url: "http://localhost:3000", tabId: <id>)

# 3. Take screenshot for visual verification
mcp__claude-in-chrome__computer(action: "screenshot", tabId: <id>)

# 4. Read page structure (accessibility tree with refs)
mcp__claude-in-chrome__read_page(tabId: <id>, filter: "interactive")

# 5. Find elements by natural language
mcp__claude-in-chrome__find(query: "login button", tabId: <id>)

# 6. Interact with elements
mcp__claude-in-chrome__computer(action: "left_click", ref: "ref_1", tabId: <id>)
mcp__claude-in-chrome__form_input(ref: "ref_2", value: "test@example.com", tabId: <id>)
```

---

### Browser 3: Playwriter MCP

**Status:** Configured via mcpServers (`mcp__playwriter__*`) + Chrome extension

**Installation:**
1. Chrome extension: Install "Playwriter" from Chrome Web Store
2. MCP server: Configured in settings.json mcpServers (runs via `npx playwriter@latest`)

**Capabilities:**
- Chrome extension integration (reuses existing cookies/auth)
- Vimium-style ref labels for element selection via `aria-ref` attributes
- 80% less context via accessibility snapshots
- Maintains authenticated sessions
- JavaScript execution in page context

**Core MCP Tool:**

Playwriter uses a single `execute` tool that runs JavaScript code with special browser context:

```javascript
// mcp__playwriter__execute(code: string, timeout?: number)

// Example: Navigate to URL
await page.goto('http://localhost:3000', { waitUntil: 'domcontentloaded' });

// Example: Get accessibility snapshot with refs
const snapshot = await accessibilitySnapshot({ page });
console.log(snapshot);

// Example: Click using aria-ref
await page.locator('aria-ref=e5').click();

// Example: Fill form inputs
await page.locator('aria-ref=e10').fill('test@example.com');
await page.locator('aria-ref=e11').fill('password123');

// Example: Take screenshot
await page.screenshot({ path: 'result.png', scale: 'css' });
```

**Available globals in execute context:**
- `page` - Current Playwright page instance
- `context` - Browser context (all tabs)
- `state` - Persistent state object (survives across execute calls)
- `accessibilitySnapshot({ page })` - Get aria-ref labeled tree
- `screenshotWithAccessibilityLabels({ page })` - Visual capture with labels
- `waitForPageLoad({ page })` - Smart load detection

**For full tool documentation:** See Playwriter best practices in the main system prompt.

---

## Quick Reference: When to Use Each Browser (App Debugging)

| Scenario | Browser | Reason |
|----------|---------|--------|
| Interactive debugging | Chrome MCP | Full DevTools access |
| Network request debugging | Chrome MCP | Request interception |
| Console error inspection | Chrome MCP | DevTools protocol |
| Recording GIFs of interactions | Chrome MCP | Built-in recording |
| Quick DOM inspection | Chrome MCP | DevTools protocol |
| App requires login/auth | Playwriter | Session persistence |
| Form testing | Playwriter | Field type awareness |
| Accessibility testing | Playwriter | Snapshot-based |
| Manual user testing | System | Full browser features |

**Note:** For web research (not app debugging), use the Web Research Fallback Chain in CLAUDE.md.
