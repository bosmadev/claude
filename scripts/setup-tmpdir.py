#!/usr/bin/env python3
"""
Setup script for CLAUDE_CODE_TMPDIR (cross-platform)

Windows: Creates %TEMP%\\claude-tmp directory
Linux:   Mounts tmpfs at /mnt/claude-tmp (requires root)

Replaces: setup-tmpdir.sh
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def setup_windows():
    """Create a dedicated temp directory on Windows."""
    tmpdir = Path(tempfile.gettempdir()) / "claude-tmp"

    print(f"Setting up CLAUDE_CODE_TMPDIR at {tmpdir}...")

    if tmpdir.exists():
        print(f"Directory already exists: {tmpdir}")
    else:
        tmpdir.mkdir(parents=True, exist_ok=True)
        print(f"Created directory: {tmpdir}")

    print()
    print("Setup complete.")
    print()
    print("To use this directory, set the environment variable:")
    print()
    print(f'  $env:CLAUDE_CODE_TMPDIR = "{tmpdir}"')
    print()
    print("Or add it permanently (PowerShell):")
    print()
    print(f'  [System.Environment]::SetEnvironmentVariable("CLAUDE_CODE_TMPDIR", "{tmpdir}", "User")')
    print()
    print("Or set it in settings.json:")
    print()
    print(f'  "env": {{ "CLAUDE_CODE_TMPDIR": "{tmpdir}" }}')
    print()
    print("Restart Claude Code to use the new tmpdir.")


def setup_linux():
    """Mount tmpfs on Linux (requires root)."""
    tmpdir_path = "/mnt/claude-tmp"
    tmpdir_size = "512m"

    if os.getuid() != 0:
        print("ERROR: Linux tmpfs setup requires root. Run with sudo:")
        print(f"  sudo python {__file__}")
        sys.exit(1)

    print(f"Setting up CLAUDE_CODE_TMPDIR at {tmpdir_path}...")

    # Create mount point
    Path(tmpdir_path).mkdir(parents=True, exist_ok=True)

    # Check if already mounted
    result = subprocess.run(
        ["mountpoint", "-q", tmpdir_path],
        capture_output=True,
    )
    if result.returncode == 0:
        print(f"Already mounted at {tmpdir_path}")
    else:
        subprocess.run(
            ["mount", "-t", "tmpfs", "-o", f"size={tmpdir_size},mode=1777", "tmpfs", tmpdir_path],
            check=True,
        )
        print(f"Mounted tmpfs at {tmpdir_path}")

    # Add to fstab if not present
    fstab = Path("/etc/fstab")
    fstab_content = fstab.read_text() if fstab.exists() else ""
    if "claude-tmp" not in fstab_content:
        with open(fstab, "a") as f:
            f.write(f"tmpfs {tmpdir_path} tmpfs size={tmpdir_size},mode=1777 0 0\n")
        print("Added to /etc/fstab for persistence")
    else:
        print("Already in /etc/fstab")

    print()
    print("Setup complete. CLAUDE_CODE_TMPDIR is configured in settings.json")
    print("Restart Claude Code to use the new tmpdir.")


def main():
    if sys.platform == "win32":
        setup_windows()
    else:
        setup_linux()


if __name__ == "__main__":
    main()
