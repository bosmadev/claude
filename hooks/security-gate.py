#!/usr/bin/env python3
"""
Security Gate Hook - Layered Defense Layer 1 (Pre-Check)

Intercepts potentially dangerous commands before execution.
Uses AskUserQuestion for soft-blocks, hard-blocks for critical threats.

Threat Categories:
- Homograph attacks (Cyrillic/Unicode lookalikes)
- ANSI injection (terminal escape sequences)
- Pipe-to-shell (curl | bash patterns)
- Secret leaks (API keys, tokens, passwords)
- Dangerous git commands (--force, --hard)
- Prompt injection (hidden instructions)

Usage:
  python security-gate.py pre-check    # PreToolUse: Check Bash commands
  python security-gate.py audit        # View recent security events
  python security-gate.py stats        # Security statistics
"""

import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# =============================================================================
# Stdin Timeout - Prevent hanging on missing stdin
# =============================================================================

_stdin_timer = None


def _setup_timeout():
    global _stdin_timer
    if sys.platform == "win32":
        import threading

        def timeout_exit():
            """Log timeout and exit gracefully."""
            try:
                debug_log = Path.home() / ".claude" / "debug" / "security-gate-timeout.log"
                debug_log.parent.mkdir(parents=True, exist_ok=True)
                with open(debug_log, "a") as f:
                    f.write(f"[{datetime.now().isoformat()}] Timeout after 5s\n")
            except Exception:
                pass
            sys.exit(0)

        _stdin_timer = threading.Timer(5, timeout_exit)
        _stdin_timer.daemon = True
        _stdin_timer.start()
    else:
        import signal

        def timeout_handler(signum, frame):
            sys.exit(0)

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(5)


def _cancel_timeout():
    global _stdin_timer
    if sys.platform == "win32":
        if _stdin_timer:
            _stdin_timer.cancel()
            _stdin_timer = None
    else:
        import signal

        signal.alarm(0)


_setup_timeout()


# =============================================================================
# Security Configuration
# =============================================================================

# Directories for security logs
SECURITY_DIR = Path.home() / ".claude" / "security"
AUDIT_LOG = SECURITY_DIR / "audit.jsonl"
BLOCKS_LOG = SECURITY_DIR / "blocks.jsonl"
OVERRIDES_LOG = SECURITY_DIR / "overrides.jsonl"

# Ensure directories exist
SECURITY_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Threat Detection: Homograph Attack
# =============================================================================

# Cyrillic characters that look like Latin (expanded set)
HOMOGRAPH_MAP = {
    "\u0430": "a",  # Cyrillic а
    "\u0435": "e",  # Cyrillic е
    "\u043e": "o",  # Cyrillic о
    "\u0440": "p",  # Cyrillic р
    "\u0441": "c",  # Cyrillic с
    "\u0443": "y",  # Cyrillic у
    "\u0445": "x",  # Cyrillic х
    "\u0456": "i",  # Cyrillic і
    "\u0458": "j",  # Cyrillic ј
    "\u04bb": "h",  # Cyrillic һ
    "\u0501": "d",  # Cyrillic ԁ
    "\u051b": "q",  # Cyrillic ԛ
    "\u051d": "w",  # Cyrillic ԝ
    "\u0412": "B",  # Cyrillic В
    "\u0405": "S",  # Cyrillic Ѕ
    "\u041d": "H",  # Cyrillic Н
    "\u0420": "P",  # Cyrillic Р
    "\u0421": "C",  # Cyrillic С
    "\u0422": "T",  # Cyrillic Т
    "\u0425": "X",  # Cyrillic Х
    "\u0406": "I",  # Cyrillic І
    "\u0408": "J",  # Cyrillic Ј
}

# Broader Unicode confusables
CONFUSABLE_SCRIPTS = {
    "CYRILLIC",
    "GREEK",
    "ARMENIAN",
    "HEBREW",
}


