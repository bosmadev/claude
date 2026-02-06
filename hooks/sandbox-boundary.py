#!/usr/bin/env python3
"""
Layered Defense - Layer 2: Sandbox Boundaries

Enforces file system, network, and process restrictions to keep agents
within safe operational boundaries.

Integration: PreToolUse hook for Bash commands (blocks before execution)
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional


# =============================================================================
# Configuration
# =============================================================================

# Default allowed network hosts (whitelist)
# Can be extended via CLAUDE_ALLOWED_HOSTS env var (comma-separated)
_DEFAULT_HOSTS = [
    "github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "npmjs.com",
    "registry.npmjs.org",
    "pypi.org",
    "files.pythonhosted.org",
    "anthropic.com",
    "claude.ai",
]

import os
_extra_hosts = os.environ.get("CLAUDE_ALLOWED_HOSTS", "").split(",")
ALLOWED_HOSTS = _DEFAULT_HOSTS + [h.strip() for h in _extra_hosts if h.strip()]

# Blocked system directories
BLOCKED_PATHS = [
    "/etc",
    "/sys",
    "/proc",
    "/dev",
    "/boot",
    "/root",
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\ProgramData\\Microsoft",
]

# Allowed executables (whitelist)
ALLOWED_EXECUTABLES = [
    "git", "npm", "node", "pnpm", "python", "python3", "pip", "pip3",
    "uv", "biome", "knip", "tsc", "playwright", "vitest", "pytest",
    "docker", "docker-compose", "gh", "claude",
]


# =============================================================================
# Sandbox Checks
# =============================================================================

def check_file_access(file_path: str, project_root: str) -> Dict[str, any]:
    """
    Check if file access is within project boundaries.

    Returns:
        dict: {"allowed": bool, "reason": str}
    """
    try:
        # Use strict resolve (Python 3.6+) to catch symlinks to nonexistent targets
        # Check realpath to detect symlinks pointing outside sandbox
        abs_path = Path(file_path).resolve()
        proj_path = Path(project_root).resolve()

        # Detect symlink escape: if realpath differs significantly, block
        if abs_path.is_symlink():
            real_target = abs_path.resolve()
            if not str(real_target).startswith(str(proj_path)):
                return {
                    "allowed": False,
                    "reason": f"symlink_escape: {abs_path} -> {real_target}"
                }

        # Check if file is within project directory
        if proj_path in abs_path.parents or abs_path == proj_path:
            return {"allowed": True, "reason": "within_project"}

        # Check if accessing blocked system paths
        for blocked in BLOCKED_PATHS:
            if str(abs_path).startswith(blocked):
                return {
                    "allowed": False,
                    "reason": f"blocked_system_path: {blocked}"
                }

        # Outside project but not blocked - ask user
        return {
            "allowed": False,
            "reason": f"outside_project: {abs_path}"
        }

    except Exception as e:
        return {"allowed": False, "reason": f"error: {str(e)}"}


def check_network_host(host: str) -> Dict[str, any]:
    """
    Check if network host is in whitelist.

    Returns:
        dict: {"allowed": bool, "reason": str}
    """
    from urllib.parse import urlparse

    # Block dangerous URL schemes
    blocked_schemes = ["file", "data", "javascript", "vbscript"]

    # Parse URL properly to extract domain
    try:
        # Add scheme if missing for proper parsing
        if not host.startswith(("http://", "https://", "ssh://", "ftp://", "file://")):
            host = "https://" + host

        parsed = urlparse(host)

        # Block dangerous schemes
        if parsed.scheme.lower() in blocked_schemes:
            return {
                "allowed": False,
                "reason": f"blocked_scheme: {parsed.scheme}"
            }

        domain = (parsed.hostname or "").lower()
        if not domain:
            return {"allowed": False, "reason": "invalid_url: no hostname"}
    except Exception:
        return {"allowed": False, "reason": "invalid_url: parse_error"}

    # Check whitelist
    for allowed in ALLOWED_HOSTS:
        if domain == allowed or domain.endswith(f".{allowed}"):
            return {"allowed": True, "reason": "whitelisted"}

    return {
        "allowed": False,
        "reason": f"unknown_host: {domain}"
    }


def check_executable(command: str) -> Dict[str, any]:
    """
    Check if executable is in allowed list.

    Returns:
        dict: {"allowed": bool, "reason": str}
    """
    # Block dangerous shell builtins
    blocked_builtins = ["eval", "exec", "source", "."]

    # Extract first word (the executable)
    exe = command.split()[0] if command.strip() else ""

    # Check for shell builtins first
    if exe in blocked_builtins:
        return {
            "allowed": False,
            "reason": f"blocked_builtin: {exe}"
        }

    # For absolute paths, verify the target is in allowed list
    # This prevents bypass via /usr/bin/malicious
    exe_basename = Path(exe).name

    if exe_basename in ALLOWED_EXECUTABLES:
        return {"allowed": True, "reason": "whitelisted"}

    return {
        "allowed": False,
        "reason": f"unknown_executable: {exe}"
    }


# =============================================================================
# Hook Handler
# =============================================================================

def pretool_bash_sandbox(tool_input: Dict, cwd: str) -> Optional[Dict]:
    """
    PreToolUse hook for Bash - block commands violating sandbox boundaries.

    Args:
        tool_input: Tool input containing command
        cwd: Current working directory

    Returns:
        Optional[Dict]: Error result if violation detected, None otherwise
    """
    command = tool_input.get("command", "")

    # Check executable whitelist
    exe_check = check_executable(command)
    if not exe_check["allowed"]:
        return {
            "result": "error",
            "error": f"🚧 Blocked by sandbox boundary: {exe_check['reason']}\n\nCommand: {command}\nAllowed executables: {', '.join(ALLOWED_EXECUTABLES)}\n\nIf this executable is required, ask user for approval first."
        }

    # Check for file operations outside project
    import shlex
    if any(keyword in command for keyword in ["cd ", "mv ", "cp ", "rm ", ">", ">>"]):
        # Use shlex to properly parse quoted paths with spaces
        try:
            words = shlex.split(command)
        except ValueError:
            # Malformed quotes - fall back to simple split
            words = command.split()
        for word in words:
            if "/" in word or "\\" in word:
                file_check = check_file_access(word, cwd)
                if not file_check["allowed"]:
                    return {
                        "result": "error",
                        "error": f"🚧 Blocked by sandbox boundary: {file_check['reason']}\n\nPath: {word}\nProject root: {cwd}\n\nIf this path access is required, ask user for approval first."
                    }

    # Check for network operations
    if any(keyword in command for keyword in ["curl", "wget", "git clone", "git push", "npm install"]):
        for word in command.split():
            if any(proto in word for proto in ["http://", "https://", "git@", "ssh://"]):
                host_check = check_network_host(word)
                if not host_check["allowed"]:
                    return {
                        "result": "error",
                        "error": f"🚧 Blocked by sandbox boundary: {host_check['reason']}\n\nHost: {word}\nAllowed hosts: {', '.join(ALLOWED_HOSTS)}\n\nIf this host is safe, ask user for approval first."
                    }

    return None  # All checks passed - allow command to proceed


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """Hook entry point."""
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing hook arguments"}), file=sys.stderr)
        sys.exit(1)

    hook_type = sys.argv[1]

    if hook_type != "pretool":
        sys.exit(0)  # Not our hook

    # Read hook payload from stdin
    try:
        payload = json.loads(sys.stdin.read())
        tool_name = payload.get("tool_name", "")

        if tool_name != "Bash":
            sys.exit(0)  # Not Bash tool

        tool_input = payload.get("tool_input", {})
        cwd = payload.get("cwd", ".")

        result = pretool_bash_sandbox(tool_input, cwd)

        if result:
            print(json.dumps(result))
            sys.exit(0)

        sys.exit(0)  # Pass through

    except Exception as e:
        print(json.dumps({"error": f"Hook error: {str(e)}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
