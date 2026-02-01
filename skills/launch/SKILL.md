---
name: launch
description: Run debug mode and browser testing for visual verification. Use when you need to visually verify UI changes, check for visual regressions, or test interactive elements. Manual invocation only - use /launch to run.
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
- ALL 4 browsers enabled by default
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
  agent-browser  - Agent Browser (headless, fast)
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
  - Valid: `system`, `playwriter`, `agent-browser`, `chrome-mcp`
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

All 4 browsers are **enabled by default**:

| Browser | Name | Description |
|---------|------|-------------|
| `system` | System Browser | Opens URL in system default (start / Start-Process) |
| `playwriter` | Playwriter MCP | Chrome extension, maintains auth/sessions |
| `agent-browser` | Agent Browser | Lightweight headless, fast screenshots |
| `chrome-mcp` | Chrome MCP | Full DevTools access, network inspection |

### Browser Toggle Menu

Press `B` from main menu to toggle browsers:
- Press `1-4` to toggle individual browsers
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
| **agent-browser** | Quick screenshots, element snapshots, lightweight checks |
| **Playwriter** | If the app requires login/authenticated session |
| **System** | Visual verification in your daily driver browser |

### Selection Logic

```
Need DevTools/network/console?  - Chrome MCP
Quick visual check?             - agent-browser
App requires login?             - Playwriter
Manual testing?                 - System browser
```

## Cross-Check Workflow

For critical visual verification, check with multiple browsers:

| Task | Primary | Verification |
|------|---------|--------------|
| UI layout check | Chrome MCP | agent-browser |
| Network debugging | Chrome MCP | Playwriter |
| Visual regression | agent-browser | Chrome MCP |

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

### Browser 3: agent-browser

**Status:** Installed at `~/.claude\agent-browser-npm\`

> **Note:** agent-browser requires separate installation via npm. If not installed, use other browser options.

**Capabilities:**
- Lightweight headless Chromium (Playwright-based)
- Fast screenshot capture
- Ref-based element selection (AI-friendly)
- Low resource usage
- Session isolation support
- CDP mode for connecting to existing browsers

**Core Workflow:**

```bash
# 1. Navigate to URL
~/.claude/bin/agent-browser open http://localhost:3000

# 2. Get accessibility tree with refs (@e1, @e2, etc.)
~/.claude/bin/agent-browser snapshot -i      # Interactive elements only
~/.claude/bin/agent-browser snapshot -c      # Compact mode
~/.claude/bin/agent-browser snapshot --json  # Machine-readable

# 3. Interact using refs
~/.claude/bin/agent-browser click @e1
~/.claude/bin/agent-browser fill @e2 "test@example.com"
~/.claude/bin/agent-browser type @e3 "search query"

# 4. Capture screenshot
~/.claude/bin/agent-browser screenshot ./verification.png
~/.claude/bin/agent-browser screenshot --full ./fullpage.png

# 5. Get element info
~/.claude/bin/agent-browser get text @e1
~/.claude/bin/agent-browser get value @e2
~/.claude/bin/agent-browser is visible @e3

# 6. Close browser
~/.claude/bin/agent-browser close
```

**Advanced Features:**

```bash
# Sessions (isolated browser instances)
~/.claude/bin/agent-browser --session agent1 open site-a.com
~/.claude/bin/agent-browser --session agent2 open site-b.com

# CDP mode (connect to existing browser)
~/.claude/bin/agent-browser connect 9222
~/.claude/bin/agent-browser --cdp 9222 snapshot

# Headed mode (visible browser for debugging)
~/.claude/bin/agent-browser open example.com --headed

# Authentication headers
~/.claude/bin/agent-browser open api.example.com --headers '{"Authorization": "Bearer <token>"}'

# Wait commands
~/.claude/bin/agent-browser wait "#element"        # Wait for element
~/.claude/bin/agent-browser wait 2000              # Wait 2 seconds
~/.claude/bin/agent-browser wait --text "Welcome"  # Wait for text
```

---

### Browser 4: Playwriter MCP

**Status:** Configured via mcpServers (`mcp__playwriter__*`) + Chrome extension

**Installation:**
1. Chrome extension: Install "Playwriter" from Chrome Web Store
2. MCP server: Configured in settings.json mcpServers (runs via `npx playwriter@latest`)

**Capabilities:**
- Chrome extension integration (reuses existing cookies/auth)
- Vimium-style ref labels for element selection
- 80% less context via accessibility snapshots
- Maintains authenticated sessions
- Form filling with field type awareness

**MCP Tools:**

```
# Navigation
mcp__playwriter__browser_navigate(url)
mcp__playwriter__browser_navigate_back()

# Interaction
mcp__playwriter__browser_click(element, ref)
mcp__playwriter__browser_type(element, ref, text)
mcp__playwriter__browser_fill_form(fields)
mcp__playwriter__browser_select_option(element, ref, values)
mcp__playwriter__browser_hover(element, ref)
mcp__playwriter__browser_drag(startElement, startRef, endElement, endRef)
mcp__playwriter__browser_press_key(key)

# Page State
mcp__playwriter__browser_snapshot()           # Accessibility tree with refs
mcp__playwriter__browser_take_screenshot()    # Visual capture
mcp__playwriter__browser_console_messages()   # Console logs
mcp__playwriter__browser_network_requests()   # Network activity

# Tabs
mcp__playwriter__browser_tabs(action: "list|new|close|select")

# Utilities
mcp__playwriter__browser_wait_for(text|textGone|time)
mcp__playwriter__browser_evaluate(function)
mcp__playwriter__browser_file_upload(paths)
mcp__playwriter__browser_handle_dialog(accept)
mcp__playwriter__browser_resize(width, height)
mcp__playwriter__browser_close()
mcp__playwriter__browser_install()            # Install browser if needed
```

**Example Workflow:**

```
# 1. Navigate to page
mcp__playwriter__browser_navigate(url: "http://localhost:3000")

# 2. Get accessibility snapshot with refs
mcp__playwriter__browser_snapshot()

# 3. Click using ref from snapshot
mcp__playwriter__browser_click(element: "Login button", ref: "e1")

# 4. Fill form fields
mcp__playwriter__browser_fill_form(fields: [
  {"name": "Email", "type": "textbox", "ref": "e2", "value": "test@example.com"},
  {"name": "Password", "type": "textbox", "ref": "e3", "value": "secret123"}
])

# 5. Take screenshot
mcp__playwriter__browser_take_screenshot(filename: "result.png")
```

---

## Quick Reference: When to Use Each Browser (App Debugging)

| Scenario | Browser | Reason |
|----------|---------|--------|
| Interactive debugging | Chrome MCP | Full DevTools access |
| Network request debugging | Chrome MCP | Request interception |
| Console error inspection | Chrome MCP | DevTools protocol |
| Recording GIFs of interactions | Chrome MCP | Built-in recording |
| Quick DOM inspection | Chrome MCP | DevTools protocol |
| Quick visual check | agent-browser | Lightweight, fast |
| Headless screenshot capture | agent-browser | Session isolation |
| CI/CD automated testing | agent-browser | Low resource usage |
| App requires login/auth | Playwriter | Session persistence |
| Form testing | Playwriter | Field type awareness |
| Accessibility testing | Playwriter | Snapshot-based |
| Manual user testing | System | Full browser features |

**Note:** For web scraping/research (not app debugging), see `/scraper` skill or use the Web Research Fallback Chain in CLAUDE.md.