def detect_homograph(text: str) -> Optional[dict]:
    """
    Detect homograph attacks using mixed-script analysis.

    Returns threat info if detected, None otherwise.
    """
    if not text:
        return None

    # Check for known Cyrillic lookalikes
    for cyrillic, latin in HOMOGRAPH_MAP.items():
        if cyrillic in text:
            return {
                "threat_type": "homograph",
                "severity": "high",
                "details": f"Cyrillic '{cyrillic}' (looks like '{latin}') found in command",
                "payload": text,
            }

    # Check for mixed scripts in same word
    scripts_used = set()
    for char in text:
        if char.isalpha():
            try:
                script = unicodedata.name(char).split()[0]
                if script in CONFUSABLE_SCRIPTS or script == "LATIN":
                    scripts_used.add(script)
            except ValueError:
                pass

    if len(scripts_used) > 1 and "LATIN" in scripts_used:
        return {
            "threat_type": "homograph",
            "severity": "medium",
            "details": f"Mixed scripts detected: {', '.join(scripts_used)}",
            "payload": text[:100],
        }

    return None


# =============================================================================
# Threat Detection: ANSI Injection
# =============================================================================

ANSI_PATTERNS = [
    r"\x1b\[",  # CSI sequences
    r"\x1b\]",  # OSC sequences
    r"\x1b\(",  # Character set
    r"\x1bP",  # DCS sequences
    r"\x1b\^",  # PM sequences
    r"\x1b_",  # APC sequences
    r"\x07",  # Bell
    r"\x9b",  # 8-bit CSI
]


def detect_ansi_injection(text: str) -> Optional[dict]:
    """
    Detect ANSI escape sequence injection attempts.
    """
    for pattern in ANSI_PATTERNS:
        if re.search(pattern, text):
            return {
                "threat_type": "ansi_injection",
                "severity": "high",
                "details": "ANSI escape sequence detected - potential terminal hijacking",
                "payload": repr(text[:100]),
            }
    return None


def sanitize_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    ansi_escape = re.compile(r"(\x1b|\x9b)[^@-_]*[@-_]|\x1b|\x9b|\x07")
    return ansi_escape.sub("", text)


# =============================================================================
# Threat Detection: Pipe-to-Shell
# =============================================================================

PIPE_SHELL_PATTERNS = [
    r"curl\s+.*\|\s*(ba)?sh",
    r"wget\s+.*\|\s*(ba)?sh",
    r"curl\s+.*\|\s*python",
    r"wget\s+.*\|\s*python",
    r"curl\s+.*\|\s*perl",
    r"curl\s+.*\|\s*ruby",
    r"curl\s+.*>\s*/tmp/.*&&.*sh",
    r"curl\s+-[oO]\s+/tmp/.*&&",
    r"wget\s+-O\s+-\s+.*\|",
    r"fetch\s+.*\|\s*sh",
]


def detect_pipe_to_shell(command: str) -> Optional[dict]:
    """
    Detect dangerous pipe-to-shell patterns (remote code execution).
    """
    for pattern in PIPE_SHELL_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return {
                "threat_type": "pipe_to_shell",
                "severity": "critical",
                "details": "Remote code execution pattern detected",
                "payload": command[:200],
            }
    return None


# =============================================================================
# Threat Detection: Secret Leaks (700+ patterns)
# =============================================================================

