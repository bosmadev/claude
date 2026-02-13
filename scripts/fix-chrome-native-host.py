#!/usr/bin/env python3
r"""Self-healing hook for Chrome native host .bat file and getSocketPaths Windows pipe patch.

Protects the .bat from being overwritten by Claude Code updates that regenerate it
to use claude.exe (Bun standalone) which crashes on stdin (GitHub issue #22901).

Also patches the getSocketPaths function (minified name varies per version) in cli.js
to include Windows named pipe paths with username sanitization, fixing the
"Browser extension is not connected" issue on Windows (GitHub issues #23082, #23828, #23539).

VERSION DETECTION:
- CC 2.1.41+: Native Windows pipe support detected via early return pattern
- CC 2.1.40 and earlier: Manual patch injected before 'return A}'
- Script auto-detects which approach is needed and skips patching if native support exists

This hook maintains TWO cli.js installations:
1. Isolated install: ~/.claude/chrome/node_host/ (used by .bat for native host)
2. npm global install: D:\nvm4w\nodejs\node_modules\@anthropic-ai\claude-code\

This hook:
1. Checks if .bat references claude.exe or Bun
2. If broken: rewrites to use node.exe + cli.js (with USERNAME sanitization)
3. Gets version from npm global package.json (source of truth)
4. Verifies version match with isolated cli.js install
5. If version mismatch: installs correct @anthropic-ai/claude-code version
6. Detects native Windows pipe support (CC 2.1.41+) OR patches getSocketPaths (pre-2.1.41)
7. Only outputs to stderr if fixes were made (silent when healthy)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Paths - dynamically computed from home directory
CLAUDE_HOME = Path.home() / ".claude"
BAT_PATH = CLAUDE_HOME / "chrome" / "chrome-native-host.bat"
NODE_HOST_DIR = CLAUDE_HOME / "chrome" / "node_host"
CLI_JS_PATH = NODE_HOST_DIR / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
PACKAGE_JSON_PATH = (
    NODE_HOST_DIR / "node_modules" / "@anthropic-ai" / "claude-code" / "package.json"
)

# Detect npm global install location dynamically
def _get_npm_global_prefix() -> Path:
    """Get npm global prefix (e.g., D:/nvm4w/nodejs on Windows, /usr/local on Linux)."""
    try:
        result = subprocess.run(
            ["npm", "config", "get", "prefix"],
            capture_output=True,
            text=True,
            timeout=5,
            shell=True,  # Windows needs shell for npm.cmd
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    # Fallback: platform-specific defaults
    if sys.platform == "win32":
        # Common Windows locations
        for candidate in [Path("D:/nvm4w/nodejs"), Path("C:/Program Files/nodejs")]:
            if candidate.exists():
                return candidate
    else:
        # Unix-like defaults
        for candidate in [Path("/usr/local"), Path.home() / ".local"]:
            if candidate.exists():
                return candidate
    return Path("/usr/local")  # Final fallback

NPM_PREFIX = _get_npm_global_prefix()
NPM_CLI_JS_PATH = NPM_PREFIX / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
NPM_PACKAGE_JSON_PATH = NPM_PREFIX / "node_modules" / "@anthropic-ai" / "claude-code" / "package.json"
NODE_EXE = NPM_PREFIX / ("node.exe" if sys.platform == "win32" else "bin" / "node")

# Expected .bat content — includes USERNAME sanitization for pipe name consistency
# Template is computed dynamically to use actual paths
def _get_bat_content() -> str:
    """Generate .bat content with actual system paths."""
    return f"""@echo off
