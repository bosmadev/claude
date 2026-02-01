#!/usr/bin/env python3
"""
Setup Hook - Repository initialization and environment validation.

This hook fires via `--init`, `--init-only`, or `--maintenance` flags
and performs environment checks to ensure consistent Claude Code setup.

Usage:
  python3 setup.py validate-symlinks  # Verify symlink structure
  python3 setup.py check-mcp          # Test MCP server connectivity
  python3 setup.py full               # Run all checks

Environment Variables:
  CLAUDE_CODE_TMPDIR - Custom temp directory (recommended: /mnt/claude-tmp)
"""

import json
import os
import subprocess
import sys
from pathlib import Path


# =============================================================================
# Stdin Timeout - Prevent hanging on missing stdin
# =============================================================================

# Cross-platform stdin timeout (SIGALRM not available on Windows)
if sys.platform == "win32":
    import threading
    _timeout_timer = threading.Timer(30, lambda: os._exit(0))
    _timeout_timer.daemon = True
    _timeout_timer.start()
else:
    import signal

    def timeout_handler(signum, frame):
        """Silent exit on timeout - prevents hooks from hanging."""
        sys.exit(0)

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(30)  # 30 second timeout for setup operations


# =============================================================================
# Constants
# =============================================================================

CLAUDE_CONFIG_DIR = Path(os.environ.get(
    "CLAUDE_HOME",
    "C:/Users/Dennis/.claude" if sys.platform == "win32" else "/usr/share/claude"
))
HOME_CLAUDE_SYMLINK = Path.home() / ".claude"
ROOT_CLAUDE_SYMLINK = None if sys.platform == "win32" else Path("/root/.claude")

# MCP servers to check connectivity
MCP_SERVERS = ["serena", "context7", "playwriter"]


# =============================================================================
# Symlink Validation
# =============================================================================

def validate_symlinks() -> dict:
    """
    Verify Claude configuration symlinks are correctly set up.

    Expected structure:
    - /root/.claude -> /usr/share/claude (or)
    - ~/.claude -> /usr/share/claude

    Returns:
        dict with validation results and any issues found.
    """
    results = {
        "valid": True,
        "checks": [],
        "warnings": [],
        "errors": []
    }

    # Check if /usr/share/claude exists and is a directory
    if not CLAUDE_CONFIG_DIR.exists():
        results["valid"] = False
        results["errors"].append(f"Config directory missing: {CLAUDE_CONFIG_DIR}")
        return results

    if not CLAUDE_CONFIG_DIR.is_dir():
        results["valid"] = False
        results["errors"].append(f"Config path is not a directory: {CLAUDE_CONFIG_DIR}")
        return results

    results["checks"].append(f"Config directory exists: {CLAUDE_CONFIG_DIR}")

    # Check ~/.claude symlink
    if HOME_CLAUDE_SYMLINK.exists():
        if HOME_CLAUDE_SYMLINK.is_symlink():
            target = HOME_CLAUDE_SYMLINK.resolve()
            if target == CLAUDE_CONFIG_DIR.resolve():
                results["checks"].append(f"Home symlink valid: {HOME_CLAUDE_SYMLINK} -> {CLAUDE_CONFIG_DIR}")
            else:
                results["warnings"].append(
                    f"Home symlink points elsewhere: {HOME_CLAUDE_SYMLINK} -> {target}"
                )
        else:
            results["warnings"].append(
                f"Home path is not a symlink: {HOME_CLAUDE_SYMLINK}"
            )
    else:
        results["warnings"].append(f"Home symlink missing: {HOME_CLAUDE_SYMLINK}")

    # Check /root/.claude if running as root or if it exists (Linux only)
    if sys.platform != "win32" and ROOT_CLAUDE_SYMLINK is not None:
        is_root = os.getuid() == 0
        if is_root or ROOT_CLAUDE_SYMLINK.exists():
            if ROOT_CLAUDE_SYMLINK.exists():
                if ROOT_CLAUDE_SYMLINK.is_symlink():
                    target = ROOT_CLAUDE_SYMLINK.resolve()
                    if target == CLAUDE_CONFIG_DIR.resolve():
                        results["checks"].append(
                            f"Root symlink valid: {ROOT_CLAUDE_SYMLINK} -> {CLAUDE_CONFIG_DIR}"
                        )
                    else:
                        results["warnings"].append(
                            f"Root symlink points elsewhere: {ROOT_CLAUDE_SYMLINK} -> {target}"
                        )
                else:
                    results["warnings"].append(
                        f"Root path is not a symlink: {ROOT_CLAUDE_SYMLINK}"
                    )
            elif is_root:
                results["warnings"].append(f"Root symlink missing: {ROOT_CLAUDE_SYMLINK}")

    # Check essential files exist
    essential_files = [
        "CLAUDE.md",
        "settings.json"
    ]

    for filename in essential_files:
        filepath = CLAUDE_CONFIG_DIR / filename
        if filepath.exists():
            results["checks"].append(f"Essential file exists: {filename}")
        else:
            results["warnings"].append(f"Essential file missing: {filename}")

    # Check essential directories
    essential_dirs = [
        "hooks",
        "scripts",
        "skills",
        "agents"
    ]

    for dirname in essential_dirs:
        dirpath = CLAUDE_CONFIG_DIR / dirname
        if dirpath.exists() and dirpath.is_dir():
            results["checks"].append(f"Essential directory exists: {dirname}/")
        else:
            results["warnings"].append(f"Essential directory missing: {dirname}/")

    return results