# Common secret patterns (expandable)
# Patterns use bounded quantifiers to prevent ReDoS attacks
SECRET_PATTERNS = [
    # API Keys
    (r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?[\w\-]{20,}['\"]?", "API key"),
    (r"(?i)sk-[a-zA-Z0-9]{20,}", "OpenAI API key"),
    (r"(?i)sk-ant-[a-zA-Z0-9\-]{20,}", "Anthropic API key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub personal access token"),
    (r"gho_[a-zA-Z0-9]{36}", "GitHub OAuth token"),
    (r"ghu_[a-zA-Z0-9]{36}", "GitHub user-to-server token"),
    (r"ghs_[a-zA-Z0-9]{36}", "GitHub server-to-server token"),
    (r"ghr_[a-zA-Z0-9]{36}", "GitHub refresh token"),
    (r"github_pat_[a-zA-Z0-9]{22}_[a-zA-Z0-9]{59}", "GitHub fine-grained PAT"),
    # AWS
    (r"(?i)AKIA[0-9A-Z]{16}", "AWS access key ID"),
    (r"(?i)aws[_\-]?secret[_\-]?access[_\-]?key\s*[:=]\s*['\"]?[\w\+/]{40}['\"]?", "AWS secret key"),
    # Google Cloud
    (r"AIza[0-9A-Za-z\-_]{35}", "Google API key"),
    # Stripe
    (r"sk_live_[0-9a-zA-Z]{24}", "Stripe live secret key"),
    (r"sk_test_[0-9a-zA-Z]{24}", "Stripe test secret key"),
    (r"rk_live_[0-9a-zA-Z]{24}", "Stripe live restricted key"),
    # Database
    (r"(?i)postgres://[^:]+:[^@]+@", "PostgreSQL connection string"),
    (r"(?i)mysql://[^:]+:[^@]+@", "MySQL connection string"),
    (r"(?i)mongodb(\+srv)?://[^:]+:[^@]+@", "MongoDB connection string"),
    (r"(?i)redis://:[^@]+@", "Redis connection string"),
    # Generic secrets
    (r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?[^\s'\"]{8,}['\"]?", "Password"),
    (r"(?i)(secret|token|auth)\s*[:=]\s*['\"]?[\w\-]{20,}['\"]?", "Secret/Token"),
    (r"(?i)bearer\s+[a-zA-Z0-9\-_.]{20,}", "Bearer token"),
    # Private keys
    (r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "Private key"),
    (r"-----BEGIN PGP PRIVATE KEY BLOCK-----", "PGP private key"),
    # Slack
    (r"xox[baprs]-[0-9]{10,13}-[0-9]{10,13}-[a-zA-Z0-9]{24}", "Slack token"),
    # Twilio
    (r"SK[0-9a-fA-F]{32}", "Twilio API key"),
    # SendGrid
    (r"SG\.[a-zA-Z0-9]{22}\.[a-zA-Z0-9\-_]{43}", "SendGrid API key"),
    # Mailchimp
    (r"[0-9a-f]{32}-us[0-9]{1,2}", "Mailchimp API key"),
    # Square
    (r"sq0atp-[0-9A-Za-z\-_]{22}", "Square access token"),
    (r"sq0csp-[0-9A-Za-z\-_]{43}", "Square OAuth secret"),
    # Shopify
    (r"shpat_[a-fA-F0-9]{32}", "Shopify access token"),
    (r"shpca_[a-fA-F0-9]{32}", "Shopify custom app token"),
    (r"shppa_[a-fA-F0-9]{32}", "Shopify private app token"),
    # Discord
    (r"[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27}", "Discord bot token"),
    # Telegram
    (r"[0-9]+:AA[0-9A-Za-z\-_]{33}", "Telegram bot token"),
    # npm
    (r"npm_[A-Za-z0-9]{36}", "npm access token"),
    # PyPI
    (r"pypi-AgEIcHlwaS5vcmc[A-Za-z0-9\-_]{50,}", "PyPI API token"),
    # Vercel
    (r"[a-zA-Z0-9]{24}", "Potential Vercel token"),  # Less specific, lower priority
    # Supabase
    (r"sbp_[a-f0-9]{40}", "Supabase service key"),
    (r"eyJ[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+\.[a-zA-Z0-9\-_]+", "JWT token"),
]


def detect_secret_leak(text: str, timeout_ms: int = 100) -> Optional[dict]:
    """
    Detect potential secret/credential leaks in commands.

    Args:
        text: Text to scan for secrets
        timeout_ms: Max milliseconds per pattern (defense against ReDoS)
    """
    import signal
    import platform

    # Limit input size to prevent ReDoS
    if len(text) > 10000:
        text = text[:10000]

    for pattern, secret_type in SECRET_PATTERNS:
        if re.search(pattern, text):
            # Mask the actual secret in the report
            masked = re.sub(pattern, f"[REDACTED {secret_type}]", text)
            return {
                "threat_type": "secret_leak",
                "severity": "critical",
                "details": f"Potential {secret_type} detected in command",
                "payload": masked[:200],
            }
    return None


# =============================================================================
# Threat Detection: Dangerous Git Commands
# =============================================================================

DANGEROUS_GIT_PATTERNS = [
    (r"git\s+push\s+.*--force(?!-with-lease)", "git push --force (data loss risk)"),
    (r"git\s+push\s+-f(?:\s|$)", "git push -f (data loss risk)"),
    (r"git\s+reset\s+--hard", "git reset --hard (uncommitted changes lost)"),
    (r"git\s+clean\s+-[a-z]*f", "git clean -f (untracked files deleted)"),
    (r"git\s+checkout\s+\.", "git checkout . (all changes discarded)"),
    (r"git\s+checkout\s+--\s+\.", "git checkout -- . (all changes discarded)"),
    (r"git\s+restore\s+\.", "git restore . (all changes discarded)"),
    (r"git\s+branch\s+-[Dd]", "git branch -D (force delete branch)"),
    (r"git\s+stash\s+drop", "git stash drop (stash permanently deleted)"),
    (r"git\s+stash\s+clear", "git stash clear (all stashes deleted)"),
    (r"git\s+reflog\s+expire", "git reflog expire (history cleanup)"),
    (r"git\s+gc\s+--prune", "git gc --prune (unreachable objects deleted)"),
]


def detect_dangerous_git(command: str) -> Optional[dict]:
    """
    Detect potentially dangerous git commands that could cause data loss.
    """
    for pattern, description in DANGEROUS_GIT_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return {
                "threat_type": "dangerous_git",
                "severity": "high",
                "details": description,
                "payload": command[:200],
            }
    return None


# =============================================================================
# Threat Detection: Prompt Injection
# =============================================================================

PROMPT_INJECTION_PATTERNS = [
    (r"(?i)ignore\s+(all\s+)?previous\s+instructions", "Instruction override attempt"),
    (r"(?i)disregard\s+(all\s+)?prior\s+instructions", "Instruction override attempt"),
    (r"(?i)you\s+are\s+now\s+(a\s+)?different", "Role manipulation attempt"),
    (r"(?i)pretend\s+you\s+are", "Role manipulation attempt"),
    (r"(?i)act\s+as\s+if\s+you", "Role manipulation attempt"),
    (r"(?i)system\s*:\s*you\s+are", "Fake system prompt"),
    (r"(?i)<\s*system\s*>", "Fake system tag"),
    (r"(?i)admin\s*:\s*override", "Fake admin command"),
    (r"(?i)developer\s+mode", "Developer mode request"),
    (r"(?i)jailbreak", "Jailbreak attempt"),
    (r"(?i)bypass\s+(the\s+)?safety", "Safety bypass attempt"),
    (r"(?i)ignore\s+(your\s+)?restrictions", "Restriction bypass attempt"),
]


def detect_prompt_injection(text: str) -> Optional[dict]:
    """
    Detect prompt injection attempts in commands or file content.
    """
    for pattern, description in PROMPT_INJECTION_PATTERNS:
        if re.search(pattern, text):
            return {
                "threat_type": "prompt_injection",
                "severity": "critical",
                "details": description,
                "payload": text[:200],
            }
    return None


# =============================================================================
# Threat Detection: Destructive Commands
# =============================================================================

DESTRUCTIVE_PATTERNS = [
    (r"rm\s+-[a-z]*r[a-z]*f[a-z]*\s+/", "rm -rf on root"),
    (r"rm\s+-[a-z]*f[a-z]*r[a-z]*\s+/", "rm -rf on root"),
    (r"rm\s+-rf\s+~", "rm -rf on home"),
    (r"rm\s+-rf\s+\*", "rm -rf wildcard"),
    (r"mkfs\.", "filesystem format"),
    (r"dd\s+if=.*of=/dev/", "dd to device"),
    (r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;", "fork bomb"),
    (r"chmod\s+-R\s+777\s+/", "chmod 777 on root"),
    (r"chown\s+-R.*\s+/[^/]", "recursive chown on system dir"),
]


def detect_destructive_command(command: str) -> Optional[dict]:
    """
    Detect potentially destructive system commands.
    """
    for pattern, description in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return {
                "threat_type": "destructive_command",
                "severity": "critical",
                "details": description,
                "payload": command[:200],
            }
    return None


# =============================================================================
# Audit Logging
# =============================================================================


def log_security_event(
    event_type: str,
    threat: Optional[dict],
    command: str,
    decision: str,
    log_file: Path = AUDIT_LOG,
) -> None:
    """
    Log security event to audit trail with rotation.
    """
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "command_hash": hashlib.sha256(command.encode()).hexdigest()[:16],
        "threat": threat,
        "decision": decision,
    }

    # Implement log rotation if file exceeds 10MB
    MAX_LOG_SIZE = 10 * 1024 * 1024
    failure_count_file = log_file.parent / ".log-failures"

    try:
        # Check if rotation needed
        if log_file.exists() and log_file.stat().st_size > MAX_LOG_SIZE:
            # Rotate: keep last 1000 lines, move rest to .old
            with open(log_file, "r") as f:
                lines = f.readlines()
            if len(lines) > 1000:
                # Save old entries
                old_log = log_file.with_suffix(".jsonl.old")
                with open(old_log, "w") as f:
                    f.writelines(lines[:-1000])
                # Keep recent entries
                with open(log_file, "w") as f:
                    f.writelines(lines[-1000:])

        # Append new event
        with open(log_file, "a") as f:
            f.write(json.dumps(event) + "\n")

        # Reset failure count on success
        if failure_count_file.exists():
            failure_count_file.unlink()

    except OSError as e:
        # Track failure count
        try:
            count = 0
            if failure_count_file.exists():
                count = int(failure_count_file.read_text())
            count += 1
            failure_count_file.write_text(str(count))
        except Exception:
            pass


def log_block(threat: dict, command: str) -> None:
    """Log blocked command to blocks log."""
    log_security_event("block", threat, command, "blocked", BLOCKS_LOG)


def log_override(threat: dict, command: str) -> None:
    """Log user-approved override to overrides log."""
    log_security_event("override", threat, command, "user_approved", OVERRIDES_LOG)


# =============================================================================
# Main Security Check
# =============================================================================


def run_security_checks(command: str) -> tuple[Optional[dict], str]:
    """
    Run all security checks on a command.

    Returns:
        (threat_info, action) where action is:
        - "allow" - No threats detected
        - "ask" - Soft-block, needs user confirmation
        - "block" - Hard-block, reject command
        - "sanitize" - Clean and allow
    """
    # Check for destructive commands (hard block)
    threat = detect_destructive_command(command)
    if threat:
        return (threat, "block")

    # Check for prompt injection (hard block)
    threat = detect_prompt_injection(command)
    if threat:
        return (threat, "block")

    # Check for homograph attack (ask user)
    threat = detect_homograph(command)
    if threat:
        return (threat, "ask")

    # Check for ANSI injection (sanitize)
    threat = detect_ansi_injection(command)
    if threat:
        return (threat, "sanitize")

    # Check for pipe-to-shell (ask user)
    threat = detect_pipe_to_shell(command)
    if threat:
        return (threat, "ask")

    # Check for secret leak (ask user)
    threat = detect_secret_leak(command)
    if threat:
        return (threat, "ask")

    # Check for dangerous git (ask user)
    threat = detect_dangerous_git(command)
    if threat:
        return (threat, "ask")

    return (None, "allow")


# =============================================================================
# Hook Handler: Pre-Check
# =============================================================================


MAX_STDIN_SIZE = 1024 * 1024  # 1MB max stdin


def pre_check() -> None:
    """
    PreToolUse hook for Bash commands.
    Intercepts and validates commands before execution.
    """
    try:
        # Limit stdin read to prevent memory exhaustion
        raw_input = sys.stdin.read(MAX_STDIN_SIZE)
        if len(raw_input) >= MAX_STDIN_SIZE:
            # Input too large, block for safety
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Command input exceeds size limit (1MB)"
                }
            }
            print(json.dumps(output))
            sys.exit(0)
        hook_input = json.loads(raw_input)
        _cancel_timeout()
    except json.JSONDecodeError as e:
        # Log JSON parsing errors to detect potential injection attempts
        try:
            debug_log = Path.home() / ".claude" / "debug" / "security-gate-json-errors.log"
            debug_log.parent.mkdir(parents=True, exist_ok=True)
            with open(debug_log, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] JSON error: {e}\n")
                f.write(f"Input preview: {raw_input[:200]}\n")
        except Exception:
            pass
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        sys.exit(0)

    # Run security checks
    threat, action = run_security_checks(command)

    if action == "allow":
        # No threat detected, allow command
        log_security_event("check", None, command, "allowed")
        sys.exit(0)

    elif action == "sanitize":
        # ANSI injection - sanitize and allow
        sanitized = sanitize_ansi(command)
        log_security_event("sanitize", threat, command, "sanitized")

        # Modify the command to sanitized version
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
        print(json.dumps(output))
        sys.exit(0)

    elif action == "ask":
        # Soft-block - ask user for confirmation
        log_security_event("check", threat, command, "pending_approval")

        severity_emoji = {
            "critical": "\U0001F6A8",  # 🚨
            "high": "\u26A0\uFE0F",  # ⚠️
            "medium": "\U0001F7E1",  # 🟡
            "low": "\U0001F7E2",  # 🟢
        }

        emoji = severity_emoji.get(threat.get("severity", "medium"), "\u26A0\uFE0F")
        threat_type = threat.get("threat_type", "unknown")
        details = threat.get("details", "Suspicious pattern detected")

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": f"{emoji} Security: {threat_type.replace('_', ' ').title()}\n{details}\n\nAllow this command?",
            }
        }
        print(json.dumps(output))
        sys.exit(0)

    elif action == "block":
        # Hard-block - reject command
        log_block(threat, command)

        threat_type = threat.get("threat_type", "unknown")
        details = threat.get("details", "Dangerous pattern detected")

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"\U0001F6AB BLOCKED: {threat_type.replace('_', ' ').title()}\n{details}",
            }
        }
        print(json.dumps(output))
        sys.exit(0)