REM Chrome native host wrapper script
REM Fixed: Uses Node.js instead of Bun standalone to avoid stdin crash (GH #22901)
REM Fixed: Strips spaces from USERNAME for pipe name consistency (GH #23828)
SET "USERNAME=%USERNAME: =%"
"{NODE_EXE}" "{CLI_JS_PATH}" --chrome-native-host
"""

CORRECT_BAT_CONTENT = _get_bat_content()

# Self-contained ESM-compatible patch: uses process globals only.
# cli.js is "type": "module" (ESM) so require() is not available.
# process.env.USERNAME is always set on Windows and matches the native host's pipe name.
# The native host .bat strips spaces via SET "USERNAME=%USERNAME: =%".
PIPE_PATCH = (
    'if(process.platform==="win32"){'
    'let W=`\\\\\\\\.\\\\pipe\\\\claude-mcp-browser-bridge-${process.env.USERNAME||"default"}`;'
    'if(!A.includes(W))A.push(W)}'
)

# Marker to detect if our exact current patch is applied
PIPE_PATCH_MARKER = 'process.env.USERNAME||"default"}`;if(!A'


def hook_response(
    continue_execution: bool = True, suppress_output: bool = True
) -> None:
    """Send hook protocol response to stdout."""
    response = {"continue": continue_execution, "suppressOutput": suppress_output}
    sys.stdout.write(json.dumps(response))
    sys.stdout.flush()


def log_error(message: str) -> None:
    """Print error message to stderr."""
    sys.stderr.write(f"[fix-chrome-native-host] {message}\n")
    sys.stderr.flush()


def get_cli_js_version(package_json_path: Path = PACKAGE_JSON_PATH) -> str | None:
    """Get version from package.json."""
    if not package_json_path.exists():
        return None

    try:
        with open(package_json_path, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("version")
    except Exception:
        return None


def get_npm_global_version() -> str | None:
    """Get version from npm global package.json (source of truth)."""
    return get_cli_js_version(NPM_PACKAGE_JSON_PATH)


def is_bat_broken() -> bool:
    """Check if .bat is missing, references claude.exe/Bun, or lacks USERNAME sanitization."""
    if not BAT_PATH.exists():
        return True

    try:
        content = BAT_PATH.read_text(encoding="utf-8")
        # Check executable lines (skip REM comments) for incorrect patterns
        exec_lines = [
            line for line in content.splitlines()
            if line.strip() and not line.strip().upper().startswith("REM")
        ]
        exec_content = "\n".join(exec_lines)
        has_claude_exe = "claude.exe" in exec_content
        has_bun_ref = "bun" in exec_content.lower()
        has_correct_node = (
            str(NODE_EXE) in content
            and str(CLI_JS_PATH) in content
        )
        has_username_fix = "USERNAME=%USERNAME: =%" in content

        return has_claude_exe or has_bun_ref or not has_correct_node or not has_username_fix
    except Exception:
        return True


def fix_bat() -> bool:
    """Rewrite .bat to use node.exe + cli.js with USERNAME sanitization. Returns True if fix was applied."""
    if not BAT_PATH.exists():
        log_error(f"Creating missing .bat: {BAT_PATH}")
    else:
        log_error(f"Fixing broken .bat: {BAT_PATH}")

    try:
        BAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        BAT_PATH.write_text(CORRECT_BAT_CONTENT, encoding="utf-8")
        log_error("✓ .bat file fixed")
        return True
    except Exception as e:
        log_error(f"✗ Failed to fix .bat: {e}")
        return False


def sync_cli_js_version(target_version: str) -> bool:
    """Install correct @anthropic-ai/claude-code version to isolated dir. Returns True if install ran."""
    log_error(f"Installing @anthropic-ai/claude-code@{target_version} to isolated dir...")

    try:
        NODE_HOST_DIR.mkdir(parents=True, exist_ok=True)

        # Use shell=True on Windows because npm is a .cmd wrapper
        result = subprocess.run(
            [
                "npm",
                "install",
                f"@anthropic-ai/claude-code@{target_version}",
                "--prefix",
                str(NODE_HOST_DIR),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            shell=True,
        )

        if result.returncode == 0:
            log_error(f"✓ Installed @anthropic-ai/claude-code@{target_version} to isolated dir")
            # Re-apply pipe patch after fresh install
            patch_socket_paths(CLI_JS_PATH)
            return True

        log_error(f"✗ npm install failed: {result.stderr}")
        return False
    except Exception as e:
        log_error(f"✗ Failed to install cli.js: {e}")
        return False


def find_get_socket_paths_function(code: str) -> tuple[int, int, str] | None:
    """Find the getSocketPaths function by content signature, not minified name.

    Strategy: find 'claude-mcp-browser-bridge' anchor, scan backwards for the nearest
    'function NAME(){' declaration, then use brace counting to find exact boundaries.
    Only matches functions that also contain 'return A}' (the array return).

    Returns (start, end, func_name) or None.
    """
    bridge_idx = code.find('claude-mcp-browser-bridge')
    while bridge_idx != -1:
        # Look backwards up to 500 chars for the nearest function declaration
        search_start = max(0, bridge_idx - 500)
        chunk_before = code[search_start:bridge_idx]
        func_matches = list(re.finditer(r'function\s+(\w+)\(\)\{', chunk_before))

        if func_matches:
            last = func_matches[-1]
            func_start = search_start + last.start()
            func_name = last.group(1)

            # Find function end via brace counting (limit to 800 chars — function is ~250-350)
            depth = 0
            j = func_start
            while j < len(code) and j < func_start + 800:
                if code[j] == '{':
                    depth += 1
                elif code[j] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                j += 1

            if depth == 0:
                func_end = j + 1
                body = code[func_start:func_end]
                if 'claude-mcp-browser-bridge' in body and 'return A}' in body:
                    return (func_start, func_end, func_name)

        bridge_idx = code.find('claude-mcp-browser-bridge', bridge_idx + 25)
    return None


def is_socket_paths_patched(cli_js_path: Path) -> bool:
    """Check if the getSocketPaths function already has Windows pipe support.

    CC 2.1.41+ has native Windows pipe support via early return at function start.
    Pre-2.1.41 versions need our manual patch injected before 'return A}'.

    Returns True if EITHER:
    1. Native support detected (CC 2.1.41+): Early 'if(platform=="win32")return[pipe]' pattern
    2. Our patch detected (pre-2.1.41): PIPE_PATCH_MARKER in function body
    """
    if not cli_js_path.exists():
        return False

    try:
        code = cli_js_path.read_text(encoding="utf-8")
        result = find_get_socket_paths_function(code)
        if result is None:
            return False

        start, end, _ = result
        snippet = code[start:end]

        # CC 2.1.41+ native support detection:
        # Look for early return pattern: if(platform_check()==="win32")return[`\.\pipe\..`]
        # This pattern appears at the START of the function (within first 150 chars after opening brace)
        # Example: if(td7()==="win32")return[`\\\\.\\pipe\\${zc7()}`]
        opening_brace = snippet.find('{')
        if opening_brace != -1:
            early_code = snippet[opening_brace:opening_brace + 150]
            # Match: if(FUNC()==="win32")return[`...pipe...`]
            native_pattern = r'if\(\w+\(\)==="win32"\)return\[`[^`]*\\\\pipe\\\\[^`]*`\]'
            if re.search(native_pattern, early_code):
                return True  # Native Windows pipe support detected (CC 2.1.41+)

        # Pre-2.1.41 manual patch detection:
        # Check for our self-contained marker (not the old qCY-based one)
        return PIPE_PATCH_MARKER in snippet
    except Exception:
        return False


def patch_socket_paths(cli_js_path: Path) -> bool:
    r"""Patch getSocketPaths in cli.js to add Windows named pipe path discovery.

    CC 2.1.41+: Native Windows pipe support exists, this function returns False (no patch needed)
    CC 2.1.40 and earlier: Injects Windows pipe path before 'return A}'

    The unpatched function on Windows (pre-2.1.41) only returns os.tmpdir() and /tmp paths,
    which can't connect to named pipes. This patch adds \\.\pipe\claude-mcp-browser-bridge-USERNAME
    to the search list, matching what the native host creates.

    Uses content-based pattern matching to find the function regardless of minified name.
    Uses self-contained process.platform + process.env to avoid dependency on
    minified helper function names that change between versions.

    Returns True if patch was applied, False if native support exists or already patched.
    """
    if not cli_js_path.exists():
        log_error(f"✗ cli.js not found at {cli_js_path}")
        return False

    try:
        code = cli_js_path.read_text(encoding="utf-8")

        result = find_get_socket_paths_function(code)
        if result is None:
            log_error(f"✗ Cannot find getSocketPaths function in {cli_js_path.name}")
            return False

        start, end, func_name = result
        snippet = code[start:end]

        # Check if already has our exact current patch and no stale patches
        pipe_count = snippet.count('pipe\\\\claude-mcp')
        if PIPE_PATCH_MARKER in snippet and pipe_count == 1:
            return False  # Exactly one patch and it's ours

        # Remove ALL pipe-related patches (old and current) to ensure clean state.
        # We'll always re-inject the canonical patch.
        # Match: if(EXPR==="win32"){let W=`...pipe...`;if(!A.includes(W))A.push(W)}
        pipe_patch_pattern = (
            r'if\((?:\w+\(\)|process\.platform)==="win32"\)'
            r'\{let W=`[^`]*pipe[^`]*`;'
            r'if\(!A\.includes\(W\)\)A\.push\(W\)\}'
        )
        snippet_cleaned = re.sub(pipe_patch_pattern, '', snippet)

        # Find 'return A}' — the end of the function
        return_idx = snippet_cleaned.rfind('return A}')
        if return_idx == -1:
            log_error(f"✗ Cannot find 'return A}}' in {func_name} at {cli_js_path.name}")
            return False

        # Insert our self-contained patch before 'return A}'
        patched_snippet = snippet_cleaned[:return_idx] + PIPE_PATCH + snippet_cleaned[return_idx:]

        # Replace the original function with patched version
        patched_code = code[:start] + patched_snippet + code[end:]

        cli_js_path.write_text(patched_code, encoding="utf-8")
        log_error(f"✓ Patched {func_name}() in {cli_js_path.name} with Windows pipe + username sanitization")
        return True
    except Exception as e:
        log_error(f"✗ Failed to patch {cli_js_path.name}: {e}")
        return False


def disable_bridge_flag() -> bool:
    """Disable tengu_copper_bridge in .claude.json cached features.

    The WSS bridge (bridge.claudeusercontent.com) is broken on Windows:
    - oauthAccount.accountUuid never populated (requires token refresh)
    - Extension startup race condition (isFeatureEnabledAsync returns false)
    - addinCount always 0 (pairing never succeeds)

    When the bridge is enabled, the MCP server uses it EXCLUSIVELY (no fallback to
    sockets/pipes). Disabling forces the socket pool path, which works with our
    getSocketPaths pipe patch. See: anthropics/claude-code#23828
    """
    claude_json = CLAUDE_HOME / ".claude.json"
    if not claude_json.exists():
        return False

    try:
        with open(claude_json, encoding="utf-8") as f:
            data = json.load(f)

        features = data.get("cachedGrowthBookFeatures", {})
        if features.get("tengu_copper_bridge") is True:
            features["tengu_copper_bridge"] = False
            with open(claude_json, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            log_error("✓ Disabled tengu_copper_bridge (WSS bridge broken on Windows)")
            return True
    except Exception as e:
        log_error(f"✗ Failed to disable bridge flag: {e}")

    return False


def main() -> None:
    """Main hook logic."""
    # Consume stdin (hook protocol requirement)
    sys.stdin.read()

    fixes_applied = False

    # Check and fix .bat if broken
    if is_bat_broken():
        if fix_bat():
            fixes_applied = True

    # Get npm global version as source of truth
    npm_version = get_npm_global_version()

    # Verify version match between npm global and isolated cli.js
    cli_version = get_cli_js_version(PACKAGE_JSON_PATH)
    if npm_version and cli_version and npm_version != cli_version:
        log_error(
            f"Version mismatch: npm global={npm_version}, isolated cli.js={cli_version}"
        )
        if sync_cli_js_version(npm_version):
            fixes_applied = True
    elif npm_version and not cli_version:
        # Isolated install doesn't exist yet
        log_error(f"Isolated cli.js missing, installing v{npm_version}")
        if sync_cli_js_version(npm_version):
            fixes_applied = True

    # Ensure pipe patch is applied to isolated cli.js
    if CLI_JS_PATH.exists() and not is_socket_paths_patched(CLI_JS_PATH):
        if patch_socket_paths(CLI_JS_PATH):
            fixes_applied = True

    # Ensure pipe patch is applied to npm global cli.js
    if NPM_CLI_JS_PATH.exists() and not is_socket_paths_patched(NPM_CLI_JS_PATH):
        if patch_socket_paths(NPM_CLI_JS_PATH):
            fixes_applied = True

    # Disable bridge (tengu_copper_bridge) — WSS bridge is broken on Windows
    # (accountUuid never populated, extension startup race condition).
    # Forces socket/pipe path which works with our getSocketPaths patch.
    if disable_bridge_flag():
        fixes_applied = True

    # Only log success if we actually did something
    if not fixes_applied:
        # Silent success - no output to stderr
        pass

    # Always continue, suppress output unless fixes were made
    hook_response(continue_execution=True, suppress_output=not fixes_applied)


if __name__ == "__main__":
    main()
