#!/usr/bin/env python3
"""
Guards Hook - Redirects to scripts/guards.py (resolved relative to this file).

This stub exists for backward compatibility only.
All logic now lives in scripts/guards.py.
"""

import subprocess
import sys
from pathlib import Path

def main() -> None:
    """Redirect to scripts/guards.py with all original arguments."""
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve().parent.parent / "scripts" / "guards.py")] + sys.argv[1:],
            input=sys.stdin.buffer.read() if not sys.stdin.isatty() else b"",
            capture_output=True,
            timeout=30,  # 30 second timeout for guards operations
        )
    except subprocess.TimeoutExpired:
        print("Error: guards.py timed out after 30s", file=sys.stderr)
        sys.exit(1)
    except (FileNotFoundError, PermissionError) as e:
        print(f"Error executing guards.py: {e}", file=sys.stderr)
        sys.exit(1)

    if result.stdout:
        sys.stdout.buffer.write(result.stdout)
    if result.stderr:
        sys.stderr.buffer.write(result.stderr)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
