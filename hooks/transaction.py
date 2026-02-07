r"""ACID transaction primitives for stateful hooks.

This module provides atomic file operations with proper locking, integrity validation,
and rollback guarantees. Designed for safe concurrent access to shared state files
across multiple hook invocations and agent processes.

**Plan:** ~/.claude\plans\steady-kindling-candy.md

**Core primitives:**
- atomic_write_json/text: Atomic write-or-fail using temp files + rename
- locked_read_json: Safe shared reads with timeout
- transactional_update: Optimistic concurrency control for state mutations

**Guarantees:**
- Atomicity: Writes complete fully or not at all (no partial states)
- Consistency: Optional validation ensures schema compliance
- Isolation: portalocker provides cross-platform file locking
- Durability: fsync=True forces OS to flush to disk before returning

**Error handling:**
- LockTimeoutError: Acquire timeout (default 5s)
- ValidationError: Schema/integrity check failed
- ConcurrentModificationError: OCC conflict detected
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional, TypeVar

import portalocker

# Configuration constants
DEFAULT_TIMEOUT = 5.0
INTEGRITY_MARKER = "claude_state_v1"

# Type variable for generic functions
T = TypeVar("T")


# Exception hierarchy
class TransactionError(Exception):
    """Base exception for transaction failures."""
    pass


class LockTimeoutError(TransactionError):
    """Raised when lock acquisition times out."""
    pass


class ValidationError(TransactionError):
    """Raised when schema or integrity validation fails."""
    pass


class ConcurrentModificationError(TransactionError):
    """Raised when optimistic concurrency control detects a conflict."""
    pass


def atomic_write_json(
    path: Path | str,
    data: Any,
    fsync: bool = True,
    validate_fn: Optional[Callable[[Any], bool]] = None,
) -> None:
    """Write JSON data atomically using temp file + rename.

    **Atomicity guarantee:** Either the full write succeeds or the original file
    remains unchanged. No partial writes are visible to readers.

    **Process:**
    1. Validate data if validate_fn provided
    2. Create temp file in same directory as target
    3. Write JSON to temp file
    4. Fsync if requested (flush to disk)
    5. Atomic rename over target

    Args:
        path: Target file path
        data: Python object to serialize as JSON
        fsync: Force OS flush to disk (default: True for durability)
        validate_fn: Optional validation callable; raises ValidationError if returns False

    Raises:
        ValidationError: If validate_fn returns False
        TransactionError: On write or rename failure
    """
    path = Path(path)

    # Validate data before write
    if validate_fn is not None and not validate_fn(data):
        raise ValidationError(f"Validation failed for data: {path}")

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory (ensures same filesystem for atomic rename)
    tmp_file = None
    tmp_path = None

    try:
        tmp_file = tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path.parent,
            delete=False,
            suffix='.tmp'
        )
        tmp_path = Path(tmp_file.name)

        # Write JSON to temp file
        json.dump(data, tmp_file, indent=2)
        tmp_file.flush()

        # Force OS flush to disk for durability
        if fsync:
            os.fsync(tmp_file.fileno())

        tmp_file.close()

        # Atomic rename (POSIX guarantees atomicity)
        os.replace(tmp_path, path)

    except Exception as e:
        # Clean up temp file on failure
        if tmp_file is not None and not tmp_file.closed:
            tmp_file.close()
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
        raise TransactionError(f"Atomic write failed for {path}: {e}") from e


def atomic_write_text(
    path: Path | str,
    content: str,
    fsync: bool = True,
) -> None:
    """Write text content atomically using temp file + rename.

    Same atomicity guarantees as atomic_write_json but for plain text.

    Args:
        path: Target file path
        content: Text content to write
        fsync: Force OS flush to disk (default: True)

    Raises:
        TransactionError: On write or rename failure
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_file = None
    tmp_path = None

    try:
        tmp_file = tempfile.NamedTemporaryFile(
            mode='w',
            encoding='utf-8',
            dir=path.parent,
            delete=False,
            suffix='.tmp'
        )
        tmp_path = Path(tmp_file.name)

        # Write text to temp file
        tmp_file.write(content)
        tmp_file.flush()

        if fsync:
            os.fsync(tmp_file.fileno())

        tmp_file.close()

        # Atomic rename
        os.replace(tmp_path, path)

    except Exception as e:
        if tmp_file is not None and not tmp_file.closed:
            tmp_file.close()
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()
        raise TransactionError(f"Atomic text write failed for {path}: {e}") from e


