# Claude token check - runs once per session in background
# Add to your PowerShell profile ($PROFILE) to run on every login.
#
# Layer 3: Login hook for token refresh (Windows equivalent)
# Replaces: claude-login-hook.sh
#
# Install:
#   $claudeHome = Join-Path $env:USERPROFILE ".claude"
#   Add-Content $PROFILE ". `"$claudeHome\scripts\claude-login-hook.ps1`""

$claudeHome = if ($env:CLAUDE_HOME) { $env:CLAUDE_HOME } else { Join-Path $env:USERPROFILE ".claude" }
$marker = Join-Path $env:TEMP ".claude-token-checked-$PID"
if (-not (Test-Path $marker)) {
    New-Item $marker -ItemType File -Force | Out-Null
    Start-Job -ScriptBlock {
        param($claudePath)
        python "$claudePath\scripts\token-guard.py" check --quiet 2>$null
    } -ArgumentList $claudeHome | Out-Null
}
