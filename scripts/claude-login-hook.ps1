# Claude token check - runs once per session in background
# Add to your PowerShell profile ($PROFILE) to run on every login.
#
# Layer 3: Login hook for token refresh (Windows equivalent)
# Replaces: claude-login-hook.sh
#
# Install:
#   Add-Content $PROFILE '. "~/.claude\scripts\claude-login-hook.ps1"'

$marker = Join-Path $env:TEMP ".claude-token-checked-$PID"
if (-not (Test-Path $marker)) {
    New-Item $marker -ItemType File -Force | Out-Null
    Start-Job -ScriptBlock {
        python "~/.claude\scripts\token-guard.py" check --quiet 2>$null
    } | Out-Null
}
