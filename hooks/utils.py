#!/usr/bin/env python3
"""Desktop Utilities Hook - Focus and notification handlers.

Cross-platform replacement for utils.sh. Supports Windows (ctypes/PowerShell)
and Linux (wmctrl/xdotool/notify-send/paplay).

Usage:
    utils.py focus [cwd]   # Focus appropriate window
    utils.py notify        # Show notification with sound (reads JSON from stdin)
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import threading

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
IS_WIN = sys.platform == "win32"

if IS_WIN:
    import ctypes
    import ctypes.wintypes

    try:
        import winsound
    except ImportError:
        winsound = None  # type: ignore[assignment]


# ===========================================================================
# Windows helpers
# ===========================================================================

def _win_find_window_by_title(pattern: str) -> int | None:
    """Find a window handle whose title contains *pattern* (case-insensitive)."""
    pattern_lower = pattern.lower()
    result: list[int] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.wintypes.BOOL,
        ctypes.wintypes.HWND,
        ctypes.wintypes.LPARAM,
    )

    def enum_cb(hwnd: int, _lparam: int) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        if pattern_lower in buf.value.lower():
            result.append(hwnd)
            return False  # stop enumeration
        return True

    ctypes.windll.user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    return result[0] if result else None


def _win_activate_window(hwnd: int) -> bool:
    """Bring a window to the foreground on Windows."""
    user32 = ctypes.windll.user32
    # If the window is minimized, restore it first
    SW_RESTORE = 9
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    return True


def _win_focus_window(pattern: str) -> bool:
    """Find and activate a window by partial title match (Windows)."""
    hwnd = _win_find_window_by_title(pattern)
    if hwnd:
        return _win_activate_window(hwnd)
    return False


# ===========================================================================
# Linux helpers
# ===========================================================================

def _has_command(name: str) -> bool:
    return shutil.which(name) is not None


def _linux_focus_wmctrl(pattern: str) -> bool:
    """Try to focus a window via wmctrl."""
    if not _has_command("wmctrl"):
        return False
    try:
        out = subprocess.check_output(["wmctrl", "-l"], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            if pattern.lower() in line.lower():
                window_id = line.split()[0]
                subprocess.run(["wmctrl", "-i", "-a", window_id], check=True, stderr=subprocess.DEVNULL)
                return True
    except (subprocess.CalledProcessError, IndexError, OSError):
        pass
    return False


def _linux_focus_xdotool(pattern: str) -> bool:
    """Try to focus a window via xdotool."""
    if not _has_command("xdotool"):
        return False
    try:
        out = subprocess.check_output(
            ["xdotool", "search", "--name", pattern],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        wid = out.strip().splitlines()[0]
        if wid:
            subprocess.run(["xdotool", "windowactivate", wid], check=True, stderr=subprocess.DEVNULL)
            return True
    except (subprocess.CalledProcessError, IndexError, OSError):
        pass
    return False


def _linux_focus_window(pattern: str) -> bool:
    """Focus a window on Linux (wmctrl then xdotool fallback)."""
    return _linux_focus_wmctrl(pattern) or _linux_focus_xdotool(pattern)


def _linux_focus_code_insiders() -> bool:
    """Focus VS Code Insiders via class name on Linux."""
    if _linux_focus_wmctrl("Visual Studio Code - Insiders"):
        return True
    if _has_command("xdotool"):
        try:
            out = subprocess.check_output(
                ["xdotool", "search", "--class", "code-insiders"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            wid = out.strip().splitlines()[0]
            if wid:
                subprocess.run(["xdotool", "windowactivate", wid], check=True, stderr=subprocess.DEVNULL)
                return True
        except (subprocess.CalledProcessError, IndexError, OSError):
            pass
    return False


# ===========================================================================
# Focus mode
# ===========================================================================

def _focus_window(pattern: str) -> bool:
    """Cross-platform focus by title pattern."""
    if IS_WIN:
        return _win_focus_window(pattern)
    return _linux_focus_window(pattern)


def _focus_code_insiders(cwd: str) -> bool:
    """Focus VS Code Insiders."""
    if IS_WIN:
        return _win_focus_window("Visual Studio Code - Insiders")
    return _linux_focus_code_insiders()


def do_focus(cwd: str | None = None) -> None:
    """Focus the appropriate editor/window, with platform-aware priority."""
    if cwd is None:
        cwd = os.environ.get("HOME") or os.environ.get("USERPROFILE") or "."

    if IS_WIN:
        # Windows priority: VS Code Insiders > VS Code > "claude" > Windows Terminal > Explorer
        if _focus_code_insiders(cwd):
            return
        if _focus_window("Visual Studio Code"):
            return
        if _focus_window("claude"):
            return
        if _focus_window("Windows Terminal"):
            return
        if _focus_window("Explorer"):
            return

        # Fallback: launch an editor / terminal
        if shutil.which("code-insiders"):
            subprocess.Popen(["code-insiders", "."], cwd=cwd, creationflags=subprocess.DETACHED_PROCESS)
        elif shutil.which("wt"):
            subprocess.Popen(["wt", "-d", cwd], creationflags=subprocess.DETACHED_PROCESS)
        else:
            subprocess.Popen(["explorer", cwd], creationflags=subprocess.DETACHED_PROCESS)
    else:
        # Linux priority: code-insiders > Kate > claude > Dolphin
        if _focus_code_insiders(cwd):
            return
        if _focus_window("Kate"):
            return
        if _focus_window("claude"):
            return
        if _focus_window("Dolphin"):
            return

        # Fallback: launch an editor / terminal
        if _has_command("kate"):
            subprocess.Popen(["kate", cwd])
        elif _has_command("code-insiders"):
            subprocess.Popen(["code-insiders", "."], cwd=cwd)
        else:
            subprocess.Popen(["konsole", "--workdir", cwd])


# ===========================================================================
# Notify mode
# ===========================================================================

def _read_stdin_with_timeout(timeout_seconds: int = 5) -> str:
    """Read all of stdin with a timeout to prevent hanging."""
    result: list[str] = []
    done = threading.Event()

    def reader():
        try:
            result.append(sys.stdin.read())
        except Exception:
            result.append("{}")
        finally:
            done.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    done.wait(timeout=timeout_seconds)
    return result[0] if result else "{}"


def _notification_params(notification_type: str) -> tuple[str, str, str]:
    """Return (title, icon, urgency) based on notification type."""
    if notification_type == "permission_prompt":
        return ("Claude Needs Permission", "dialog-password", "critical")
    if notification_type == "idle_prompt":
        return ("Claude Waiting for Input", "dialog-question", "normal")
    if notification_type == "elicitation_dialog":
        return ("Claude Needs Input", "dialog-information", "normal")
    return ("Claude Code", "dialog-information", "normal")


def _win_play_sound() -> None:
    """Play a notification beep on Windows."""
    if winsound is not None:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass


def _win_show_notification(title: str, message: str) -> None:
    """Show a toast / balloon notification on Windows via PowerShell."""
    # Escape single quotes for PowerShell
    safe_title = title.replace("'", "''").replace('"', '`"')
    safe_message = message.replace("'", "''").replace('"', '`"')

    ps_script = (
        "[void][System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms');"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information;"
        "$n.BalloonTipTitle = '{title}';"
        "$n.BalloonTipText = '{msg}';"
        "$n.BalloonTipIcon = 'Info';"
        "$n.Visible = $true;"
        "$n.ShowBalloonTip(5000);"
        "Start-Sleep -Milliseconds 5100;"
        "$n.Dispose()"
    ).format(title=safe_title, msg=safe_message)

    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", ps_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS,
        )
    except OSError:
        pass


def _linux_play_sound() -> None:
    """Play a notification sound on Linux."""
    sound_file = "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga"
    if _has_command("paplay") and os.path.isfile(sound_file):
        try:
            subprocess.Popen(
                ["paplay", sound_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass


def _linux_show_notification(title: str, message: str, icon: str, urgency: str) -> None:
    """Show a desktop notification on Linux via notify-send."""
    if not _has_command("notify-send"):
        return
    try:
        subprocess.Popen(
            [
                "notify-send",
                f"--urgency={urgency}",
                f"--icon={icon}",
                "--app-name=Claude Code",
                title,
                message,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def do_notify() -> None:
    """Read notification JSON from stdin, play sound, show notification."""
    raw = _read_stdin_with_timeout(5)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}

    notification_type = data.get("notification_type", "unknown")
    message = data.get("message", "Claude needs your attention")
    cwd = data.get("cwd", os.environ.get("HOME") or os.environ.get("USERPROFILE") or ".")
    # session_id available but not currently used
    # session_id = data.get("session_id", "")

    title, icon, urgency = _notification_params(notification_type)

    if IS_WIN:
        _win_play_sound()
        _win_show_notification(title, message)
    else:
        _linux_play_sound()
        _linux_show_notification(title, message, icon, urgency)

    # Return success to Claude (Notification hooks use simple schema)
    sys.stdout.write('{"continue":true,"suppressOutput":true}')


# ===========================================================================
# Main entry point
# ===========================================================================

def main() -> None:
    # Graceful signal handling (mirror bash trap behaviour)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: sys.exit(0))
    # SIGHUP only available on non-Windows
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, lambda *_: sys.exit(0))

    if len(sys.argv) < 2:
        print("Usage: utils.py [focus|notify] [args...]", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "focus":
        cwd = sys.argv[2] if len(sys.argv) > 2 else None
        do_focus(cwd)
    elif mode == "notify":
        do_notify()
    else:
        print("Usage: utils.py [focus|notify] [args...]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
