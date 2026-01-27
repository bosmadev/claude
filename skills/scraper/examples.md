# Example Sessions

## Basic Scrape

```
User: /scrape https://example.com

Claude: Scraping https://example.com...

Browser: patchright (auto-selected)
Mode: stealth

Scrape Complete

URL: https://example.com
Browser: patchright
Mode: stealth
Time: 2.3s

Content Summary:
- Title: Example Domain
- Words: 83
- Links: 1
- Images: 0

Output: ~/.claude/scraper/exports/example_com_20260123.json
```

## AI Extraction

```
User: /scrape https://shop.example.com/products --ai "extract product names and prices"

Claude: Scraping with AI extraction...

Browser: patchright (auto-selected)
AI Provider: openai (gpt-4o)

Scrape Complete

Extracted Data:
[
  {"name": "Widget Pro", "price": "$29.99"},
  {"name": "Gadget Plus", "price": "$49.99"},
  {"name": "Gizmo Max", "price": "$79.99"}
]

Output: ~/.claude/scraper/exports/shop_products_20260123.json
```

## Tor + Multi-Page

```
User: /scrape https://example.onion/listings --tor --pages 1-5

Claude: Scraping via Tor (5 pages)...

Browser: patchright
Mode: tor (circuit isolated)
Pages: 1-5

Progress:
Page 1/5... done (2.1s)
Page 2/5... done (2.4s)
Page 3/5... done (1.9s)
Page 4/5... done (2.2s)
Page 5/5... done (2.0s)

Scrape Complete

Total Items: 125
Total Time: 10.6s

Output: ~/.claude/scraper/exports/example_onion_listings_20260123.json
```

## Stealth with Export

```
User: /scrape https://protected.site --stealth --export csv

Claude: Scraping with stealth mode...

Browser: patchright
Mode: stealth (explicit)
Export: CSV

Scrape Complete

URL: https://protected.site
Time: 3.1s

Content exported to: ~/.claude/scraper/exports/protected_site_20260123.csv
Rows: 42
Columns: 5
```

## CAPTCHA Mode

```
User: /scrape https://captcha-site.com --captcha

Claude: CAPTCHA Mode Activated

The browser will open to: https://captcha-site.com

Steps:
1. Browser window will open
2. Solve the CAPTCHA manually
3. Press Enter in terminal when done
4. Scraping will continue automatically

Opening browser...
[Browser opens]

User: [Solves CAPTCHA, presses Enter]

Claude: Continuing scrape...

Scrape Complete

URL: https://captcha-site.com
Time: 45.2s (including CAPTCHA solve)

Output: ~/.claude/scraper/exports/captcha_site_20260123.json
```

## Cross-Browser Verification

```
User: /scrape https://dynamic-site.com --verify

Claude: Scraping with cross-browser verification...

Testing with: patchright, playwriter, browser-use

Results:
- patchright: 1,234 words
- playwriter: 1,234 words
- browser-use: 1,234 words

VERIFIED: Content consistent across browsers

Output: ~/.claude/scraper/exports/dynamic_site_20260123.json
```
