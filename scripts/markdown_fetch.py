#!/usr/bin/env python3
"""
Unified web-to-markdown fetch utility.

Tries markdown.new (Cloudflare) first, then r.jina.ai as fallback.
Returns JSON with markdown content, source, and token estimate.

Usage:
    python markdown_fetch.py <url> [--method auto|browser|ai]

Exit codes:
    0 = success (markdown or failed — check "source" field)
    1 = invalid arguments
"""

import json
import sys
import urllib.request
import urllib.error
import urllib.parse
import os
from typing import Optional

TIMEOUT = 15  # seconds per service
USER_AGENT = "Mozilla/5.0 (compatible; ClaudeCode/1.0)"


def fetch_markdown_new(url: str, method: str = "auto") -> Optional[str]:
    """Fetch markdown via markdown.new POST API.

    Args:
        url: Target URL to convert.
        method: Rendering mode — "auto" (default), "browser", or "ai".

    Returns:
        Markdown string on success, None on failure.
    """
    api_url = "https://md.dhr.wtf/api/md"
    payload = json.dumps({"url": url, "options": {"method": method}}).encode("utf-8")

    req = urllib.request.Request(
        api_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status == 200:
                text = resp.read().decode("utf-8", errors="replace")
                if text and len(text.strip()) > 50:
                    return text
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        pass
    return None


def fetch_jina(url: str) -> Optional[str]:
    """Fetch markdown via r.jina.ai GET API.

    Returns:
        Markdown string on success, None on failure.
    """
    api_url = f"https://r.jina.ai/{url}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/markdown",
    }

    # Optional API key for higher rate limits (20 RPM free, 500 RPM with key)
    jina_key = os.environ.get("JINA_API_KEY")
    if jina_key:
        headers["Authorization"] = f"Bearer {jina_key}"

    req = urllib.request.Request(api_url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            if resp.status == 200:
                text = resp.read().decode("utf-8", errors="replace")
                if text and len(text.strip()) > 50:
                    return text
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError):
        pass
    return None


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token)."""
    return len(text) // 4


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python markdown_fetch.py <url> [--method auto|browser|ai]", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    method = "auto"

    for arg in sys.argv[2:]:
        if arg.startswith("--method"):
            if "=" in arg:
                method = arg.split("=", 1)[1]
            elif sys.argv.index(arg) + 1 < len(sys.argv):
                method = sys.argv[sys.argv.index(arg) + 1]

    # Tier 1: markdown.new
    md = fetch_markdown_new(url, method)
    if md:
        result = {"markdown": md, "source": "markdown.new", "tokens": estimate_tokens(md)}
        print(json.dumps(result))
        return

    # Tier 2: jina.ai
    md = fetch_jina(url)
    if md:
        result = {"markdown": md, "source": "jina", "tokens": estimate_tokens(md)}
        print(json.dumps(result))
        return

    # Both failed — LLM decides whether to escalate to browser tools
    result = {"markdown": "", "source": "failed", "tokens": 0}
    print(json.dumps(result))


if __name__ == "__main__":
    main()
