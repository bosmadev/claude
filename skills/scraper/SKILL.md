---
name: scraper
description: Web scraping with CyberScraper integration. Features anti-detection, AI extraction, Tor routing, browser pool selection, and multi-page support.
argument-hint: <url> [--stealth|--tor|--browser <name>|--ai "prompt"|--captcha|--pages N|--cache|--verify|--export json|csv|xlsx]
user-invocable: true
context: main
---

# /scraper Skill

**When invoked, immediately output: `SKILL_STARTED: scraper`**

Enterprise-grade web scraping with CyberScraper Deep integration, intelligent browser pool routing, and AI-powered extraction.

## Usage

```
/scrape help                           Show this help
/scrape <url>                          Auto-select browser, stealth default
/scrape <url> --stealth                Explicit stealth mode (Patchright)
/scrape <url> --tor                    Via Tor network with circuit isolation
/scrape <url> --pages 1-10             Multi-page scraping (pagination)
/scrape <url> --cache                  Use cached version if available
/scrape <url> --browser <name>         Force specific browser
/scrape <url> --verify                 Cross-browser verification
/scrape <url> --export json|csv|xlsx   Export format (default: json)
/scrape <url> --ai "extract prices"    AI-powered content extraction
/scrape <url> --captcha                Pause for manual CAPTCHA solving
```

## Arguments

**$ARGUMENTS**: "$ARGUMENTS"

Parse: URL, Flags (`--stealth`, `--tor`, `--cache`, `--verify`, `--captcha`), Options (`--browser`, `--pages`, `--export`, `--ai`).

---

## Browser Pool Architecture

| Browser | Use Case | Anti-Detection | Capabilities |
|---------|----------|----------------|--------------|
| **Patchright** | Default stealth | Webdriver patching | Best for protected sites |
| **Playwriter** | Auth-required | Session persistence, 80% less context | Login flows |
| **Browser-Use** | Cloudflare/Captcha | Autonomous solving | Anti-bot bypass |
| **Chrome MCP** | DevTools needed | Full Chrome DevTools Protocol | Debugging |
| **agent-browser** | Simple pages | Lightweight, fast | Static content |

### Auto-Selection Logic

1. Cloudflare detected? -> Browser-Use
2. Requires authentication? -> Playwriter
3. DevTools/network needed? -> Chrome MCP
4. Protected site? -> Patchright
5. Simple page? -> agent-browser
6. Override with `--browser` flag
7. Fall back to Patchright if uncertain

### Detection Heuristics

```bash
# Cloudflare check
curl -sI "$URL" | grep -i "cloudflare\|cf-ray\|__cf_bm"

# Login check
curl -s "$URL" | grep -iE "login|sign.?in|password|authenticate"
```

---

## CyberScraper Integration

See [cyberscraper.md](cyberscraper.md) for detailed implementation including:
- Anti-detection (Patchright) techniques
- AI-powered extraction (OpenAI, Gemini, Ollama)
- Advanced Tor routing with circuit isolation
- Session management and caching
- Multi-page pagination detection
- Cross-browser verification
- Export formats (JSON, CSV, XLSX)

---

## Command Implementation

### Action: Help

When `$ARGUMENTS` is empty or "help", display usage guide.

### Action: Scrape URL

**Execution Flow:**

1. **Parse Arguments** - Extract URL, flags, and options from `$ARGUMENTS`
2. **Check Cache** - If `--cache`, check `~/.claude/scraper/cache/{URL_HASH}.json` (24h TTL)
3. **Select Browser** - Auto-detect or use `--browser` override
4. **Execute Scrape** - Run with selected browser and mode
5. **AI Extraction** - If `--ai`, process content with AI provider
6. **Multi-Page** - If `--pages`, iterate with rate limiting
7. **Verify** - If `--verify`, compare across browsers
8. **CAPTCHA** - If `--captcha`, open browser for manual solving
9. **Export** - Save to requested format (json/csv/xlsx)
10. **Display Results** - Show summary with content stats

**Browser Commands:**

```bash
# Patchright (Stealth)
cyberscraper scrape "$URL" --browser patchright --stealth --output "/tmp/scrape.json"

# Playwriter (Auth)
playwriter execute "$URL" --storage-state "$SESSION_FILE" --output "/tmp/scrape.json"

# Browser-Use (Cloudflare)
browser-use scrape "$URL" --autonomous --solve-captcha --output "/tmp/scrape.json"

# Tor Mode
cyberscraper scrape "$URL" --proxy "socks5://127.0.0.1:9050" --new-circuit --output "/tmp/scrape.json"
```

---

## File Locations

| Path | Purpose |
|------|---------|
| `~/.claude/scraper/cache/` | Cached scrape results |
| `~/.claude/scraper/sessions/` | Browser session states |
| `~/.claude/scraper/exports/` | Export output files |
| `~/.claude/scraper/config.json` | Scraper configuration |

## Configuration

`~/.claude/scraper/config.json`:

```json
{
  "default_browser": "patchright",
  "default_export": "json",
  "cache_ttl_hours": 24,
  "rate_limit_seconds": 2,
  "ai_provider": "openai",
  "tor_enabled": true,
  "stealth_by_default": true
}
```

---

## Safety and Ethics

- **Respect robots.txt** - Check before scraping
- **Rate Limiting** - Minimum 1s between requests, exponential backoff
- **Do NOT scrape** - Personal data without consent, content behind auth you don't own, sites prohibiting scraping

---

## Error Handling

| Error | Recovery |
|-------|----------|
| Cloudflare block | Switch to browser-use |
| CAPTCHA detected | Offer --captcha mode |
| Rate limited | Exponential backoff |
| Tor circuit failed | New identity, retry |
| Session expired | Clear session, re-auth |
| Content empty | Try different browser |
| Network timeout | Increase timeout, retry |

---

## Example Sessions

See [examples.md](examples.md) for complete example sessions including:
- Basic scrape
- AI extraction
- Tor + Multi-page
- Stealth with export
- CAPTCHA mode
- Cross-browser verification
