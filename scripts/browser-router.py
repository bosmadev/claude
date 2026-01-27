#!/usr/bin/env python3
"""
Browser Router - Unified multi-browser selection for web automation.

This module provides intelligent browser selection based on URL requirements
like authentication, captcha handling, stealth mode, and CDP access.

Browser Capability Matrix:
| Browser        | Auth | Stealth | Captcha | CDP | Best For              |
|----------------|------|---------|---------|-----|-----------------------|
| WebFetch       | No   | No      | No      | No  | Simple public pages   |
| agent-browser  | No   | Yes     | No      | Yes | Headless automation   |
| Playwriter MCP | Yes  | Yes     | No      | Yes | Auth flows, sessions  |
| Browser-Use    | Yes  | Yes     | Yes     | Yes | Cloudflare bypass     |
| CyberScraper   | Yes  | Yes++   | Yes     | Yes | Bot detection evasion |
| Chrome MCP     | Yes  | No      | No      | Yes | Debugging, inspection |

Usage:
    from browser_router import select_browser, BrowserCapabilities

    # Simple usage
    browser = select_browser("https://example.com", {"stealth": True})

    # With full requirements
    browser = select_browser(
        "https://protected-site.com",
        {"auth": True, "captcha": True, "stealth": True}
    )

    # CLI usage
    python3 browser-router.py select https://example.com --auth --stealth
    python3 browser-router.py test  # Run self-tests
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse


# =============================================================================
# Browser Definitions
# =============================================================================

class Browser(str, Enum):
    """Available browser tools for web automation."""
    WEBFETCH = "webfetch"
    AGENT_BROWSER = "agent-browser"
    PLAYWRITER = "playwriter"
    BROWSER_USE = "browser-use"
    CYBERSCRAPER = "cyberscraper"
    CHROME_MCP = "chrome-mcp"


@dataclass
class BrowserCapabilities:
    """Capabilities of a browser tool."""
    name: Browser
    auth: bool = False
    stealth: bool = False
    captcha: bool = False
    cdp: bool = False
    priority: int = 0  # Higher = preferred when capabilities match
    description: str = ""


# Browser capability definitions
BROWSER_CAPABILITIES: dict[Browser, BrowserCapabilities] = {
    Browser.WEBFETCH: BrowserCapabilities(
        name=Browser.WEBFETCH,
        auth=False,
        stealth=False,
        captcha=False,
        cdp=False,
        priority=10,
        description="Fast, simple public page fetching"
    ),
    Browser.AGENT_BROWSER: BrowserCapabilities(
        name=Browser.AGENT_BROWSER,
        auth=False,
        stealth=True,
        captcha=False,
        cdp=True,
        priority=20,
        description="Headless automation with stealth"
    ),
    Browser.PLAYWRITER: BrowserCapabilities(
        name=Browser.PLAYWRITER,
        auth=True,
        stealth=True,
        captcha=False,
        cdp=True,
        priority=30,
        description="Auth flows and session management"
    ),
    Browser.BROWSER_USE: BrowserCapabilities(
        name=Browser.BROWSER_USE,
        auth=True,
        stealth=True,
        captcha=True,
        cdp=True,
        priority=40,
        description="Cloudflare and captcha bypass"
    ),
    Browser.CYBERSCRAPER: BrowserCapabilities(
        name=Browser.CYBERSCRAPER,
        auth=True,
        stealth=True,  # Enhanced stealth
        captcha=True,
        cdp=True,
        priority=50,
        description="Advanced bot detection evasion"
    ),
    Browser.CHROME_MCP: BrowserCapabilities(
        name=Browser.CHROME_MCP,
        auth=True,
        stealth=False,
        captcha=False,
        cdp=True,
        priority=5,  # Low priority - debugging tool
        description="Debugging and inspection"
    ),
}


# =============================================================================
# Requirements Dataclass
# =============================================================================

@dataclass
class BrowserRequirements:
    """Requirements for browser selection."""
    auth: bool = False
    stealth: bool = False
    captcha: bool = False
    cdp: bool = False
    debug: bool = False
    prefer: Optional[Browser] = None  # Explicitly prefer a browser

    @classmethod
    def from_dict(cls, data: dict) -> "BrowserRequirements":
        """Create requirements from dictionary."""
        return cls(
            auth=data.get("auth", False),
            stealth=data.get("stealth", False),
            captcha=data.get("captcha", False),
            cdp=data.get("cdp", False),
            debug=data.get("debug", False),
            prefer=Browser(data["prefer"]) if data.get("prefer") else None
        )


# =============================================================================
# URL Analysis
# =============================================================================

def analyze_url(url: str) -> dict:
    """
    Analyze a URL to detect likely requirements.

    Args:
        url: The URL to analyze.

    Returns:
        dict with detected hints about requirements.
    """
    parsed = urlparse(url)
    hints = {
        "likely_auth": False,
        "likely_captcha": False,
        "likely_stealth": False
    }

    # Known auth-required domains
    auth_domains = [
        "github.com", "gitlab.com", "bitbucket.org",
        "console.cloud.google.com", "portal.azure.com",
        "console.aws.amazon.com", "app.netlify.com",
        "vercel.com", "dashboard.stripe.com"
    ]

    # Known Cloudflare/captcha-protected domains
    protected_domains = [
        "cloudflare.com", "discord.com", "reddit.com",
        "twitter.com", "x.com", "instagram.com"
    ]

    domain = parsed.netloc.lower()

    for auth_domain in auth_domains:
        if domain.endswith(auth_domain):
            hints["likely_auth"] = True
            break

    for protected in protected_domains:
        if domain.endswith(protected):
            hints["likely_captcha"] = True
            hints["likely_stealth"] = True
            break

    return hints


# =============================================================================
# Browser Selection Logic
# =============================================================================

def select_browser(url: str, requirements: dict | BrowserRequirements | None = None) -> Browser:
    """
    Select optimal browser based on URL and requirements.

    Decision tree:
    1. If debug mode -> Chrome MCP
    2. If explicit preference -> use that browser
    3. If captcha required:
       - If stealth also needed -> CyberScraper
       - Otherwise -> Browser-Use
    4. If auth required -> Playwriter
    5. If stealth required -> agent-browser
    6. Default -> WebFetch

    Args:
        url: The target URL.
        requirements: dict or BrowserRequirements with needed capabilities.

    Returns:
        The selected Browser enum value.
    """
    # Normalize requirements
    if requirements is None:
        reqs = BrowserRequirements()
    elif isinstance(requirements, dict):
        reqs = BrowserRequirements.from_dict(requirements)
    else:
        reqs = requirements

    # 1. Debug mode always goes to Chrome MCP
    if reqs.debug:
        return Browser.CHROME_MCP

    # 2. Explicit preference
    if reqs.prefer:
        return reqs.prefer

    # 3. Captcha handling
    if reqs.captcha:
        if reqs.stealth:
            return Browser.CYBERSCRAPER
        return Browser.BROWSER_USE

    # 4. Auth required
    if reqs.auth:
        return Browser.PLAYWRITER

    # 5. Stealth mode
    if reqs.stealth:
        return Browser.AGENT_BROWSER

    # 6. Default - simple pages
    return Browser.WEBFETCH


def select_browser_with_fallback(
    url: str,
    requirements: dict | BrowserRequirements | None = None
) -> list[Browser]:
    """
    Get ordered fallback chain for browser selection.

    Returns browsers in order of preference, allowing graceful
    degradation if the primary choice fails.

    Args:
        url: The target URL.
        requirements: Required capabilities.

    Returns:
        List of browsers in fallback order.
    """
    primary = select_browser(url, requirements)

    # Build fallback chain based on primary selection
    fallback_chains = {
        Browser.WEBFETCH: [Browser.WEBFETCH, Browser.AGENT_BROWSER, Browser.PLAYWRITER],
        Browser.AGENT_BROWSER: [Browser.AGENT_BROWSER, Browser.PLAYWRITER, Browser.BROWSER_USE],
        Browser.PLAYWRITER: [Browser.PLAYWRITER, Browser.BROWSER_USE, Browser.CYBERSCRAPER],
        Browser.BROWSER_USE: [Browser.BROWSER_USE, Browser.CYBERSCRAPER, Browser.CHROME_MCP],
        Browser.CYBERSCRAPER: [Browser.CYBERSCRAPER, Browser.BROWSER_USE, Browser.CHROME_MCP],
        Browser.CHROME_MCP: [Browser.CHROME_MCP, Browser.PLAYWRITER, Browser.AGENT_BROWSER],
    }

    return fallback_chains.get(primary, [primary])


# =============================================================================
# Browser Pairing for Verification
# =============================================================================

def get_verification_pair(primary: Browser) -> Browser:
    """
    Get secondary browser for dual verification.

    Pairing matrix:
    | Primary       | Secondary     | Use Case                         |
    |---------------|---------------|----------------------------------|
    | WebFetch      | agent-browser | Public pages, JS rendering check |
    | agent-browser | Playwriter    | Headless vs headed comparison    |
    | Playwriter    | Browser-Use   | Auth flow verification           |
    | Browser-Use   | CyberScraper  | Bot detection consistency        |
    | CyberScraper  | Browser-Use   | Cross-check stealth engines      |
    | Chrome MCP    | Playwriter    | Debug with full-featured backup  |

    Args:
        primary: The primary browser being used.

    Returns:
        Recommended secondary browser for verification.
    """
    pairs = {
        Browser.WEBFETCH: Browser.AGENT_BROWSER,
        Browser.AGENT_BROWSER: Browser.PLAYWRITER,
        Browser.PLAYWRITER: Browser.BROWSER_USE,
        Browser.BROWSER_USE: Browser.CYBERSCRAPER,
        Browser.CYBERSCRAPER: Browser.BROWSER_USE,
        Browser.CHROME_MCP: Browser.PLAYWRITER,
    }
    return pairs.get(primary, Browser.CHROME_MCP)


# =============================================================================
# Session Management Helpers
# =============================================================================

@dataclass
class SessionInfo:
    """Browser session information for persistence."""
    agent_id: str
    browser: Browser
    session_id: str
    cookies: list = field(default_factory=list)
    last_used: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "agent_id": self.agent_id,
            "browser": self.browser.value,
            "session_id": self.session_id,
            "cookies": self.cookies,
            "last_used": self.last_used
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionInfo":
        """Create from dict."""
        return cls(
            agent_id=data["agent_id"],
            browser=Browser(data["browser"]),
            session_id=data["session_id"],
            cookies=data.get("cookies", []),
            last_used=data.get("last_used")
        )


# =============================================================================
# CLI Interface
# =============================================================================

def run_tests() -> bool:
    """Run self-tests for browser router."""
    tests_passed = 0
    tests_failed = 0

    test_cases = [
        # (url, requirements, expected)
        ("https://example.com", {}, Browser.WEBFETCH),
        ("https://example.com", {"stealth": True}, Browser.AGENT_BROWSER),
        ("https://example.com", {"auth": True}, Browser.PLAYWRITER),
        ("https://example.com", {"captcha": True}, Browser.BROWSER_USE),
        ("https://example.com", {"captcha": True, "stealth": True}, Browser.CYBERSCRAPER),
        ("https://example.com", {"debug": True}, Browser.CHROME_MCP),
        ("https://example.com", {"prefer": "playwriter"}, Browser.PLAYWRITER),
    ]

    print("Running browser router tests...\n")

    for url, reqs, expected in test_cases:
        result = select_browser(url, reqs)
        if result == expected:
            tests_passed += 1
            print(f"  PASS: {reqs} -> {result.value}")
        else:
            tests_failed += 1
            print(f"  FAIL: {reqs} -> {result.value} (expected {expected.value})")

    print(f"\nResults: {tests_passed} passed, {tests_failed} failed")
    return tests_failed == 0


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Browser Router - Intelligent browser selection for web automation"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Select command
    select_parser = subparsers.add_parser("select", help="Select browser for URL")
    select_parser.add_argument("url", help="Target URL")
    select_parser.add_argument("--auth", action="store_true", help="Requires authentication")
    select_parser.add_argument("--stealth", action="store_true", help="Requires stealth mode")
    select_parser.add_argument("--captcha", action="store_true", help="May have captcha")
    select_parser.add_argument("--cdp", action="store_true", help="Needs CDP access")
    select_parser.add_argument("--debug", action="store_true", help="Debug mode")
    select_parser.add_argument("--prefer", choices=[b.value for b in Browser], help="Preferred browser")
    select_parser.add_argument("--fallback", action="store_true", help="Show fallback chain")
    select_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze URL for requirements")
    analyze_parser.add_argument("url", help="URL to analyze")

    # Verify-pair command
    verify_parser = subparsers.add_parser("verify-pair", help="Get verification browser pair")
    verify_parser.add_argument("browser", choices=[b.value for b in Browser], help="Primary browser")

    # Test command
    subparsers.add_parser("test", help="Run self-tests")

    # List command
    subparsers.add_parser("list", help="List all browsers and capabilities")

    args = parser.parse_args()

    if args.command == "select":
        requirements = {
            "auth": args.auth,
            "stealth": args.stealth,
            "captcha": args.captcha,
            "cdp": args.cdp,
            "debug": args.debug,
            "prefer": args.prefer
        }

        if args.fallback:
            browsers = select_browser_with_fallback(args.url, requirements)
            if args.json:
                print(json.dumps({"fallback_chain": [b.value for b in browsers]}))
            else:
                print("Fallback chain:")
                for i, b in enumerate(browsers, 1):
                    print(f"  {i}. {b.value}")
        else:
            browser = select_browser(args.url, requirements)
            if args.json:
                print(json.dumps({"browser": browser.value}))
            else:
                print(f"Selected: {browser.value}")

    elif args.command == "analyze":
        hints = analyze_url(args.url)
        print(json.dumps(hints, indent=2))

    elif args.command == "verify-pair":
        primary = Browser(args.browser)
        secondary = get_verification_pair(primary)
        print(f"Primary: {primary.value}")
        print(f"Secondary: {secondary.value}")

    elif args.command == "test":
        success = run_tests()
        sys.exit(0 if success else 1)

    elif args.command == "list":
        print("Browser Capabilities:\n")
        print(f"{'Browser':<15} {'Auth':<6} {'Stealth':<8} {'Captcha':<8} {'CDP':<5} Description")
        print("-" * 80)
        for browser, caps in BROWSER_CAPABILITIES.items():
            print(
                f"{browser.value:<15} "
                f"{'Yes' if caps.auth else 'No':<6} "
                f"{'Yes' if caps.stealth else 'No':<8} "
                f"{'Yes' if caps.captcha else 'No':<8} "
                f"{'Yes' if caps.cdp else 'No':<5} "
                f"{caps.description}"
            )

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
