#!/usr/bin/env python3
"""
Install Claude token refresh scheduled task/timer (cross-platform)

Windows: Creates Windows Task Scheduler tasks
Linux:   Installs systemd timer units (original behavior)

Replaces: install-token-timer.sh
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# ANSI colors
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"

TASK_NAME_REFRESH = "ClaudeTokenRefresh"
TASK_NAME_RESUME = "ClaudeTokenResume"
REFRESH_SCRIPT = SCRIPT_DIR / "refresh-claude-token.py"


def print_header():
    print("Claude Token Refresh Timer Installer")
    print("=====================================")
    print()


def find_python() -> str:
    """Return the path to the current Python executable."""
    return sys.executable


# ---------------------------------------------------------------------------
# Windows: Task Scheduler
# ---------------------------------------------------------------------------

def windows_install():
    """Install scheduled tasks on Windows using Task Scheduler."""
    python_exe = find_python()
    script_path = str(REFRESH_SCRIPT)

    # Integrity check: verify paths are within expected locations
    python_path = Path(python_exe).resolve()
    script_full = Path(script_path).resolve()

    # Verify script is within .claude directory
    claude_dir = Path.home() / ".claude"
    if not str(script_full).startswith(str(claude_dir)):
        print(f"  {RED}FAIL{RESET} Script path not within ~/.claude: {script_full}")
        sys.exit(1)

    # Verify script exists and is a file (not a symlink to outside)
    if script_full.is_symlink():
        real_target = script_full.resolve()
        if not str(real_target).startswith(str(claude_dir)):
            print(f"  {RED}FAIL{RESET} Script symlink points outside ~/.claude")
            sys.exit(1)

    print(f"Platform: {GREEN}Windows{RESET}")
    print(f"Python:   {CYAN}{python_exe}{RESET}")
    print(f"Script:   {CYAN}{script_path}{RESET}")
    print()

    # --- Task 1: 30-minute recurring refresh ---
    print("Creating 30-minute recurring task...")
    try:
        result = subprocess.run(
            [
                "schtasks", "/create",
                "/tn", TASK_NAME_REFRESH,
                "/sc", "MINUTE",
                "/mo", "30",
                "/tr", f'"{python_exe}" "{script_path}" --sync',
                "/f",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"  {GREEN}OK{RESET} {TASK_NAME_REFRESH} (every 30 min)")
        else:
            print(f"  {RED}FAIL{RESET} {TASK_NAME_REFRESH}: {result.stderr.strip()}")
    except FileNotFoundError:
        print(f"  {RED}FAIL{RESET} schtasks not found")

    # --- Task 2: Power resume / startup trigger ---
    print("Creating startup/resume trigger task...")
    import base64

    # Use -EncodedCommand to prevent injection via paths with special characters
    ps_script = f'''
$action = New-ScheduledTaskAction -Execute "{python_exe}" -Argument '"{script_path}" --sync'
$triggerStartup = New-ScheduledTaskTrigger -AtStartup
# Event trigger for resume from sleep (Event ID 1, Power-Troubleshooter)
$CIMTriggerClass = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
$triggerResume = New-CimInstance -CimClass $CIMTriggerClass -ClientOnly
$triggerResume.Subscription = '<QueryList><Query Id="0" Path="System"><Select Path="System">*[System[Provider[@Name="Microsoft-Windows-Power-Troubleshooter"] and EventID=1]]</Select></Query></QueryList>'
$triggerResume.Enabled = $true
$triggerResume.Delay = 'PT10S'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName "{TASK_NAME_RESUME}" -Action $action -Trigger @($triggerStartup, $triggerResume) -Settings $settings -Force -Description "Refresh Claude OAuth token on startup/resume"
'''
    try:
        # Encode to Base64 for -EncodedCommand (UTF-16LE required)
        encoded_cmd = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded_cmd],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"  {GREEN}OK{RESET} {TASK_NAME_RESUME} (on startup + resume from sleep)")
        else:
            print(f"  {RED}FAIL{RESET} {TASK_NAME_RESUME}: {result.stderr.strip()}")
    except FileNotFoundError:
        print(f"  {RED}FAIL{RESET} PowerShell not found")

    # --- Verify ---
    print()
    print("Verifying installation...")
    windows_verify()


def windows_verify():
    """Verify Windows scheduled tasks exist."""
    for name in [TASK_NAME_REFRESH, TASK_NAME_RESUME]:
        try:
            result = subprocess.run(
                ["schtasks", "/query", "/tn", name, "/fo", "LIST"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"  {GREEN}OK{RESET} {name} is registered")
                # Extract next run time from output
                for line in result.stdout.splitlines():
                    if "Next Run Time" in line:
                        print(f"       {line.strip()}")
                        break
            else:
                print(f"  {RED}MISSING{RESET} {name}")
        except FileNotFoundError:
            print(f"  {YELLOW}SKIP{RESET} Cannot query (schtasks not found)")

    print()
    print("Useful commands:")
    print(f'  schtasks /query /tn "{TASK_NAME_REFRESH}" /v   # Check task details')
    print(f'  schtasks /run   /tn "{TASK_NAME_REFRESH}"      # Manual trigger')
    print(f'  schtasks /delete /tn "{TASK_NAME_REFRESH}" /f  # Remove task')


def windows_uninstall():
    """Remove Windows scheduled tasks."""
    for name in [TASK_NAME_REFRESH, TASK_NAME_RESUME]:
        try:
            result = subprocess.run(
                ["schtasks", "/delete", "/tn", name, "/f"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"  {GREEN}OK{RESET} Removed {name}")
            else:
                print(f"  {YELLOW}SKIP{RESET} {name} not found")
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Linux: systemd
# ---------------------------------------------------------------------------

def linux_install():
    """Install systemd timer units on Linux (original behavior)."""
    systemd_dir = SCRIPT_DIR.parent / "systemd"
    is_root = os.getuid() == 0

    if is_root:
        mode = "system"
        unit_dir = Path("/etc/systemd/system")
        systemctl = ["systemctl"]
    else:
        mode = "user"
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        systemctl = ["systemctl", "--user"]

    print(f"Installing as: {GREEN}{mode} service{RESET}")
    print()

    unit_dir.mkdir(parents=True, exist_ok=True)

    # Stop existing timers
    print("Stopping existing timers...")
    for unit in ["claude-token-refresh.timer", "claude-token-resume.service"]:
        subprocess.run([*systemctl, "stop", unit], capture_output=True)

    # Copy unit files
    print("Installing unit files...")
    for unit_file in ["claude-token-refresh.timer", "claude-token-refresh.service", "claude-token-resume.service"]:
        src = systemd_dir / unit_file
        dst = unit_dir / unit_file
        if src.exists():
            dst.write_text(src.read_text())
            print(f"  {GREEN}OK{RESET} {unit_file}")
        else:
            print(f"  {YELLOW}SKIP{RESET} {unit_file} (not found)")

    # Reload and enable
    print()
    print("Reloading systemd...")
    subprocess.run([*systemctl, "daemon-reload"], capture_output=True)

    print("Enabling services...")
    subprocess.run([*systemctl, "enable", "claude-token-refresh.timer"], capture_output=True)
    subprocess.run([*systemctl, "enable", "claude-token-resume.service"], capture_output=True)

    print("Starting timer...")
    subprocess.run([*systemctl, "start", "claude-token-refresh.timer"], capture_output=True)

    # Verify
    print()
    print("Verifying installation...")
    result = subprocess.run(
        [*systemctl, "is-active", "claude-token-refresh.timer"],
        capture_output=True, text=True,
    )
    if result.stdout.strip() == "active":
        print(f"  {GREEN}OK{RESET} Timer is active")
    else:
        print(f"  {RED}FAIL{RESET} Timer failed to start")

    result = subprocess.run(
        [*systemctl, "is-enabled", "claude-token-resume.service"],
        capture_output=True, text=True,
    )
    if result.stdout.strip() == "enabled":
        print(f"  {GREEN}OK{RESET} Resume hook enabled")
    else:
        print(f"  {YELLOW}WARN{RESET} Resume hook not enabled")

    sc = " ".join(systemctl)
    print()
    print("Useful commands:")
    print(f"  {sc} status claude-token-refresh.timer   # Check timer status")
    print(f"  {sc} list-timers --all                    # List all timers")
    print(f"  journalctl -u claude-token-refresh.service # View logs")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print_header()

    action = "install"
    if len(sys.argv) > 1:
        if sys.argv[1] in ("uninstall", "remove"):
            action = "uninstall"
        elif sys.argv[1] in ("verify", "status", "check"):
            action = "verify"
        elif sys.argv[1] in ("help", "--help", "-h"):
            print("Usage: install-token-timer.py [install|uninstall|verify|help]")
            print()
            print("  install    Install scheduled task/timer (default)")
            print("  uninstall  Remove scheduled task/timer")
            print("  verify     Check if task/timer is installed")
            print("  help       Show this message")
            sys.exit(0)

    if sys.platform == "win32":
        if action == "uninstall":
            windows_uninstall()
        elif action == "verify":
            windows_verify()
        else:
            windows_install()
    else:
        if action == "uninstall":
            print(f"{YELLOW}Use systemctl to manage units on Linux{RESET}")
        elif action == "verify":
            print("Use: systemctl status claude-token-refresh.timer")
        else:
            linux_install()

    if action == "install":
        print()
        print("Installation complete!")


if __name__ == "__main__":
    main()
