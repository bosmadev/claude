#!/usr/bin/env python3
"""Screenshot capture - cross-platform.

Linux: Uses Spectacle (KDE) for region selection.
Windows: Uses Snipping Tool / ms-screenclip URI scheme.
"""
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path

# Add parent directories to sys.path for compat import
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.compat import get_claude_home

# Dynamic screenshots directory
CLAUDE_HOME = get_claude_home()
SCREENSHOTS_DIR = CLAUDE_HOME / "skills" / "screen" / "screenshots"

def capture_screenshot(output_path: str) -> bool:
    if sys.platform == "win32":
        # Launch Windows Snipping Tool
        # ms-screenclip: launches the modern snip overlay
        subprocess.run(["cmd", "/c", "start", "ms-screenclip:"], check=False)
        print(f"Snipping Tool launched. Save screenshot to: {output_path}", file=sys.stderr)
        # Note: ms-screenclip saves to clipboard, not to file directly
        # The user must save manually or we can try to read clipboard
        return True
    else:
        # Linux: Use Spectacle
        result = subprocess.run(
            ["spectacle", "-b", "-r", "-n", "-o", output_path],
            capture_output=True
        )
        return result.returncode == 0

def main():
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    default_output = str(SCREENSHOTS_DIR / f"screen-{timestamp}.png")
    output_path = sys.argv[1] if len(sys.argv) > 1 else default_output

    if capture_screenshot(output_path):
        if Path(output_path).exists():
            print(output_path)
            sys.exit(0)
        else:
            # On Windows, the file may not exist yet (clipboard-based)
            print(output_path)
            sys.exit(0)
    else:
        print("Error: Screenshot capture failed or was cancelled", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
