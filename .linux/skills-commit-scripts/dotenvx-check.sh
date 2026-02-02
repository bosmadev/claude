#!/usr/bin/env bash
# dotenvx-check.sh - Check and run dotenvx encryption before commit
# Part of /commit skill workflow
#
# Exit codes:
#   0 - Success (encryption ran or not needed)
#   1 - Failure (encryption failed)
#
# Usage: dotenvx-check.sh [project-dir]

set -euo pipefail

PROJECT_DIR="${1:-.}"
cd "$PROJECT_DIR"

# Check if package.json exists
if [[ ! -f "package.json" ]]; then
    echo "DOTENVX_STATUS: no_package_json"
    exit 0
fi

# Check if env:encrypt script exists in package.json
if command -v jq &>/dev/null; then
    # Use jq if available (more reliable)
    HAS_ENCRYPT=$(jq -r '.scripts["env:encrypt"] // empty' package.json 2>/dev/null)
else
    # Fall back to grep
    HAS_ENCRYPT=$(grep -o '"env:encrypt"' package.json 2>/dev/null || true)
fi

if [[ -z "$HAS_ENCRYPT" ]]; then
    echo "DOTENVX_STATUS: no_encrypt_script"
    exit 0
fi

# Check if there are any .env files that might need encryption
# Look for unencrypted .env files (not .env.vault or .env.keys)
UNENCRYPTED_ENV_FILES=$(find . -maxdepth 2 -name ".env*" \
    ! -name ".env.vault" \
    ! -name ".env.keys" \
    ! -name ".env*.example" \
    -type f 2>/dev/null | head -5)

if [[ -z "$UNENCRYPTED_ENV_FILES" ]]; then
    echo "DOTENVX_STATUS: no_env_files"
    exit 0
fi

echo "DOTENVX_STATUS: running_encryption"
echo "DOTENVX_FILES: Found .env files that may need encryption"

# Run the encryption
if pnpm env:encrypt 2>&1; then
    echo "DOTENVX_STATUS: encryption_success"

    # Check if .env.vault was modified
    if [[ -f ".env.vault" ]]; then
        if git diff --quiet .env.vault 2>/dev/null; then
            echo "DOTENVX_VAULT: unchanged"
        else
            echo "DOTENVX_VAULT: modified"
            echo "DOTENVX_ACTION: Stage .env.vault for commit"
        fi
    fi

    exit 0
else
    echo "DOTENVX_STATUS: encryption_failed"
    echo "DOTENVX_ERROR: pnpm env:encrypt command failed"
    exit 1
fi
