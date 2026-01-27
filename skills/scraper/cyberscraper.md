# CyberScraper Deep Integration

## 1. Anti-Detection (Patchright)

Patchright patches Chromium to evade detection:

```python
# Webdriver property patching
Object.defineProperty(navigator, 'webdriver', { get: () => undefined })

# Automation flags removal
window.chrome.runtime = undefined

# CDP detection bypass
delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array

# Headless detection bypass
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] })
```

**Usage Pattern:**
```bash
# Launch with Patchright stealth
cyberscraper --url "$URL" --stealth --patchright
```

## 2. AI-Powered Extraction

Supports multiple AI providers for intelligent content extraction:

| Provider | Model | Best For |
|----------|-------|----------|
| OpenAI | gpt-4o | Complex extraction, reasoning |
| Gemini | gemini-pro | Multi-modal, images |
| Ollama | llama3 | Local/private, no API |

**Configuration:**
```bash
# Set provider (environment variable)
export SCRAPER_AI_PROVIDER="openai"  # or gemini, ollama

# AI extraction prompt
/scrape https://example.com --ai "Extract all product names and prices"
```

**Extraction Flow:**
1. Fetch page content
2. Clean HTML (remove scripts, styles)
3. Send to AI with extraction prompt
4. Parse structured response
5. Format to requested export type

## 3. Advanced Tor Routing

**Features:**
- Circuit isolation per domain
- Automatic .onion routing
- Identity rotation on failure
- Exit node selection

**Usage:**
```bash
/scrape https://example.com --tor

# For .onion sites (automatic Tor)
/scrape http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion
```

**Implementation:**
```python
# Tor SOCKS5 proxy
proxy = {
    "server": "socks5://127.0.0.1:9050",
    "bypass": "localhost,127.0.0.1"
}

# Circuit isolation (new identity per domain)
controller.signal(Signal.NEWNYM)
```

## 4. Session Management

**Persistent Context:**
```python
# Store session in ~/.claude/scraper/sessions/
context = browser.new_context(
    storage_state="~/.claude/scraper/sessions/{domain}.json"
)
```

**LRU Caching:**
```python
# Cache scraped content (24h default)
cache_dir = "~/.claude/scraper/cache/"
cache_key = hashlib.md5(url.encode()).hexdigest()
```

## 5. Multi-Page Scraping

**Pagination Pattern Detection:**
```python
def detect_pagination(url, page_num):
    patterns = [
        (r'\?page=\d+', f'?page={page_num}'),
        (r'/page/\d+', f'/page/{page_num}'),
        (r'&p=\d+', f'&p={page_num}'),
        (r'/p\d+', f'/p{page_num}'),
    ]
    for pattern, replacement in patterns:
        if re.search(pattern, url):
            return re.sub(pattern, replacement, url)
    # Default: append ?page=N
    separator = '&' if '?' in url else '?'
    return f"{url}{separator}page={page_num}"
```

## 6. Cross-Browser Verification

```python
browsers = ["patchright", "playwriter", "browser-use"]
results = {}

for browser in browsers:
    result = scrape_with_browser(url, browser)
    results[browser] = result

# Compare results
differences = compare_results(results)
if differences:
    print("WARNING: Content differs across browsers")
else:
    print("VERIFIED: Content consistent across browsers")

# Return most complete result
return max(results.values(), key=lambda x: len(x.get("content", "")))
```

## 7. Export Formats

**JSON (default):**
```python
with open(output_path, 'w') as f:
    json.dump(result, f, indent=2)
```

**CSV:**
```python
import csv
with open(output_path, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=result[0].keys())
    writer.writeheader()
    writer.writerows(result)
```

**XLSX:**
```python
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.append(list(result[0].keys()))  # Headers
for row in result:
    ws.append(list(row.values()))
wb.save(output_path)
```
