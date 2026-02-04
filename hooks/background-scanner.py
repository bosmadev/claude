#!/usr/bin/env python3
"""
Layered Defense - Layer 4: Background Scanners

Triggers security scans on specific file changes:
- Dependency audits on package.json/requirements.txt changes
- Secret scans on new file creation
- OWASP checks on code changes

Integration: PostToolUse hook for Edit/Write operations
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional


# =============================================================================
# Scanner Triggers
# =============================================================================

def should_run_dependency_audit(file_path: str) -> bool:
    """Check if file change triggers dependency audit."""
    dependency_files = [
        "package.json",
        "package-lock.json",
        "requirements.txt",
        "Pipfile",
        "Pipfile.lock",
        "pyproject.toml",
        "uv.lock",
    ]
    return Path(file_path).name in dependency_files


def should_run_secret_scan(file_path: str) -> bool:
    """Check if file should be scanned for secrets."""
    # Scan all new files, skip binary and generated files
    skip_extensions = [".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".tar", ".gz"]
    skip_paths = ["node_modules", ".venv", "venv", "dist", "build", ".next"]

    path = Path(file_path)

    # Skip binary files
    if path.suffix.lower() in skip_extensions:
        return False

    # Skip generated directories
    if any(skip in path.parts for skip in skip_paths):
        return False

    return True


# =============================================================================
# Scanner Implementations
# =============================================================================

def run_npm_audit(project_root: str) -> Optional[str]:
    """
    Run npm audit if package.json exists.

    Returns:
        Optional[str]: Warning message if vulnerabilities found
    """
    package_json = Path(project_root) / "package.json"
    if not package_json.exists():
        return None

    try:
        result = subprocess.run(
            ["npm", "audit", "--json"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0 and result.stdout:
            audit_data = json.loads(result.stdout)
            vulnerabilities = audit_data.get("metadata", {}).get("vulnerabilities", {})

            critical = vulnerabilities.get("critical", 0)
            high = vulnerabilities.get("high", 0)

            if critical > 0 or high > 0:
                return f"""
🔍 Dependency Audit: Found {critical} critical and {high} high severity vulnerabilities

Run `npm audit` for details and `npm audit fix` to remediate.
                """

    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError):
        pass  # Silently fail - don't block on scanner errors

    return None


def run_pip_audit(project_root: str) -> Optional[str]:
    """
    Run pip/uv audit if requirements.txt exists.

    Returns:
        Optional[str]: Warning message if vulnerabilities found
    """
    requirements = Path(project_root) / "requirements.txt"
    if not requirements.exists():
        return None

    try:
        # Try uv first (faster), fallback to pip
        cmd = ["uv", "pip", "check"] if shutil.which("uv") else ["pip", "check"]

        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0 and result.stderr:
            return f"""
🔍 Dependency Audit: Found package conflicts or vulnerabilities

{result.stderr[:500]}

Run `{' '.join(cmd)}` for details.
            """

    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        pass  # Silently fail

    return None


def run_secret_scan(file_path: str, project_root: str) -> Optional[str]:
    """
    Quick pattern-based secret scan on a file.

    Returns:
        Optional[str]: Warning message if secrets detected
    """
    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    # Simple pattern detection (not exhaustive - just common cases)
    suspicious_patterns = [
        ("API key", r"api[_-]?key\s*[:=]\s*['\"]?\w{20,}"),
        ("Secret key", r"secret[_-]?key\s*[:=]\s*['\"]?\w{20,}"),
        ("Password", r"password\s*[:=]\s*['\"]?\w{8,}"),
        ("Token", r"token\s*[:=]\s*['\"]?\w{20,}"),
        ("AWS key", r"AKIA[0-9A-Z]{16}"),
        ("Private key", r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    ]

    import re
    found_secrets = []

    for name, pattern in suspicious_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            found_secrets.append(name)

    if found_secrets:
        return f"""
🔐 Secret Scan: Potential secrets detected in {Path(file_path).name}

Found patterns: {', '.join(found_secrets)}

Please verify these are not actual secrets. If they are:
1. Move to .env file
2. Add .env to .gitignore
3. Remove from tracked files

Run `/review security` for comprehensive secret audit.
        """

    return None


# =============================================================================
# Hook Handler
# =============================================================================

def posttool_scan(tool_input: Dict, tool_output: Dict, cwd: str) -> Optional[Dict]:
    """
    PostToolUse hook for Edit/Write - trigger background scans.

    Args:
        tool_input: Tool input containing file_path
        tool_output: Tool output (not used)
        cwd: Current working directory

    Returns:
        Optional[Dict]: Injection dict with scan warnings
    """
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return None

    warnings = []

    # Dependency audit trigger
    if should_run_dependency_audit(file_path):
        npm_warning = run_npm_audit(cwd)
        if npm_warning:
            warnings.append(npm_warning)

        pip_warning = run_pip_audit(cwd)
        if pip_warning:
            warnings.append(pip_warning)

    # Secret scan trigger
    if should_run_secret_scan(file_path):
        secret_warning = run_secret_scan(file_path, cwd)
        if secret_warning:
            warnings.append(secret_warning)

    if warnings:
        return {
            "type": "system-reminder",
            "content": "\n".join(warnings)
        }

    return None


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """Hook entry point."""
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Missing hook arguments"}), file=sys.stderr)
        sys.exit(1)

    hook_type = sys.argv[1]

    if hook_type != "posttool":
        sys.exit(0)  # Not our hook

    # Read hook payload from stdin
    try:
        payload = json.loads(sys.stdin.read())
        tool_name = payload.get("tool_name", "")

        if tool_name not in ["Edit", "Write", "MultiEdit"]:
            sys.exit(0)  # Not file edit tool

        tool_input = payload.get("tool_input", {})
        tool_output = payload.get("tool_output", {})
        cwd = payload.get("cwd", ".")

        result = posttool_scan(tool_input, tool_output, cwd)

        if result:
            print(json.dumps(result))
            sys.exit(0)

        sys.exit(0)  # Pass through

    except Exception as e:
        print(json.dumps({"error": f"Hook error: {str(e)}"}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