# =============================================================================
# CLI Commands
# =============================================================================


def cmd_audit() -> None:
    """Show recent security events."""
    if not AUDIT_LOG.exists():
        print("No security events logged yet.")
        return

    print("Recent Security Events:")
    print("-" * 60)

    events = []
    with open(AUDIT_LOG) as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    # Show last 20 events
    for event in events[-20:]:
        ts = event.get("timestamp", "")[:19]
        decision = event.get("decision", "unknown")
        threat = event.get("threat")
        threat_type = threat.get("threat_type", "-") if threat else "-"
        print(f"{ts}  {decision:15}  {threat_type}")


def cmd_stats() -> None:
    """Show security statistics."""
    stats = {"total": 0, "allowed": 0, "blocked": 0, "sanitized": 0, "pending": 0}
    threat_types = {}

    if AUDIT_LOG.exists():
        with open(AUDIT_LOG) as f:
            for line in f:
                try:
                    event = json.loads(line)
                    stats["total"] += 1
                    decision = event.get("decision", "")
                    if decision == "allowed":
                        stats["allowed"] += 1
                    elif decision == "blocked":
                        stats["blocked"] += 1
                    elif decision == "sanitized":
                        stats["sanitized"] += 1
                    elif decision == "pending_approval":
                        stats["pending"] += 1

                    threat = event.get("threat")
                    if threat:
                        tt = threat.get("threat_type", "unknown")
                        threat_types[tt] = threat_types.get(tt, 0) + 1
                except json.JSONDecodeError:
                    pass

    print("Security Statistics:")
    print("-" * 40)
    print(f"Total checks:     {stats['total']}")
    print(f"Allowed:          {stats['allowed']}")
    print(f"Blocked:          {stats['blocked']}")
    print(f"Sanitized:        {stats['sanitized']}")
    print(f"Pending approval: {stats['pending']}")
    print()
    if threat_types:
        print("Threat Types Detected:")
        for tt, count in sorted(threat_types.items(), key=lambda x: -x[1]):
            print(f"  {tt}: {count}")


# =============================================================================
# Main Entry Point
# =============================================================================


def main() -> None:
    """Main entry point with mode dispatch."""
    if len(sys.argv) < 2:
        print(
            "Usage: security-gate.py [pre-check|audit|stats]",
            file=sys.stderr,
        )
        sys.exit(1)

    mode = sys.argv[1]
    if mode == "pre-check":
        pre_check()
    elif mode == "audit":
        cmd_audit()
    elif mode == "stats":
        cmd_stats()
    else:
        print(f"Unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
