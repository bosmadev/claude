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


def setup_stdin_timeout(seconds: int) -> None:
    """
    Set a timeout for stdin read operations.

    On POSIX: uses signal.SIGALRM (interrupts blocking reads).
    On Windows: uses a daemon thread with os._exit (forceful but reliable).
    """
    global _stdin_timer
    if IS_WINDOWS:
        _stdin_timer = threading.Timer(seconds, lambda: os._exit(0))
        _stdin_timer.daemon = True
        _stdin_timer.start()
    else:
        import signal

        def _handler(signum, frame):
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
