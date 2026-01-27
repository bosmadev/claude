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

Boot up the Node.js server and perform visual verification of the app via localhost or production domain:
- Identify UI elements and interactions
- Inspect network requests (DevTools)
- Catch console errors and warnings
- Verify visual regressions
- Check responsive behavior

## Help Command

When arguments equal "help":

```
/launch - Run debug mode and visual app verification

Usage:
  /launch [options]

Commands:
  (no args)            Start server, visual verification
  --only <browser>     Use single browser
  help                 Show this help

Browsers (for app debugging):
  chrome-mcp       - DevTools, network, console inspection (PRIMARY)
  agent-browser    - Lightweight, fast screenshot capture
  playwriter       - If app requires authenticated session

Examples:
  /launch
  /launch --only chrome-mcp
```

---

## Invocation

- `/launch` → Start server + visual verification
- `/launch --only <browser>` → Single browser mode
  - Valid values: `chrome-mcp`, `agent-browser`, `playwriter`
- `/launch help` → Show usage information

## Browser Selection (App Debugging)

| Browser | Use For |
|---------|---------|
| **Chrome MCP** | DevTools, network inspection, console logs, DOM debugging (PRIMARY) |
| **agent-browser** | Quick screenshots, element snapshots, lightweight checks |
| **Playwriter** | If the app requires login/authenticated session |

### Selection Logic

```
Need DevTools/network/console?  → Chrome MCP (default)
Quick visual check?             → agent-browser
App requires login?             → Playwriter
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

## Auto-Start with RALPH

When RALPH is active, `/launch` automatically:
1. Starts the dev server (`pnpm launch`)
2. Initializes browser tools for visual verification
3. Enables cross-check coordination

For debugging specific browser issues, use `--only` flag to isolate:
```bash
/launch --only chrome-mcp  # Debug Chrome-specific issue
```

## Purpose

Run the application in debug mode and perform visual verification in the browser and also by using Claude MCP in Chrome.

## Instructions

1. **Run debug mode**
   ```bash
   pnpm launch
   ```

2. **Monitor output**
   - Watch console for errors
   - Check Antigravity browser
   - Review network debug log

3. **Click around** - Test interactive elements and verify behavior

4. **Check for issues**
   - Console errors
   - Network failures
   - UI glitches
   - Performance issues

5. **Research improvements**
   - Scout the internet using model tools
   - Based on current context (brain, tasks, implementation plans)
   - Make proposals for improvements

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

### Browser Used
[Which browser tool was selected and why]

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

### Browser 1: Chrome MCP (claude-in-chrome)

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

### Browser 2: agent-browser

**Status:** Installed at `/usr/share/claude/agent-browser-npm/`

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

### Browser 3: Browser-Use

**Status:** Python library integration

**Capabilities:**
- LLM decision loop for autonomous navigation
- Natural language task descriptions
- 15+ built-in action tools
- Self-correcting workflows
- Vision capabilities for complex pages

**Installation:**

```bash
pip install browser-use
playwright install chromium
```

**Usage (Python):**

```python
from browser_use import Agent
import asyncio

async def main():
    agent = Agent(
        task="Navigate to the login page and fill in test credentials"
    )
    result = await agent.run()
    print(result)

asyncio.run(main())
```

**Available Actions:**
- `navigate(url)` - Go to URL
- `click(element)` - Click element
- `type(element, text)` - Type text
- `scroll(direction)` - Scroll page
- `screenshot()` - Capture screenshot
- `extract_text(element)` - Get text content
- `wait_for(condition)` - Wait for condition
- `go_back()` / `go_forward()` - Navigation
- `new_tab()` / `switch_tab(index)` / `close_tab()` - Tab management
- `select_option(element, value)` - Dropdown selection
- `hover(element)` - Mouse hover
- `drag_and_drop(source, target)` - Drag operations

**Configuration:**

```python
from browser_use import Agent, BrowserConfig

config = BrowserConfig(
    headless=True,
    slow_mo=100,  # Slow down for debugging
    viewport={"width": 1280, "height": 720}
)

agent = Agent(
    task="Your task description",
    browser_config=config,
    max_steps=50,  # Limit autonomous actions
)
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

**Note:** For web scraping/research (not app debugging), see `/scraper` skill or use the Web Research Fallback Chain in CLAUDE.md.
