#!/usr/bin/env python3
"""Claude Code Chats Manager - list, rename, delete, and clean up chats."""

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

CLAUDE_DIR = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
PLANS_DIR = CLAUDE_DIR / "plans"


# ── Helpers ──────────────────────────────────────────────


def get_terminal_width() -> int:
    """Get current terminal width, minimum 80 columns."""
    return max(shutil.get_terminal_size().columns, 80)


def format_table(columns: list[dict]) -> dict[str, int]:
    """Calculate column widths for terminal-width table rendering.

    Args:
        columns: List of dicts with 'name', 'min_width', 'flex' (bool)
                 Columns with flex=True expand to fill available space.
                 First flex column is PRIMARY, others are SECONDARY.

    Returns:
        Dict mapping column name -> calculated width
    """
    term_width = get_terminal_width()
    total_fixed = sum(c["min_width"] for c in columns if not c.get("flex", False))
    total_separators = (len(columns) - 1) * 1  # Single space between columns
    available = term_width - total_fixed - total_separators

    flex_cols = [c for c in columns if c.get("flex", False)]
    if not flex_cols:
        return {c["name"]: c["min_width"] for c in columns}

    # Distribute available space: primary flex gets 60%, others split the rest
    widths = {}
    for c in columns:
        if not c.get("flex", False):
            widths[c["name"]] = c["min_width"]
        else:
            if c == flex_cols[0]:  # Primary flex
                widths[c["name"]] = c["min_width"] + int(available * 0.6)
            else:  # Secondary flex
                remaining = available - int(available * 0.6)
                share = remaining // (len(flex_cols) - 1) if len(flex_cols) > 1 else 0
                widths[c["name"]] = c["min_width"] + share

    return widths


def truncate(text: str, width: int) -> str:
    """Truncate text to width with '...' if needed."""
    if len(text) <= width:
        return text
    return text[:width-3] + "..."


def format_relative_date(date_str: str) -> str:
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            now = datetime.now()
        diff = now - dt
        minutes = diff.total_seconds() / 60
        hours = minutes / 60
        days = hours / 24
        if minutes < 60:
            return f"{int(minutes)}m ago"
        if hours < 24:
            return f"{int(hours)}h ago"
        if days < 7:
            return f"{int(days)}d ago"
        return dt.strftime("%b %d %H:%M")
    except Exception:
        return "unknown"


def format_size(size_bytes: int) -> str:
    if size_bytes >= 1_073_741_824:
        return f"{size_bytes / 1_073_741_824:.1f} GB"
    if size_bytes >= 1_048_576:
        return f"{size_bytes / 1_048_576:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def decode_project_path(encoded_project_path: str) -> str:
    """Decode Claude Code's project path encoding: C--Users-Dennis--claude -> ~/.claude"""
    projects_dir_str = str(PROJECTS_DIR)
    if not encoded_project_path.startswith(projects_dir_str):
        return encoded_project_path

    encoded = Path(encoded_project_path).name
    m = re.match(r"^([A-Z])--(.+)$", encoded)
    if m:
        drive = m.group(1)
        rest = m.group(2)
        # Strategy 1: -- -> \. (hidden dirs) then - -> \
        try1 = drive + ":\\" + rest.replace("--", "\\.").replace("-", "\\")
        if Path(try1).is_dir():
            return try1
        # Strategy 2: all - -> \
        try2 = drive + ":\\" + rest.replace("-", "\\")
        if Path(try2).is_dir():
            return try2
    return encoded_project_path


def get_project_display(project_path: str, git_branch: str = "") -> str:
    if not project_path:
        return "unknown"

    real_path = decode_project_path(project_path)
    project_name = Path(real_path).name

    git_file = Path(real_path) / ".git"
    if git_file.is_file():
        try:
            content = git_file.read_text()
            m = re.search(r"gitdir:\s*(.+)", content)
            if m:
                gitdir = m.group(1).strip()
                repo_name = Path(re.sub(r"[\\/]\.git[\\/]worktrees[\\/].*$", "", gitdir)).name
                return f"{repo_name}/{project_name}"
        except Exception:
            pass

    if git_branch:
        return f"{project_name}/{git_branch}"
    return project_name


