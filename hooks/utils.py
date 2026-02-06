#!/usr/bin/env python3
"""Desktop Utilities Hook - Focus, notification, and model capture handlers.

Cross-platform replacement for utils.sh. Supports Windows (ctypes/PowerShell)
and Linux (wmctrl/xdotool/notify-send/paplay).

Usage:
    utils.py focus [cwd]      # Focus appropriate window
    utils.py notify           # Show notification with sound (reads JSON from stdin)
    utils.py model-capture    # Capture model ID from SessionStart hook (reads JSON from stdin)
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from pathlib import Path

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
    # Validate pattern to prevent matching all windows
    if not pattern or not pattern.strip():
        return None
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
        # Error handling for GetWindowTextW failures
        try:
            buf = ctypes.create_unicode_buffer(length + 1)
            chars_copied = ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            if chars_copied == 0:
                return True  # Failed to get window text, continue enumeration
            if pattern_lower in buf.value.lower():
                result.append(hwnd)
                return False  # stop enumeration
        except (OSError, ValueError):
            return True  # Error creating buffer or getting text, continue enumeration
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

    # Validate and sanitize cwd path
    try:
        cwd_path = Path(cwd).resolve()
        if not cwd_path.exists():
            # Fall back to home directory if path doesn't exist
            cwd = str(Path.home())
        else:
            cwd = str(cwd_path)
    except (OSError, ValueError):
        # Invalid path - use home directory
        cwd = str(Path.home())

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

        # Fallback: launch an editor / terminal with error handling
        try:
            if shutil.which("code-insiders"):
                subprocess.Popen(["code-insiders", "."], cwd=cwd, creationflags=subprocess.DETACHED_PROCESS)
            elif shutil.which("wt"):
                subprocess.Popen(["wt", "-d", cwd], creationflags=subprocess.DETACHED_PROCESS)
            else:
                subprocess.Popen(["explorer", cwd], creationflags=subprocess.DETACHED_PROCESS)
        except (OSError, PermissionError):
            # Silently fail - focus is best-effort
            pass
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

        # Fallback: launch an editor / terminal with error handling
        try:
            if _has_command("kate"):
                subprocess.Popen(["kate", cwd])
            elif _has_command("code-insiders"):
                subprocess.Popen(["code-insiders", "."], cwd=cwd)
            else:
                subprocess.Popen(["konsole", "--workdir", cwd])
        except (OSError, PermissionError):
            # Silently fail - focus is best-effort
            pass


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
    # Comprehensive escaping for PowerShell: single quotes, backticks, newlines, variables
    def escape_powershell(text: str) -> str:
        """Escape text for safe PowerShell string inclusion."""
        # Replace single quotes (PowerShell string delimiter)
        text = text.replace("'", "''")
        # Replace backticks (PowerShell escape character)
        text = text.replace("`", "``")
        # Replace newlines
        text = text.replace("\n", " ").replace("\r", "")
        # Remove dollar signs (variable expansion)
        text = text.replace("$", "")
        # Truncate to prevent command length issues
        return text[:200]

    safe_title = escape_powershell(title)
    safe_message = escape_powershell(message)

    # Use -EncodedCommand to prevent injection via title/message
    import base64
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

    # Encode to Base64 for -EncodedCommand (UTF-16LE required)
    encoded_cmd = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")

    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded_cmd],
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
# Model capture mode (SessionStart hook)
# ===========================================================================

# Model ID patterns:
#   claude-opus-4-5-20251101   → Opus 4.5
#   claude-opus-4-6            → Opus 4.6  (no date suffix = alias)
#   claude-sonnet-5-20260201   → Sonnet 5
#   claude-haiku-3-5-20241022  → Haiku 3.5
# Strategy: try dated patterns first, then date-less patterns
_MODEL_PATTERN_FULL = re.compile(
    r"claude-(?P<family>[a-z]+)-(?P<major>\d+)-(?P<minor>\d{1,2})-(?P<date>\d{8,})",
    re.IGNORECASE,
)
_MODEL_PATTERN_SHORT = re.compile(
    r"claude-(?P<family>[a-z]+)-(?P<major>\d+)-(?P<date>\d{8,})",
    re.IGNORECASE,
)
_MODEL_PATTERN_FULL_NO_DATE = re.compile(
    r"claude-(?P<family>[a-z]+)-(?P<major>\d+)-(?P<minor>\d{1,2})$",
    re.IGNORECASE,
)
_MODEL_PATTERN_SHORT_NO_DATE = re.compile(
    r"claude-(?P<family>[a-z]+)-(?P<major>\d+)$",
    re.IGNORECASE,
)

# Fallback for short names: "opus", "sonnet", "haiku"
# Versionless — bare name without version = regex didn't match, investigate why.
_SHORT_NAMES = {
    "opus": {"family": "Opus", "version": ""},
    "sonnet": {"family": "Sonnet", "version": ""},
    "haiku": {"family": "Haiku", "version": ""},
}


def parse_model_id(model_id: str) -> dict:
    """Parse a model ID string into structured info.

    Examples:
        claude-opus-4-5-20251101 → { family: "Opus", version: "4.5", date: "20251101", raw: "..." }
        claude-sonnet-5-20260201 → { family: "Sonnet", version: "5", date: "20260201", raw: "..." }
        opus                     → { family: "Opus", version: "4.5", date: "", raw: "opus" }
    """
    result = {"family": "Claude", "version": "", "date": "", "raw": model_id, "display": "Claude"}

    if not model_id:
        return result

    # Try dated patterns first, then date-less patterns
    m = (
        _MODEL_PATTERN_FULL.match(model_id)
        or _MODEL_PATTERN_SHORT.match(model_id)
        or _MODEL_PATTERN_FULL_NO_DATE.match(model_id)
        or _MODEL_PATTERN_SHORT_NO_DATE.match(model_id)
    )
    if m:
        family = m.group("family").capitalize()
        major = m.group("major") or ""
        minor = m.group("minor") if "minor" in m.groupdict() and m.group("minor") else ""
        date = m.group("date") if "date" in m.groupdict() and m.group("date") else ""

        version = f"{major}.{minor}" if minor else major
        result.update({
            "family": family,
            "version": version,
            "date": date,
            "display": f"{family} {version}" if version else family,
        })
        return result

    # Try short name lookup
    # Handle empty strings and whitespace-only input
    stripped = model_id.strip().lower()
    if not stripped:
        return result
    parts = stripped.split()
    if not parts:
        return result
    short = parts[0]
    if short in _SHORT_NAMES:
        info = _SHORT_NAMES[short]
        display = f"{info['family']} {info['version']}" if info["version"] else info["family"]
        result.update({
            "family": info["family"],
            "version": info["version"],
            "display": display,
        })
        return result

    # Fallback: capitalize first word
    # Handle empty strings and whitespace-only input
    stripped_fallback = model_id.strip()
    if not stripped_fallback:
        return result
    words = stripped_fallback.split()
    if not words:
        return result
    first_word = words[0]
    result.update({"family": first_word.capitalize(), "display": first_word.capitalize()})
    return result


def get_session_name(session_id: str) -> str:
    """Look up the display name for a session from sessions-index.json.

    Searches all project session indices for the given session ID.
    Returns customTitle (from /rename) if present, else summary, else empty string.
    """
    if not session_id:
        return ""
    try:
        claude_dir = Path.home() / ".claude" / "projects"
        for idx_path in claude_dir.glob("*/sessions-index.json"):
            try:
                data = json.loads(idx_path.read_text(encoding="utf-8"))
                for entry in data.get("entries", []):
                    if entry.get("sessionId") == session_id:
                        return entry.get("customTitle") or entry.get("summary") or ""
            except (json.JSONDecodeError, OSError):
                continue
    except Exception:
        pass
    return ""


def do_model_capture() -> None:
    """Capture model ID from SessionStart hook input, write to ~/.claude/.model-info."""
    raw = _read_stdin_with_timeout(5)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = {}

    model_id = data.get("model", "")
    if not model_id:
        # Try nested structure
        model_id = data.get("session", {}).get("model", "") if isinstance(data.get("session"), dict) else ""

    parsed = parse_model_id(model_id)

    # Write to ~/.claude/.model-info
    model_info_path = Path.home() / ".claude" / ".model-info"
    try:
        model_info_path.parent.mkdir(parents=True, exist_ok=True)
        model_info_path.write_text(json.dumps(parsed, indent=2), encoding="utf-8")
    except OSError:
        pass

    # Return success (SessionStart hooks use simple schema)
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
        print("Usage: utils.py [focus|notify|model-capture] [args...]", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "focus":
        cwd = sys.argv[2] if len(sys.argv) > 2 else None
        do_focus(cwd)
    elif mode == "notify":
        do_notify()
    elif mode == "model-capture":
        do_model_capture()
    else:
        print("Usage: utils.py [focus|notify|model-capture] [args...]", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
