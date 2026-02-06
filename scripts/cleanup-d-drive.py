#!/usr/bin/env python3
"""
D: Drive Cleanup Script

Removes temporary files and directories from D: drive:
- cache-break-*.diff files in D:\tmp\claude\
- NUL files at D:\claude\nul and D:\nul (via Git Bash)
- Empty directories after cleanup

Git Bash rm is required for NUL files because Windows treats "nul" as a
reserved device name (like CON, PRN, AUX). Python's pathlib.unlink() and
os.remove() fail with "The system cannot find the file specified" error.
Git Bash rm bypasses this restriction by using POSIX path semantics.
"""

import subprocess
from pathlib import Path


def format_size(size_bytes: int) -> str:
    """Format byte size as human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024}KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f}MB"


def cleanup_cache_break_diffs() -> None:
    """Remove cache-break-*.diff files from D:\tmp\claude\."""
    print("[cache-break diffs]")
    tmp_dir = Path("D:/tmp/claude")

    if not tmp_dir.exists():
        print("  → D:\\tmp\\claude\\ not found")
        return

    # Find all cache-break diff files
    diff_files = list(tmp_dir.glob("cache-break-*.diff"))

    if not diff_files:
        print("  → No cache-break-*.diff files found")
        return

    # Calculate total size
    total_size = sum(f.stat().st_size for f in diff_files if f.exists())
    print(f"  Found {len(diff_files)} files ({format_size(total_size)})")

    # Remove each file
    for diff_file in diff_files:
        try:
            diff_file.unlink()
            print(f"  ✓ Removed {diff_file.name}")
        except Exception as e:
            print(f"  ✗ Failed to remove {diff_file.name}: {e}")

    # Remove directory if empty
    try:
        if not any(tmp_dir.iterdir()):
            tmp_dir.rmdir()
            print(f"  ✓ Removed {tmp_dir} (empty)")
    except Exception as e:
        print(f"  → {tmp_dir} not empty or failed to remove: {e}")


def cleanup_nul_files() -> None:
    """Remove NUL files using Git Bash rm command."""
    print("\n[NUL files]")

    nul_paths = [
        "D:/claude/nul",
        "D:/nul"
    ]

    for nul_path in nul_paths:
        # Check if file exists before attempting removal
        # Note: Path.exists() may fail for NUL files, but try anyway
        try:
            result = subprocess.run(
                ["bash", "-c", f"rm '{nul_path}'"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                print(f"  ✓ Removed {nul_path}")
            else:
                # Check if error is "file not found" (acceptable)
                if "No such file" in result.stderr:
                    print(f"  → {nul_path} not found")
                else:
                    print(f"  ✗ Failed to remove {nul_path}: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            print(f"  ✗ Timeout removing {nul_path}")
        except FileNotFoundError:
            print(f"  ✗ Git Bash not found (bash command unavailable)")
            break
        except Exception as e:
            print(f"  ✗ Failed to remove {nul_path}: {e}")


def cleanup_empty_directories() -> None:
    """Remove empty D:\claude\ directory if applicable."""
    print("\n[directories]")

    claude_dir = Path("D:/claude")

    if not claude_dir.exists():
        print("  → D:\\claude\\ not found")
        return

    try:
        if not any(claude_dir.iterdir()):
            claude_dir.rmdir()
            print(f"  ✓ Removed {claude_dir} (empty)")
        else:
            print(f"  → {claude_dir} not empty")
    except Exception as e:
        print(f"  ✗ Failed to remove {claude_dir}: {e}")


def main() -> None:
    """Run D: drive cleanup tasks."""
    print("D: Drive Cleanup")
    print("=" * 16)

    cleanup_cache_break_diffs()
    cleanup_nul_files()
    cleanup_empty_directories()

    print("\nDone.")


if __name__ == "__main__":
    main()