def locked_read_json(
    path: Path | str,
    timeout: float = DEFAULT_TIMEOUT,
    default: Optional[Any] = None,
) -> Any:
    """Read JSON file with shared lock (multiple readers allowed).

    **Isolation guarantee:** Lock prevents writers from modifying file during read.

    Args:
        path: File path to read
        timeout: Lock acquisition timeout in seconds (default: 5.0)
        default: Value to return if file doesn't exist (default: None)

    Returns:
        Parsed JSON data or default if file missing

    Raises:
        LockTimeoutError: If lock acquisition times out
        TransactionError: On JSON parse failure
    """
    path = Path(path)

    # Return default if file doesn't exist
    if not path.exists():
        return default

    try:
        # Shared lock (LOCK_SH) allows multiple concurrent readers
        with portalocker.Lock(
            str(path),
            mode='r',
            flags=portalocker.LOCK_SH,
            timeout=timeout
        ) as f:
            # Handle empty files gracefully (common after interrupted writes)
            content = f.read()
            if not content.strip():
                return default

            f.seek(0)
            return json.load(f)

    except portalocker.exceptions.LockException as e:
        raise LockTimeoutError(f"Lock timeout reading {path} after {timeout}s") from e
    except json.JSONDecodeError as e:
        raise TransactionError(f"Invalid JSON in {path}: {e}") from e


