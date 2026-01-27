#!/usr/bin/env bash
# Screenshot capture using Spectacle region mode
# Usage: capture.sh [output_path]

set -euo pipefail

SCREENSHOTS_DIR="/usr/share/claude/skills/screen/screenshots"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
DEFAULT_OUTPUT="${SCREENSHOTS_DIR}/screen-${TIMESTAMP}.png"
OUTPUT_PATH="${1:-$DEFAULT_OUTPUT}"

# Ensure screenshots directory exists
mkdir -p "$SCREENSHOTS_DIR"

# Capture region screenshot using Spectacle
# -b: background mode (no GUI after capture)
# -r: region selection mode
# -n: no notification
# -o: output file path
if spectacle -b -r -n -o "$OUTPUT_PATH" 2>/dev/null; then
    # Verify file was created
    if [[ -f "$OUTPUT_PATH" ]]; then
        echo "$OUTPUT_PATH"
        exit 0
    else
        echo "Error: Screenshot file was not created" >&2
        exit 1
    fi
else
    echo "Error: Screenshot capture failed or was cancelled" >&2
    exit 1
fi