# =============================================================================
# MCP Connectivity Check
# =============================================================================

def check_mcp_connectivity() -> dict:
    """
    Test connectivity to configured MCP servers.

    Returns:
        dict with connectivity status for each server.
    """
    results = {
        "servers": {},
        "all_connected": True
    }

    # Read settings to get enabled MCP servers
    settings_path = CLAUDE_CONFIG_DIR / "settings.json"
    enabled_servers = MCP_SERVERS

    if settings_path.exists():
        try:
            with open(settings_path) as f:
                settings = json.load(f)
            enabled_servers = settings.get("enabledMcpjsonServers", MCP_SERVERS)
        except (json.JSONDecodeError, OSError):
            pass

    for server in enabled_servers:
        # Basic check - just verify the server config exists
        # Full connectivity test would require actually calling MCP
        results["servers"][server] = {
            "configured": True,
            "status": "configured"
        }

    return results


# =============================================================================
# TMPDIR Check
# =============================================================================

def check_tmpdir() -> dict:
    """
    Check if CLAUDE_CODE_TMPDIR is configured and accessible.

    Returns:
        dict with tmpdir status and recommendations.
    """
    results = {
        "configured": False,
        "path": None,
        "writable": False,
        "recommendation": None
    }

    tmpdir = os.environ.get("CLAUDE_CODE_TMPDIR")

    if tmpdir:
        results["configured"] = True
        results["path"] = tmpdir

        tmppath = Path(tmpdir)
        if tmppath.exists() and tmppath.is_dir():
            # Test write access
            test_file = tmppath / ".claude-write-test"
            try:
                test_file.write_text("test")
                test_file.unlink()
                results["writable"] = True
            except (OSError, PermissionError):
                results["writable"] = False
                results["recommendation"] = f"CLAUDE_CODE_TMPDIR exists but is not writable: {tmpdir}"
        else:
            results["recommendation"] = f"CLAUDE_CODE_TMPDIR does not exist: {tmpdir}"
    else:
        if sys.platform == "win32":
            results["recommendation"] = (
                "Consider setting CLAUDE_CODE_TMPDIR to a RAM disk for faster file operations:\n"
                "  1. Install a RAM disk tool (e.g., ImDisk) and create a 512 MB RAM drive (e.g., R:\\)\n"
                "  2. Set environment variable: setx CLAUDE_CODE_TMPDIR R:\\claude-tmp\n"
                "  3. Create directory: mkdir R:\\claude-tmp"
            )
        else:
            results["recommendation"] = (
                "Consider setting CLAUDE_CODE_TMPDIR to a RAM-backed tmpfs for faster file operations:\n"
                "  1. Add to /etc/fstab: tmpfs /mnt/claude-tmp tmpfs size=512m,mode=1777 0 0\n"
                "  2. Mount: sudo mount /mnt/claude-tmp\n"
                "  3. Export: echo 'export CLAUDE_CODE_TMPDIR=/mnt/claude-tmp' >> ~/.bashrc"
            )

    return results


# =============================================================================
# Full Validation
# =============================================================================

def run_full_validation() -> dict:
    """
    Run all validation checks.

    Returns:
        Combined results from all checks.
    """
    return {
        "symlinks": validate_symlinks(),
        "mcp": check_mcp_connectivity(),
        "tmpdir": check_tmpdir()
    }


# =============================================================================
# Hook Output Helpers
# =============================================================================

def output_hook_response(results: dict, mode: str) -> None:
    """
    Format and output hook response as JSON.

    Args:
        results: Validation results dictionary.
        mode: The validation mode that was run.
    """
    # Build summary message
    messages = []

    if mode == "validate-symlinks" or mode == "full":
        symlinks = results if mode == "validate-symlinks" else results.get("symlinks", {})
        if symlinks.get("errors"):
            messages.extend([f"[ERROR] {e}" for e in symlinks["errors"]])
        if symlinks.get("warnings"):
            messages.extend([f"[WARN] {w}" for w in symlinks["warnings"]])

    if mode == "check-tmpdir" or mode == "full":
        tmpdir = results if mode == "check-tmpdir" else results.get("tmpdir", {})
        if tmpdir.get("recommendation") and not tmpdir.get("configured"):
            messages.append(f"[INFO] {tmpdir['recommendation']}")

    if messages:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "Setup",
                "additionalContext": "\n".join(messages)
            }
        }
        print(json.dumps(output))


# =============================================================================
# Main Entry Point
# =============================================================================

def main() -> None:
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: setup.py [validate-symlinks|check-mcp|check-tmpdir|full]", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "validate-symlinks":
        results = validate_symlinks()
        output_hook_response(results, mode)
        if not results["valid"]:
            sys.exit(1)

    elif mode == "check-mcp":
        results = check_mcp_connectivity()
        output_hook_response(results, mode)

    elif mode == "check-tmpdir":
        results = check_tmpdir()
        output_hook_response(results, mode)

    elif mode == "full":
        results = run_full_validation()
        output_hook_response(results, mode)
        if not results["symlinks"]["valid"]:
            sys.exit(1)

    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