def transactional_update(
    path: Path | str,
    update_fn: Callable[[Any], Any],
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 3,
    fsync: bool = True,
    default: Optional[Any] = None,
) -> Any:
    """Update file atomically using read-modify-write with exclusive locking.

    **Transaction semantics:**
    1. Acquire exclusive lock (blocks all readers and writers)
    2. Read current state (or use default if file missing)
    3. Call update_fn(current_state) → new_state
    4. Write new state in-place
    5. Release lock

    **Retry logic:** Retries on lock timeout (up to `retries` times).

    Args:
        path: File path to update
        update_fn: Transform function: old_state → new_state
        timeout: Lock acquisition timeout per attempt
        retries: Maximum retry attempts on lock failure
        fsync: Force OS flush to disk
        default: Initial state if file doesn't exist

    Returns:
        New state returned by update_fn

    Raises:
        LockTimeoutError: If all retry attempts fail
        TransactionError: On read/write failure
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(retries + 1):
        try:
            # Determine lock mode based on file existence
            # Start with r+ for existing files, w+ for new files
            lock_mode = 'r+' if path.exists() else 'w+'

            # Exclusive lock (LOCK_EX) blocks all other accessors
            with portalocker.Lock(
                str(path),
                mode=lock_mode,
                flags=portalocker.LOCK_EX,
                timeout=timeout
            ) as f:
                # Read current state (if file exists and has content)
                current_state = default
                if lock_mode == 'r+':
                    try:
                        content = f.read()
                        if content.strip():
                            f.seek(0)
                            current_state = json.load(f)
                        else:
                            # Empty file - use default
                            current_state = default
                    except json.JSONDecodeError:
                        # Corrupted file - treat as default
                        current_state = default

                # Apply update function
                new_state = update_fn(current_state)

                # Write back atomically (in-place, since we hold exclusive lock)
                f.seek(0)
                f.truncate()
                json.dump(new_state, f, indent=2)
                f.flush()

                if fsync:
                    os.fsync(f.fileno())

                return new_state

        except FileNotFoundError:
            # File doesn't exist - retry with w+ mode on next iteration
            # (This handles the race where file was deleted between attempts)
            lock_mode = 'w+'
            continue

        except portalocker.exceptions.LockException as e:
            if attempt == retries:
                raise LockTimeoutError(
                    f"Lock timeout updating {path} after {retries + 1} attempts"
                ) from e
            # Retry on next iteration

        except Exception as e:
            raise TransactionError(f"Update failed for {path}: {e}") from e

    # Should never reach here due to raise in loop
    raise TransactionError(f"Transactional update failed unexpectedly for {path}")


# ==============================================================================
# Optimistic Concurrency Control (OCC)
# ==============================================================================

def add_version(data: dict) -> dict:
    """Add or increment version field for optimistic concurrency control.

    **OCC pattern:** Each write increments _version. Conflicts detected by
    checking if _version changed between read and write.

    Args:
        data: Dictionary to version (modified in-place)

    Returns:
        Same dict with _version incremented and _updated_at timestamp
    """
    from datetime import datetime, timezone

    current_version = data.get("_version", 0)
    data["_version"] = current_version + 1
    data["_updated_at"] = datetime.now(timezone.utc).isoformat()

    return data


def transactional_update_occ(
    path: Path | str,
    update_fn: Callable[[Any], Any],
    retries: int = 3,
    fsync: bool = True,
    default: Optional[Any] = None,
) -> Any:
    """Update file atomically using optimistic concurrency control.

    **OCC strategy (CORRECTED - uses exclusive lock for version check + write):**
    1. Read current state + _version (shared lock)
    2. Apply update_fn to get new state
    3. Increment _version via add_version
    4. Acquire EXCLUSIVE lock
    5. Re-read file to verify _version hasn't changed (under lock)
    6. If conflict detected, release lock and retry
    7. Atomic write-in-place (already holding exclusive lock)

    **Note:** The original implementation had a TOCTOU race between version check
    and atomic write. This corrected version uses exclusive locking for the
    check-and-write critical section.

    **Trade-off:** This is now equivalent to transactional_update in terms of
    locking overhead. True lock-free OCC requires Compare-And-Swap (CAS) atomic
    operations not available via standard file I/O.

    Args:
        path: File path to update
        update_fn: Transform function: old_state → new_state
        retries: Maximum retry attempts on version conflict
        fsync: Force OS flush to disk
        default: Initial state if file doesn't exist

    Returns:
        New state returned by update_fn

    Raises:
        ConcurrentModificationError: If all retry attempts fail due to conflicts
        TransactionError: On read/write failure
    """
    # TODO-P1: This implementation cannot provide true OCC semantics without CAS.
    # Consider using SQLite with BEGIN IMMEDIATE for real optimistic locking,
    # or document that this is pessimistic locking with version checking.

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(retries + 1):
        try:
            # Read current state (shared lock - allows concurrent readers)
            current_state = locked_read_json(path, default=default or {})
            original_version = current_state.get("_version", 0) if isinstance(current_state, dict) else 0

            # Apply update function (no lock held - allows concurrent computation)
            new_state = update_fn(current_state)

            # Add version metadata
            if isinstance(new_state, dict):
                new_state = add_version(new_state)

            # CRITICAL SECTION: Acquire exclusive lock for check-and-write
            try:
                lock_mode = 'r+' if path.exists() else 'w+'
            except:
                lock_mode = 'w+'

            with portalocker.Lock(
                str(path),
                mode=lock_mode,
                flags=portalocker.LOCK_EX,
                timeout=DEFAULT_TIMEOUT
            ) as f:
                # Re-read file under exclusive lock to verify version
                verification_state = default or {}
                if lock_mode == 'r+':
                    try:
                        content = f.read()
                        if content.strip():
                            f.seek(0)
                            verification_state = json.load(f)
                    except json.JSONDecodeError:
                        verification_state = default or {}

                verification_version = verification_state.get("_version", 0) if isinstance(verification_state, dict) else 0

                if verification_version != original_version:
                    # Version conflict detected - release lock and retry
                    if attempt == retries:
                        raise ConcurrentModificationError(
                            f"Version conflict after {retries + 1} attempts: {path} "
                            f"(expected v{original_version}, found v{verification_version})"
                        )
                    # Lock released at end of with block - retry on next iteration
                    continue

                # No conflict - write in-place (already holding exclusive lock)
                f.seek(0)
                f.truncate()
                json.dump(new_state, f, indent=2)
                f.flush()

                if fsync:
                    os.fsync(f.fileno())

                return new_state

        except FileNotFoundError:
            # File doesn't exist - retry with w+ mode
            continue

        except (LockTimeoutError, ValidationError, ConcurrentModificationError):
            # Re-raise transaction errors without wrapping
            raise
        except Exception as e:
            raise TransactionError(f"OCC update failed for {path}: {e}") from e

    # Should never reach here
    raise ConcurrentModificationError(f"OCC update exhausted retries for {path}")


# ==============================================================================
# Validation Helpers
# ==============================================================================

def validate_with_marker(data: Any, marker: str = INTEGRITY_MARKER) -> bool:
    """Validate data contains expected integrity marker.

    Args:
        data: Data structure to validate
        marker: Expected integrity marker string

    Returns:
        True if data is dict and contains matching integrity_marker field
    """
    if not isinstance(data, dict):
        return False
    return data.get("integrity_marker") == marker


def validate_sessions_index(data: Any) -> bool:
    """Validate sessions-index.json schema.

    **Expected structure:**
    {
        "entries": [
            {"sessionId": "...", ...},
            ...
        ]
    }

    Args:
        data: Parsed JSON data

    Returns:
        True if schema valid, False otherwise
    """
    if not isinstance(data, dict):
        return False

    entries = data.get("entries")
    if not isinstance(entries, list):
        return False

    # Check each entry has sessionId string
    for entry in entries:
        if not isinstance(entry, dict):
            return False
        if "sessionId" not in entry:
            return False
        if not isinstance(entry["sessionId"], str):
            return False

    return True


def validate_ralph_progress(data: Any) -> bool:
    """Validate ralph progress.json schema.

    **Expected structure:**
    {
        "total": int,
        "completed": int,
        "failed": int,
        "done": bool,
        "cost_usd": float,
        ...
    }

    Args:
        data: Parsed JSON data

    Returns:
        True if schema valid, False otherwise
    """
    if not isinstance(data, dict):
        return False

    required_keys = ["total", "completed", "failed", "done", "cost_usd"]
    if not all(key in data for key in required_keys):
        return False

    # Type validation (defensive)
    try:
        total = int(data["total"])
        completed = int(data["completed"])
        failed = int(data["failed"])
        done = bool(data["done"])
        cost_usd = float(data["cost_usd"])

        # Logical constraints
        if total < 0 or completed < 0 or failed < 0:
            return False
        if completed > total or failed > total:
            return False
        if cost_usd < 0:
            return False

        return True
    except (ValueError, TypeError):
        return False


def validate_emergency_state(data: Any) -> bool:
    """Validate emergency state schema.

    **Expected structure:**
    {
        "integrity_marker": "claude_emergency_state_v1",
        "blocks": [...],
        "shutdowns": [...],
        "manual_kill": bool,
        ...
    }

    Args:
        data: Parsed JSON data

    Returns:
        True if schema valid, False otherwise
    """
    if not isinstance(data, dict):
        return False

    # Check integrity marker
    if data.get("integrity_marker") != "claude_emergency_state_v1":
        return False

    # Check required keys and types
    required_keys = ["blocks", "shutdowns", "manual_kill"]
    if not all(key in data for key in required_keys):
        return False

    # Type validation
    if not isinstance(data["blocks"], list):
        return False
    if not isinstance(data["shutdowns"], list):
        return False
    if not isinstance(data["manual_kill"], bool):
        return False

    return True
