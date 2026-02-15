#!/usr/bin/env python3
"""
Cross-platform compatibility module for Claude Code hooks and scripts.

Provides platform-aware replacements for:
- signal.SIGALRM (stdin timeout)
- fcntl.flock (file locking)
- Path resolution (CLAUDE_HOME)
- Python executable detection

Usage:
    from scripts.compat import IS_WINDOWS, get_claude_home, setup_stdin_timeout
    # or with sys.path manipulation:
    import sys; sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts.compat import ...
"""

import os
import subprocess
import sys
import threading
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

# Module-level reference to the stdin timeout Timer so it can be cancelled
_stdin_timer: threading.Timer | None = None


def get_python_exe() -> str:
    """Return the current Python interpreter path."""
    return sys.executable


def get_claude_home() -> Path:
    """Return CLAUDE_HOME with platform-aware default."""
    env = os.environ.get("CLAUDE_HOME")
    if env:
        return Path(env)
    if IS_WINDOWS:
        return Path.home() / ".claude"
    return Path("/usr/share/claude")


def setup_stdin_timeout(seconds: int, debug_label: str = "") -> None:
    """
    Set a timeout for stdin read operations.

    On POSIX: uses signal.SIGALRM (interrupts blocking reads).
    On Windows: uses a daemon thread with os._exit (forceful but reliable).

    Args:
        seconds: Timeout in seconds
        debug_label: Optional label for debug logging when timeout fires
    """
    global _stdin_timer
    if IS_WINDOWS:
        def _timeout_handler():
            if debug_label:
                from datetime import datetime
                log_dir = get_claude_home() / "debug"
                log_dir.mkdir(exist_ok=True)
                log_file = log_dir / "hook-timeout.log"
                timestamp = datetime.now().isoformat()
                with open(log_file, "a") as f:
                    f.write(f"{timestamp} - Timeout ({seconds}s): {debug_label}\n")
            os._exit(0)

        _stdin_timer = threading.Timer(seconds, _timeout_handler)
        _stdin_timer.daemon = True
        _stdin_timer.start()
    else:
        import signal

        def _handler(signum, frame):
            if debug_label:
                from datetime import datetime
                log_dir = get_claude_home() / "debug"
                log_dir.mkdir(exist_ok=True)
                log_file = log_dir / "hook-timeout.log"
                timestamp = datetime.now().isoformat()
                with open(log_file, "a") as f:
                    f.write(f"{timestamp} - Timeout ({seconds}s): {debug_label}\n")
            sys.exit(0)

        signal.signal(signal.SIGALRM, _handler)
        signal.alarm(seconds)


def cancel_stdin_timeout() -> None:
    """Cancel a previously set stdin timeout."""
    global _stdin_timer
    if IS_WINDOWS:
        if _stdin_timer is not None:
            _stdin_timer.cancel()
            _stdin_timer = None
    else:
        import signal

        signal.alarm(0)


def file_lock(fd: int, exclusive: bool = True) -> None:
    """
    Acquire a file lock, cross-platform.

    On POSIX: uses fcntl.flock().
    On Windows: uses msvcrt.locking() on 1 byte at current position.
    """
    if IS_WINDOWS:
        import msvcrt

        # Note: Windows msvcrt does not support shared locks; all locks are exclusive
        lock_mode = msvcrt.LK_LOCK if exclusive else msvcrt.LK_LOCK
        msvcrt.locking(fd, lock_mode, 1)
    else:
        import fcntl

        lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(fd, lock_mode)


def file_lock_nb(fd: int) -> bool:
    """
    Try to acquire a non-blocking exclusive file lock.

    Returns True if lock acquired, False if already locked.
    """
    if IS_WINDOWS:
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    else:
        import fcntl

        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False


def file_unlock(fd: int) -> None:
    """Release a file lock, cross-platform."""
    if IS_WINDOWS:
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass  # Already unlocked
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


def create_symlink(target: Path, link: Path) -> bool:
    """
    Create a symlink/junction, cross-platform.

    On Windows: creates a junction using cmd.exe mklink /J.
    On Linux: creates a symlink using os.symlink.

    Args:
        target: Path to the target directory
        link: Path where the symlink/junction should be created

    Returns:
        True if successful, False otherwise
    """
    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)],
                capture_output=True,
                text=True,
                check=False
            )
            return result.returncode == 0
        else:
            os.symlink(str(target), str(link))
            return True
    except Exception:
        return False


def is_symlink(path: Path) -> bool:
    """
    Check if path is a symlink/junction, cross-platform.

    On Windows (Python 3.12+): uses path.is_junction().
    On Windows (Python <3.12): uses os.path.islink() fallback.
    On Linux: uses path.is_symlink().

    Args:
        path: Path to check

    Returns:
        True if path is a symlink/junction, False otherwise
    """
    try:
        if IS_WINDOWS:
            # Try Python 3.12+ method first
            if hasattr(path, 'is_junction'):
                return path.is_junction()
            # Fallback to os.path.islink
            return os.path.islink(str(path))
        else:
            return path.is_symlink()
    except Exception:
        return False


def get_symlink_target(path: Path) -> Path | None:
    """
    Get the target of a symlink/junction, cross-platform.

    Args:
        path: Path to the symlink/junction

    Returns:
        Path to the target, or None if path is not a symlink or on error
    """
    try:
        return path.readlink()
    except Exception:
        return None


def play_sound(wav_path: Path) -> None:
    """
    Play a WAV sound file, cross-platform.

    On Windows: uses winsound.PlaySound().
    On Linux: tries aplay, then paplay as fallback.

    Args:
        wav_path: Path to the .wav file to play
    """
    if not wav_path.exists():
        return

    if IS_WINDOWS:
        try:
            import winsound
            winsound.PlaySound(str(wav_path), winsound.SND_FILENAME)
        except Exception:
            pass  # Silently ignore errors
    else:
        # Try aplay first, then paplay
        for player in ["aplay", "paplay"]:
            try:
                subprocess.Popen(
                    [player, str(wav_path)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                break  # Success, don't try other players
            except FileNotFoundError:
                continue  # Try next player
            except Exception:
                break  # Give up on error
