#!/usr/bin/env python3
r"""Self-healing hook for Chrome native host .bat file and Gc4 Windows pipe patch.

Protects the .bat from being overwritten by Claude Code updates that regenerate it
to use claude.exe (Bun standalone) which crashes on stdin (GitHub issue #22901).

Also patches Gc4() in cli.js to include Windows named pipe paths, fixing the
"Browser extension is not connected" issue on Windows. The MCP client in claude.exe
uses Gc4() to find the native host socket, but on Windows it only returns tmpdir
paths that can't connect to named pipes. The patch adds named pipe paths.

This hook maintains TWO cli.js installations:
1. Isolated install: ~/.claude/chrome/node_host/ (used by .bat for native host)
2. npm global install: D:\nvm4w\nodejs\node_modules\@anthropic-ai\claude-code\

This hook:
1. Checks if .bat references claude.exe or Bun
2. If broken: rewrites to use node.exe + cli.js
3. Verifies version match between claude.exe and both cli.js installs
4. If version mismatch: installs correct @anthropic-ai/claude-code version
5. Patches Gc4() in BOTH cli.js files to add Windows named pipe discovery
6. Only outputs to stderr if fixes were made (silent when healthy)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal

# Paths
BAT_PATH = Path(r"C:\Users\Dennis\.claude\chrome\chrome-native-host.bat")
NODE_EXE = Path(r"D:\nvm4w\nodejs\node.exe")
NODE_HOST_DIR = Path(r"C:\Users\Dennis\.claude\chrome\node_host")
CLI_JS_PATH = NODE_HOST_DIR / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
PACKAGE_JSON_PATH = (
    NODE_HOST_DIR / "node_modules" / "@anthropic-ai" / "claude-code" / "package.json"
)
NPM_CLI_JS_PATH = Path(r"D:\nvm4w\nodejs\node_modules\@anthropic-ai\claude-code\cli.js")
NPM_PACKAGE_JSON_PATH = Path(r"D:\nvm4w\nodejs\node_modules\@anthropic-ai\claude-code\package.json")
CLAUDE_EXE = Path(r"C:\Users\Dennis\.local\bin\claude.exe")

# Expected .bat content
CORRECT_BAT_CONTENT = """@echo off
REM Chrome native host wrapper script
REM Fixed: Uses Node.js instead of Bun standalone to avoid stdin crash (GH #22901)
REM Node.js path via nvm4w, cli.js installed to isolated directory
"D:\\nvm4w\\nodejs\\node.exe" "C:\\Users\\Dennis\\.claude\\chrome\\node_host\\node_modules\\@anthropic-ai\\claude-code\\cli.js" --chrome-native-host
"""


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


def get_claude_exe_version() -> str | None:
    """Get version from claude.exe --version."""
    if not CLAUDE_EXE.exists():
        return None

    try:
        result = subprocess.run(
            [str(CLAUDE_EXE), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        # Output format: "2.1.34 (Claude Code)" or "claude-code version X.Y.Z"
        match = re.search(r"(\d+\.\d+\.\d+)", result.stdout)
        return match.group(1) if match else None
    except Exception:
        return None


def get_cli_js_version(package_json_path: Path = PACKAGE_JSON_PATH) -> str | None:
    """Get version from cli.js package.json."""
    if not package_json_path.exists():
        return None

    try:
        with open(package_json_path, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("version")
    except Exception:
        return None


def is_bat_broken() -> bool:
    """Check if .bat references claude.exe or Bun instead of node.exe + cli.js."""
    if not BAT_PATH.exists():
        return True

    try:
        content = BAT_PATH.read_text(encoding="utf-8")
        # Check for incorrect patterns
        has_claude_exe = "claude.exe" in content
        has_bun_ref = "bun" in content.lower()
        has_correct_node = (
            str(NODE_EXE) in content
            and str(CLI_JS_PATH) in content
        )

        return has_claude_exe or has_bun_ref or not has_correct_node
    except Exception:
        return True


def fix_bat() -> bool:
    """Rewrite .bat to use node.exe + cli.js. Returns True if fix was applied."""
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
        )

        if result.returncode == 0:
            log_error(f"✓ Installed @anthropic-ai/claude-code@{target_version} to isolated dir")
            # Re-apply Gc4 patch after fresh install
            patch_gc4(CLI_JS_PATH)
            return True

        log_error(f"✗ npm install failed: {result.stderr}")
        return False
    except Exception as e:
        log_error(f"✗ Failed to install cli.js: {e}")
        return False


def sync_npm_cli_version(target_version: str) -> bool:
    """Install correct @anthropic-ai/claude-code version globally via npm. Returns True if install ran."""
    log_error(f"Installing @anthropic-ai/claude-code@{target_version} globally via npm...")

    try:
        result = subprocess.run(
            [
                "npm",
                "install",
                "-g",
                f"@anthropic-ai/claude-code@{target_version}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        if result.returncode == 0:
            log_error(f"✓ Installed @anthropic-ai/claude-code@{target_version} globally")
            # Re-apply Gc4 patch after fresh install
            patch_gc4(NPM_CLI_JS_PATH)
            return True

        log_error(f"✗ npm install -g failed: {result.stderr}")
        return False
    except Exception as e:
        log_error(f"✗ Failed to install npm global cli.js: {e}")
        return False


# The ORIGINAL unpatched Gc4 function signature (to detect if patch is needed)
GC4_WIN32_MARKER = 'qCY()==="win32"'

# The patch: adds Windows named pipe to Gc4's search paths
# Inserted before 'return A}' in function Gc4
GC4_PATCH = 'if(qCY()==="win32"){let W=`\\\\\\\\.\\\\pipe\\\\${K}`;if(!A.includes(W))A.push(W)}'


def is_gc4_patched(cli_js_path: Path = CLI_JS_PATH) -> bool:
    """Check if Gc4 in cli.js already has the Windows pipe patch."""
    if not cli_js_path.exists():
        return False

    try:
        code = cli_js_path.read_text(encoding="utf-8")
        # Find Gc4 function
        start = code.find("function Gc4(){")
        if start == -1:
            return False
        # Check if win32 check exists in the function (within 500 chars)
        snippet = code[start : start + 800]
        return GC4_WIN32_MARKER in snippet
    except Exception:
        return False


def patch_gc4(cli_js_path: Path = CLI_JS_PATH) -> bool:
    r"""Patch Gc4() in cli.js to add Windows named pipe path discovery.

    The unpatched Gc4 on Windows only returns os.tmpdir() paths, which can't
    connect to named pipes. This patch adds \\.\pipe\NAME to the search list.
    """
    if not cli_js_path.exists():
        log_error(f"✗ cli.js not found at {cli_js_path}, cannot patch Gc4")
        return False

    if is_gc4_patched(cli_js_path):
        return False  # Already patched, no action needed

    try:
        code = cli_js_path.read_text(encoding="utf-8")

        # Find the Gc4 function
        func_start = code.find("function Gc4(){")
        if func_start == -1:
            log_error(f"✗ Cannot find Gc4 function in {cli_js_path.name}")
            return False

        # Find 'return A}' within the function (the last return before closing brace)
        # Search from func_start to avoid matching other functions
        search_area = code[func_start : func_start + 500]
        return_idx = search_area.find("return A}")
        if return_idx == -1:
            log_error(f"✗ Cannot find 'return A}}' in Gc4 at {cli_js_path.name}")
            return False

        # Insert patch before 'return A}'
        abs_idx = func_start + return_idx
        patched = code[:abs_idx] + GC4_PATCH + code[abs_idx:]

        cli_js_path.write_text(patched, encoding="utf-8")
        log_error(f"✓ Patched Gc4 in {cli_js_path.name} with Windows named pipe support")
        return True
    except Exception as e:
        log_error(f"✗ Failed to patch Gc4 in {cli_js_path.name}: {e}")
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

    # Get claude.exe version for sync checks
    claude_version = get_claude_exe_version()

    # Verify version match between claude.exe and isolated cli.js
    cli_version = get_cli_js_version(PACKAGE_JSON_PATH)
    if claude_version and cli_version and claude_version != cli_version:
        log_error(
            f"Version mismatch: claude.exe={claude_version}, isolated cli.js={cli_version}"
        )
        if sync_cli_js_version(claude_version):
            fixes_applied = True

    # Ensure Gc4 Windows pipe patch is applied to isolated cli.js
    if not is_gc4_patched(CLI_JS_PATH):
        if patch_gc4(CLI_JS_PATH):
            fixes_applied = True

    # Verify version match between claude.exe and npm global cli.js
    npm_cli_version = get_cli_js_version(NPM_PACKAGE_JSON_PATH)
    if claude_version and npm_cli_version and claude_version != npm_cli_version:
        log_error(
            f"Version mismatch: claude.exe={claude_version}, npm cli.js={npm_cli_version}"
        )
        if sync_npm_cli_version(claude_version):
            fixes_applied = True

    # Ensure Gc4 Windows pipe patch is applied to npm cli.js
    if NPM_CLI_JS_PATH.exists() and not is_gc4_patched(NPM_CLI_JS_PATH):
        if patch_gc4(NPM_CLI_JS_PATH):
            fixes_applied = True

    # Only log success if we actually did something
    if not fixes_applied:
        # Silent success - no output to stderr
        pass

    # Always continue, suppress output unless fixes were made
    hook_response(continue_execution=True, suppress_output=not fixes_applied)


if __name__ == "__main__":
    main()