def get_all_chats() -> list[dict]:
    entries = []
    if not PROJECTS_DIR.exists():
        return entries
    for index_file in PROJECTS_DIR.glob("*/sessions-index.json"):
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            for entry in data.get("entries", []):
                entry["_indexFile"] = str(index_file)
                entries.append(entry)
        except Exception:
            pass
    entries.sort(key=lambda e: e.get("modified", ""), reverse=True)
    return entries


def find_chat_by_id(chat_id: str, chats: list[dict] | None = None) -> dict | None:
    if chats is None:
        chats = get_all_chats()
    for c in chats:
        if c.get("sessionId", "").startswith(chat_id):
            return c
    return None


def get_directory_stats(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {"count": 0, "size": 0, "size_str": "0 B"}
    total_size = 0
    count = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total_size += f.stat().st_size
                count += 1
            except OSError:
                pass
    return {"count": count, "size": total_size, "size_str": format_size(total_size)}


def get_chat_display_name(chat: dict) -> str:
    if chat.get("customTitle"):
        return chat["customTitle"]
    fp = chat.get("firstPrompt", "")
    if fp and fp != "No prompt":
        clean = re.sub(r"<[^>]+>", "", fp)
        clean = re.sub(r"[\r\n]+", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean:
            return clean
    return "No prompt"


# ── Commands ─────────────────────────────────────────────


def show_help():
    term_width = get_terminal_width()

    # Dynamic column widths for command list
    cols = [
        {"name": "Command", "min_width": 30, "flex": True},
        {"name": "Description", "min_width": 20, "flex": True},
    ]
    widths = format_table(cols)

    print()
    print("=== Chats Manager Help ===")
    print()
    print("Available commands:")
    print()

    commands = [
        ("/chats", "List all chats"),
        ("/chats [id]", "View chat details"),
        ("/chats rename [id] [name]", "Rename a chat"),
        ("/chats delete [id|days|all]", "Delete chat(s)"),
        ("/chats cache", "Clean caches"),
        ("/chats open [id]", "Show resume command"),
        ("/chats filter [project]", "Filter by project"),
        ("/chats commits", "Manage commit.md files"),
        ("/chats plans", "Manage plan files"),
        ("/chats help", "Show this help"),
    ]

    for cmd, desc in commands:
        print(f"  {cmd:<{widths['Command']}} {desc}")

    print()
    print("Examples:")
    print(f"  {truncate('/chats filter gswarm-api', term_width - 2)}")
    print(f"  {truncate('/chats delete 30            Delete chats older than 30 days', term_width - 2)}")
    print(f"  {truncate('/chats delete all           Delete all chats', term_width - 2)}")
    print(f"  {truncate('/chats delete abc123        Delete specific chat', term_width - 2)}")
    print(f"  {truncate('/chats rename abc123 \"Auth implementation\"', term_width - 2)}")
    print()


def show_chat_list(filter_project: str = "", limit: int = 30):
    chats = get_all_chats()

    if filter_project:
        chats = [c for c in chats if filter_project.lower() in get_project_display(
            c.get("projectPath", ""), c.get("gitBranch", "")).lower()]

    displayed = chats[:limit]
    total_chats = len(chats)
    total_projects = len(list(PROJECTS_DIR.glob("*/sessions-index.json"))) if PROJECTS_DIR.exists() else 0

    print()
    if filter_project:
        print(f"=== Chats matching '{filter_project}' (newest first) ===")
    else:
        print("=== Claude Code Chats (newest first) ===")
    print()

    # Dynamic column widths
    cols = [
        {"name": "ID", "min_width": 10, "flex": False},
        {"name": "Name", "min_width": 20, "flex": True},  # Primary flex
        {"name": "Modified", "min_width": 12, "flex": False},
        {"name": "Msgs", "min_width": 5, "flex": False},
        {"name": "Project", "min_width": 15, "flex": True},  # Secondary flex
    ]
    widths = format_table(cols)

    # Header
    header = f"{'ID':<{widths['ID']}}{'Name':<{widths['Name']}}{'Modified':<{widths['Modified']}}{'Msgs':<{widths['Msgs']}}Project"
    print(header)
    sep = f"{'-'*(widths['ID'])} {'-'*(widths['Name']-1)} {'-'*(widths['Modified']-1)} {'-'*(widths['Msgs']-1)} {'-'*(widths['Project'])}"
    print(sep)

    # Rows
    for chat in displayed:
        sid = chat.get("sessionId", "????????")[:8]
        raw_name = get_chat_display_name(chat)
        name = truncate(raw_name, widths["Name"])
        mod_str = format_relative_date(chat.get("modified", ""))
        msgs = str(chat.get("messageCount", 0))
        project = truncate(get_project_display(chat.get("projectPath", ""), chat.get("gitBranch", "")), widths["Project"])
        print(f"{sid:<{widths['ID']}}{name:<{widths['Name']}}{mod_str:<{widths['Modified']}}{msgs:<{widths['Msgs']}}{project}")

    print()
    print("Actions: rename [id] [name] | delete [id|days|all] | cache | open [id] | filter [project] | commits | plans | help")
    print()

    showing = len(displayed)
    filter_note = " (filtered)" if filter_project else ""
    print(f"Showing {showing} of {total_chats} chats across {total_projects} projects{filter_note}")


def show_chat_details(chat_id: str):
    chat = find_chat_by_id(chat_id)
    if not chat:
        print(f"Chat '{chat_id}' not found.")
        return

    full_id = chat["sessionId"]
    name = get_chat_display_name(chat)
    project = get_project_display(chat.get("projectPath", ""), chat.get("gitBranch", ""))
    created = format_relative_date(chat.get("created", ""))
    modified = format_relative_date(chat.get("modified", ""))
    msgs = chat.get("messageCount", 0)

    file_size = "?"
    fp = chat.get("fullPath", "")
    if fp and Path(fp).exists():
        file_size = format_size(Path(fp).stat().st_size)

    real_path = decode_project_path(chat.get("projectPath", ""))
    term_width = get_terminal_width()

    # Calculate label width (longest label + padding)
    label_width = 10  # "Modified:" is longest at 9 chars + 1 space
    value_width = term_width - label_width - 4  # 4 for indent

    print()
    print("=== Chat Details ===")
    print()
    print(f"  {'ID:':<{label_width}} {truncate(full_id, value_width)}")
    print(f"  {'Name:':<{label_width}} {truncate(name, value_width)}")
    print(f"  {'Project:':<{label_width}} {truncate(project, value_width)}")
    print(f"  {'Path:':<{label_width}} {truncate(real_path, value_width)}")
    print(f"  {'Created:':<{label_width}} {created} ({chat.get('created', '')})")
    print(f"  {'Modified:':<{label_width}} {modified} ({chat.get('modified', '')})")
    print(f"  {'Messages:':<{label_width}} {msgs}")
    print(f"  {'Size:':<{label_width}} {file_size}")
    if chat.get("gitBranch"):
        print(f"  {'Branch:':<{label_width}} {truncate(chat['gitBranch'], value_width)}")
    if chat.get("isSidechain"):
        print(f"  {'Type:':<{label_width}} Sidechain")
    print()
    resume_cmd = f'cd "{real_path}" && claude --resume {full_id}'
    print(f"Resume: {truncate(resume_cmd, term_width - 8)}")
    print()


# ── Rename ───────────────────────────────────────────────


def rename_chat_entry(chat_id: str, new_name: str):
    if not chat_id or not new_name:
        print("Usage: /chats rename [id] [name]")
        return

    if not PROJECTS_DIR.exists():
        print(f"Chat '{chat_id}' not found.")
        return

    for index_file in PROJECTS_DIR.glob("*/sessions-index.json"):
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            found = False
            for entry in data.get("entries", []):
                if entry.get("sessionId", "").startswith(chat_id):
                    entry["firstPrompt"] = new_name
                    entry["customTitle"] = new_name
                    found = True
                    break
            if found:
                index_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"Chat {chat_id} renamed to '{new_name}'")
                return
        except Exception as e:
            print(f"Error processing {index_file}: {e}")

    print(f"Chat '{chat_id}' not found.")


# ── Delete ───────────────────────────────────────────────


def remove_chat_preview(arg: str):
    if arg == "all":
        remove_all_chats_preview()
    elif arg.isdigit():
        remove_chats_by_age_preview(int(arg))
    else:
        remove_chat_by_id_preview(arg)


def remove_chat_by_id_preview(chat_id: str):
    chat = find_chat_by_id(chat_id)
    if not chat:
        print(f"Chat '{chat_id}' not found.")
        return

    name = get_chat_display_name(chat)
    file_size = "?"
    fp = chat.get("fullPath", "")
    if fp and Path(fp).exists():
        file_size = format_size(Path(fp).stat().st_size)

    term_width = get_terminal_width()
    label_width = 6  # "Name:" is longest at 5 chars + 1 space
    value_width = term_width - label_width - 4  # 4 for indent

    print()
    print("=== Delete Chat ===")
    print(f"  {'ID:':<{label_width}} {chat['sessionId'][:8]}")
    print(f"  {'Name:':<{label_width}} {truncate(name, value_width)}")
    print(f"  {'Size:':<{label_width}} {file_size}")
    print()
    print(f"PREVIEW_DELETE_ID:{chat['sessionId']}")


def remove_chat_by_id_confirm(chat_id: str):
    if not PROJECTS_DIR.exists():
        print(f"Chat '{chat_id}' not found.")
        return

    for index_file in PROJECTS_DIR.glob("*/sessions-index.json"):
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            target = None
            for entry in data.get("entries", []):
                if entry.get("sessionId", "").startswith(chat_id):
                    target = entry
                    break
            if target:
                fp = target.get("fullPath", "")
                if fp and Path(fp).exists():
                    Path(fp).unlink()
                data["entries"] = [e for e in data["entries"] if not e.get("sessionId", "").startswith(chat_id)]
                index_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                print(f"Deleted chat {target['sessionId'][:8]}")
                return
        except Exception as e:
            print(f"Error: {e}")

    print(f"Chat '{chat_id}' not found.")


def remove_chats_by_age_preview(days: int):
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    chats = get_all_chats()

    old = []
    for c in chats:
        try:
            mod = c.get("modified", "")
            dt = datetime.fromisoformat(mod.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                old.append(c)
        except Exception:
            pass

    if not old:
        print(f"No chats older than {days} days.")
        return

    total_size = 0
    for c in old:
        fp = c.get("fullPath", "")
        if fp and Path(fp).exists():
            total_size += Path(fp).stat().st_size

    print()
    print("=== Delete Old Chats ===")
    print(f"Found {len(old)} chats older than {days} days ({format_size(total_size)})")
    print()

    # Dynamic column widths (with 2-space indent)
    cols = [
        {"name": "ID", "min_width": 10, "flex": False},
        {"name": "Name", "min_width": 30, "flex": True},  # Primary flex
        {"name": "Modified", "min_width": 12, "flex": False},
    ]
    widths = format_table(cols)

    for c in old[:10]:
        sid = c.get("sessionId", "")[:8]
        raw_name = get_chat_display_name(c)
        name = truncate(raw_name, widths["Name"])
        mod = format_relative_date(c.get("modified", ""))
        print(f"  {sid:<{widths['ID']}}{name:<{widths['Name']}}{mod}")

    if len(old) > 10:
        print(f"  ... and {len(old) - 10} more")

    print()
    print(f"PREVIEW_DELETE_DAYS:{days}")


def remove_chats_by_age_confirm(days: int):
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    freed_bytes = 0

    if not PROJECTS_DIR.exists():
        print("No chats found.")
        return

    for index_file in PROJECTS_DIR.glob("*/sessions-index.json"):
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            keep = []
            for entry in data.get("entries", []):
                try:
                    mod = entry.get("modified", "")
                    dt = datetime.fromisoformat(mod.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        fp = entry.get("fullPath", "")
                        if fp and Path(fp).exists():
                            freed_bytes += Path(fp).stat().st_size
                            Path(fp).unlink()
                        deleted += 1
                        continue
                except Exception:
                    pass
                keep.append(entry)
            data["entries"] = keep
            index_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"Error processing {index_file}: {e}")

    print(f"Deleted {deleted} chats, freed {format_size(freed_bytes)}")


def remove_all_chats_preview():
    chats = get_all_chats()
    count = len(chats)
    total_size = 0
    for c in chats:
        fp = c.get("fullPath", "")
        if fp and Path(fp).exists():
            total_size += Path(fp).stat().st_size

    project_count = len(list(PROJECTS_DIR.glob("*/sessions-index.json"))) if PROJECTS_DIR.exists() else 0
    term_width = get_terminal_width()

    print()
    print("=== Delete ALL Chats ===")
    summary = f"Found {count} chats across {project_count} projects ({format_size(total_size)})"
    print(truncate(summary, term_width))
    print()
    print("PREVIEW_DELETE_ALL")


def remove_all_chats_confirm():
    deleted = 0
    freed_bytes = 0

    if not PROJECTS_DIR.exists():
        print("No chats found.")
        return

    for index_file in PROJECTS_DIR.glob("*/sessions-index.json"):
        try:
            data = json.loads(index_file.read_text(encoding="utf-8"))
            for entry in data.get("entries", []):
                fp = entry.get("fullPath", "")
                if fp and Path(fp).exists():
                    freed_bytes += Path(fp).stat().st_size
                    Path(fp).unlink()
                deleted += 1
            data["entries"] = []
            index_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            print(f"Error: {e}")

    print(f"Deleted {deleted} chats, freed {format_size(freed_bytes)}")


def remove_delete_confirm(arg: str):
    if arg == "all":
        remove_all_chats_confirm()
    elif arg.isdigit():
        remove_chats_by_age_confirm(int(arg))
    else:
        remove_chat_by_id_confirm(arg)


# ── Cleanup (post delete-all) ───────────────────────────


def show_cleanup_preview():
    items_config = [
        {"name": "screenshots", "path": CLAUDE_DIR / "skills" / "screen" / "screenshots", "glob": "screen-*.png"},
        {"name": "plans", "path": PLANS_DIR, "glob": "*.md"},
        {"name": "debug", "path": CLAUDE_DIR / "debug"},
        {"name": "todos", "path": CLAUDE_DIR / "todos"},
        {"name": "tasks", "path": CLAUDE_DIR / "tasks", "is_dir": True},
        {"name": "file-history", "path": CLAUDE_DIR / "file-history"},
        {"name": "paste-cache", "path": CLAUDE_DIR / "paste-cache"},
        {"name": "shell-snapshots", "path": CLAUDE_DIR / "shell-snapshots"},
        {"name": "session-env", "path": CLAUDE_DIR / "session-env"},
        {"name": "command-history", "path": CLAUDE_DIR / "command-history.log", "is_file": True},
        {"name": "ralph", "path": CLAUDE_DIR / "ralph"},
    ]

    print()
    print("=== Additional Cleanup ===")
    print()

    results = []
    for item in items_config:
        p = item["path"]
        if item.get("is_file"):
            if p.exists() and p.is_file():
                sz = p.stat().st_size
                results.append({"name": item["name"], "count": 1, "size": sz, "size_str": format_size(sz), "label": "1 file"})
        elif item.get("is_dir"):
            if p.exists():
                dirs = [d for d in p.iterdir() if d.is_dir()]
                stats = get_directory_stats(p)
                if dirs or stats["count"] > 0:
                    results.append({"name": item["name"], "count": len(dirs), "size": stats["size"], "size_str": stats["size_str"], "label": f"{len(dirs)} dirs"})
        else:
            if p.exists():
                stats = get_directory_stats(p)
                if stats["count"] > 0:
                    results.append({"name": item["name"], "count": stats["count"], "size": stats["size"], "size_str": stats["size_str"], "label": f"{stats['count']} files"})

    # Check ralph-legacy
    legacy_size = 0
    legacy_count = 0
    for lf in [CLAUDE_DIR / "ralph-state.json", CLAUDE_DIR / "ralph-activity.log"]:
        if lf.exists():
            legacy_size += lf.stat().st_size
            legacy_count += 1
    cp = CLAUDE_DIR / "ralph-checkpoints"
    if cp.exists():
        ls = get_directory_stats(cp)
        legacy_size += ls["size"]
        legacy_count += ls["count"]
    if legacy_count > 0:
        results.append({"name": "ralph-legacy", "count": legacy_count, "size": legacy_size, "size_str": format_size(legacy_size), "label": f"{legacy_count} files"})

    if not results:
        print("  Nothing to clean up.")
        return

    # Dynamic column widths (with 2-space indent)
    cols = [
        {"name": "Item", "min_width": 18, "flex": False},
        {"name": "Contents", "min_width": 12, "flex": False},
        {"name": "Size", "min_width": 10, "flex": True},
    ]
    widths = format_table(cols)

    # Header (indented)
    header = f"  {'Item':<{widths['Item']}} {'Contents':<{widths['Contents']}} Size"
    print(header)
    sep = f"  {'-'*widths['Item']} {'-'*(widths['Contents']-1)} {'-'*(widths['Size'])}"
    print(sep)

    # Rows
    for r in results:
        print(f"  {r['name']:<{widths['Item']}} {r['label']:<{widths['Contents']}} {r['size_str']}")

    total_size = sum(r["size"] for r in results)
    print()
    print(f"  Total cleanable: {format_size(total_size)}")
    print()

    names = ",".join(r["name"] for r in results)
    print(f"CLEANUP_ITEMS:{names}")


def remove_cleanup_item(item_name: str):
    freed_bytes = 0
    paths_map = {
        "screenshots": (CLAUDE_DIR / "skills" / "screen" / "screenshots", "screen-*.png"),
        "plans": (PLANS_DIR, "*.md"),
        "debug": (CLAUDE_DIR / "debug", None),
        "todos": (CLAUDE_DIR / "todos", None),
        "tasks": (CLAUDE_DIR / "tasks", None),
        "file-history": (CLAUDE_DIR / "file-history", None),
        "paste-cache": (CLAUDE_DIR / "paste-cache", None),
        "shell-snapshots": (CLAUDE_DIR / "shell-snapshots", None),
        "session-env": (CLAUDE_DIR / "session-env", None),
    }

    if item_name == "command-history":
        p = CLAUDE_DIR / "command-history.log"
        if p.exists():
            freed_bytes = p.stat().st_size
            p.unlink()
    elif item_name == "ralph":
        p = CLAUDE_DIR / "ralph"
        if p.exists():
            freed_bytes = get_directory_stats(p)["size"]
            for f in p.rglob("*"):
                if f.is_file():
                    try:
                        f.unlink()
                    except OSError:
                        pass
            # Remove empty dirs
            for d in sorted(p.rglob("*"), reverse=True):
                if d.is_dir():
                    try:
                        d.rmdir()
                    except OSError:
                        pass
    elif item_name == "ralph-legacy":
        for lf in [CLAUDE_DIR / "ralph-state.json", CLAUDE_DIR / "ralph-activity.log"]:
            if lf.exists():
                freed_bytes += lf.stat().st_size
                lf.unlink()
        cp = CLAUDE_DIR / "ralph-checkpoints"
        if cp.exists():
            freed_bytes += get_directory_stats(cp)["size"]
            shutil.rmtree(cp, ignore_errors=True)
    elif item_name in paths_map:
        path, glob_pattern = paths_map[item_name]
        if path.exists():
            freed_bytes = get_directory_stats(path)["size"]
            if glob_pattern:
                for f in path.glob(glob_pattern):
                    try:
                        f.unlink()
                    except OSError:
                        pass
            else:
                for f in path.rglob("*"):
                    if f.is_file():
                        try:
                            f.unlink()
                        except OSError:
                            pass
                for d in sorted(path.rglob("*"), reverse=True):
                    if d.is_dir():
                        try:
                            d.rmdir()
                        except OSError:
                            pass

    print(f"Cleaned {item_name} ({format_size(freed_bytes)})")


# ── Cache ────────────────────────────────────────────────


def clear_caches():
    dirs = [
        ("cache", CLAUDE_DIR / "cache"),
        ("debug", CLAUDE_DIR / "debug"),
        ("file-history", CLAUDE_DIR / "file-history"),
        ("shell-snapshots", CLAUDE_DIR / "shell-snapshots"),
        ("paste-cache", CLAUDE_DIR / "paste-cache"),
    ]

    print()
    print("Cleaning Claude Code caches...")
    print()

    # Dynamic column widths (with 2-space indent)
    cols = [
        {"name": "Directory", "min_width": 18, "flex": False},
        {"name": "Size", "min_width": 10, "flex": False},
        {"name": "Status", "min_width": 6, "flex": False},
    ]
    widths = format_table(cols)

    # Header (indented)
    header = f"  {'Directory':<{widths['Directory']}} {'Size':<{widths['Size']}} Status"
    print(header)
    sep = f"  {'-'*widths['Directory']} {'-'*(widths['Size']-1)} {'-'*widths['Status']}"
    print(sep)

    total_freed = 0
    for name, path in dirs:
        if path.exists():
            stats = get_directory_stats(path)
            # Remove contents
            for f in path.rglob("*"):
                if f.is_file():
                    try:
                        f.unlink()
                    except OSError:
                        pass
            for d in sorted(path.rglob("*"), reverse=True):
                if d.is_dir():
                    try:
                        d.rmdir()
                    except OSError:
                        pass
            total_freed += stats["size"]
            print(f"  {name + '/':<{widths['Directory']}} {stats['size_str']:<{widths['Size']}} OK")
        else:
            print(f"  {name + '/':<{widths['Directory']}} {'0 B':<{widths['Size']}} skip")

    print()
    print(f"  Freed {format_size(total_freed)} total")
    print()


# ── Open ─────────────────────────────────────────────────


def open_chat_resume(chat_id: str):
    chat = find_chat_by_id(chat_id)
    if not chat:
        print(f"Chat '{chat_id}' not found.")
        return

    name = get_chat_display_name(chat)
    real_path = decode_project_path(chat.get("projectPath", ""))
    term_width = get_terminal_width()

    label_width = 9  # "Project:" is longest at 8 chars + 1 space
    value_width = term_width - label_width - 4  # 4 for indent

    print()
    print("=== Resume Chat ===")
    print()
    print(f"  {'ID:':<{label_width}} {truncate(chat['sessionId'], value_width)}")
    print(f"  {'Name:':<{label_width}} {truncate(name, value_width)}")
    print(f"  {'Project:':<{label_width}} {truncate(real_path, value_width)}")
    print()
    print("  Command:")
    resume_cmd = f'cd "{real_path}" && claude --resume {chat["sessionId"]}'
    print(f"  {truncate(resume_cmd, term_width - 4)}")
    print()


# ── Commits Manager ──────────────────────────────────────


def _find_commit_files() -> list[Path]:
    search_paths = [
        Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / d
        for d in ("projects", "repos", "code", "work", "Desktop")
    ]
    commit_files = []
    for base in search_paths:
        if base.exists():
            for cf in base.rglob("commit.md"):
                if ".claude" in cf.parts:
                    commit_files.append(cf)
    local = CLAUDE_DIR / "commit.md"
    if local.exists():
        commit_files.append(local)
    return commit_files


def show_commits_manager(arg1: str = "", arg2: str = ""):
    commit_files = _find_commit_files()

    if arg1 == "delete" and arg2 == "all":
        count = len(commit_files)
        total_size = sum(f.stat().st_size for f in commit_files if f.exists())
        print()
        print("=== Delete All Commit Files ===")
        print(f"Found {count} commit.md files ({format_size(total_size)})")
        print()
        print("PREVIEW_DELETE_COMMITS_ALL")
        return

    if not commit_files:
        print()
        print("No commit.md files found.")
        print()
        return

    print()
    print("=== Commit Files ===")
    print()

    # Dynamic column widths (with 2-space indent)
    cols = [
        {"name": "#", "min_width": 4, "flex": False},
        {"name": "Project", "min_width": 20, "flex": True},  # Primary flex
        {"name": "Size", "min_width": 8, "flex": False},
        {"name": "Updated", "min_width": 12, "flex": True},  # Secondary flex
    ]
    widths = format_table(cols)

    # Header (indented)
    header = f"  {'#':<{widths['#']}}{'Project':<{widths['Project']}}{'Size':<{widths['Size']}}Last Updated"
    print(header)
    sep = f"  {'-'*(widths['#']-1)} {'-'*(widths['Project']-1)} {'-'*(widths['Size']-1)} {'-'*(widths['Updated'])}"
    print(sep)

    # Rows
    for i, cf in enumerate(commit_files, 1):
        project = cf.parent.name
        if project == ".claude":
            project = cf.parent.parent.name
        project = truncate(project, widths["Project"])
        size = format_size(cf.stat().st_size)
        try:
            mod = format_relative_date(datetime.fromtimestamp(cf.stat().st_mtime, tz=timezone.utc).isoformat())
        except Exception:
            mod = "unknown"
        print(f"  {str(i):<{widths['#']}}{project:<{widths['Project']}}{size:<{widths['Size']}}{mod}")

    print()
    print("Actions: [d N] Delete specific | [a] Delete All | [q] Quit")
    print()

    paths = "|".join(str(f) for f in commit_files)
    print(f"COMMIT_FILES:{paths}")


def remove_all_commit_files():
    commit_files = _find_commit_files()
    deleted = 0
    for cf in commit_files:
        try:
            cf.unlink()
            deleted += 1
        except OSError:
            pass
    print(f"Deleted {deleted} commit.md files")


# ── Plans Manager ────────────────────────────────────────


def show_plans_manager(arg1: str = "", arg2: str = ""):
    if not PLANS_DIR.exists():
        print()
        print("No plans directory found.")
        return

    plan_files = sorted(PLANS_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)

    if arg1 == "delete" and arg2 == "all":
        count = len(plan_files)
        total_size = sum(f.stat().st_size for f in plan_files)
        print()
        print("=== Delete All Plan Files ===")
        print(f"Found {count} plan files ({format_size(total_size)})")
        print()
        print("PREVIEW_DELETE_PLANS_ALL")
        return

    if not plan_files:
        print()
        print("No plan files found.")
        return

    print()
    print("=== Plan Files ===")
    print()

    # Dynamic column widths (with 2-space indent)
    cols = [
        {"name": "#", "min_width": 4, "flex": False},
        {"name": "Filename", "min_width": 25, "flex": True},  # Primary flex
        {"name": "Modified", "min_width": 14, "flex": False},
        {"name": "Size", "min_width": 7, "flex": False},
        {"name": "Project", "min_width": 15, "flex": True},  # Secondary flex
    ]
    widths = format_table(cols)

    # Header (indented)
    header = f"  {'#':<{widths['#']}}{'Filename':<{widths['Filename']}}{'Modified':<{widths['Modified']}}{'Size':<{widths['Size']}}Project"
    print(header)
    sep = f"  {'-'*(widths['#']-1)} {'-'*(widths['Filename']-1)} {'-'*(widths['Modified']-1)} {'-'*(widths['Size']-1)} {'-'*(widths['Project'])}"
    print(sep)

    # Rows
    for i, pf in enumerate(plan_files, 1):
        name = truncate(pf.name, widths["Filename"])
        try:
            mod = format_relative_date(datetime.fromtimestamp(pf.stat().st_mtime, tz=timezone.utc).isoformat())
        except Exception:
            mod = "unknown"
        size = format_size(pf.stat().st_size)

        # Detect project from content
        project = ""
        try:
            lines = pf.read_text(encoding="utf-8").splitlines()[:10]
            for line in lines:
                m = re.search(r"\*\*Session:\*\*\s*(.+)", line)
                if m:
                    project = m.group(1).strip()
                    break
        except Exception:
            pass
        project = truncate(project, widths["Project"])

        print(f"  {str(i):<{widths['#']}}{name:<{widths['Filename']}}{mod:<{widths['Modified']}}{size:<{widths['Size']}}{project}")

    print()
    print("Actions: [d N] Delete specific | [a] Delete All | [q] Quit")
    print()

    paths = "|".join(str(f) for f in plan_files)
    print(f"PLAN_FILES:{paths}")


def remove_all_plan_files():
    if PLANS_DIR.exists():
        plan_files = list(PLANS_DIR.glob("*.md"))
        count = len(plan_files)
        for f in plan_files:
            try:
                f.unlink()
            except OSError:
                pass
        print(f"Deleted {count} plan files")
    else:
        print("No plans directory found.")


# ── Command Router ───────────────────────────────────────


def main():
    args = sys.argv[1:]
    command = args[0] if args else "list"
    arg1 = args[1] if len(args) > 1 else ""
    arg2 = " ".join(args[2:]) if len(args) > 2 else ""

    match command:
        case "list":
            show_chat_list()
        case "help":
            show_help()
        case "filter":
            show_chat_list(filter_project=arg1)
        case "rename":
            rename_chat_entry(arg1, arg2)
        case "delete":
            remove_chat_preview(arg1)
        case "delete-confirm":
            remove_delete_confirm(arg1)
        case "cleanup-preview":
            show_cleanup_preview()
        case "cleanup-item":
            remove_cleanup_item(arg1)
        case "cache":
            clear_caches()
        case "open":
            open_chat_resume(arg1)
        case "commits":
            show_commits_manager(arg1, arg2)
        case "commits-delete-all":
            remove_all_commit_files()
        case "plans":
            show_plans_manager(arg1, arg2)
        case "plans-delete-all":
            remove_all_plan_files()
        case _:
            if re.match(r"^[a-f0-9]{8,}$", command):
                show_chat_details(command)
            else:
                print(f"Unknown command: {command}")
                print("Run '/chats help' for usage.")


if __name__ == "__main__":
    main()
