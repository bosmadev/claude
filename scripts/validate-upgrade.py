#!/usr/bin/env python3
"""Validate all CC 2.1.49 upgrade changes are intact.

Run: python scripts/validate-upgrade.py
Exit 0 = all checks pass, Exit 1 = failures found.
"""
import sys
import os
import json
import subprocess
import stat
import tempfile
from pathlib import Path

# Ensure Unicode output works on Windows (CP1252 terminal)
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

CLAUDE_HOME = Path.home() / ".claude"
PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  \u2713 {name}")
        PASS += 1
    else:
        print(f"  \u2717 {name}" + (f": {detail}" if detail else ""))
        FAIL += 1


def section(title):
    print(f"\n[{title}]")


def main():
    print("=== CC 2.1.49 Upgrade Validation ===\n")

    # ── 1. commit-msg hook exists and is executable ──────────────────────────
    section("Git Hooks")
    hook_path = CLAUDE_HOME / ".git" / "hooks" / "commit-msg"
    hook_exists = hook_path.exists()
    check("commit-msg hook exists", hook_exists,
          f"expected at {hook_path}")

    if hook_exists:
        mode = hook_path.stat().st_mode
        is_exec = bool(mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        # On Windows NTFS, chmod is a no-op for git hooks — git itself handles execution
        # via the shebang. Accept either executable bit OR Windows platform.
        on_windows = sys.platform == "win32" or os.name == "nt"
        check("commit-msg hook is executable (or Windows NTFS)",
              is_exec or on_windows,
              f"mode={oct(mode)}, run: chmod +x {hook_path}")

    # ── 2. commit-msg injects Build ID on main branch ────────────────────────
    section("Build ID Injection")
    if hook_exists:
        hook_content = hook_path.read_text(encoding="utf-8")
        # Verify the hook contains Build ID injection logic
        has_build_id_logic = (
            "Build" in hook_content and
            "BRANCH" in hook_content and
            "main" in hook_content
        )
        check("commit-msg hook contains Build ID injection logic",
              has_build_id_logic,
              "hook is missing Build ID/branch injection code")

        # Test hook execution using Git Bash on Windows, bash elsewhere
        git_bash = Path("C:/Program Files/Git/bin/bash.exe")
        bash_cmd = str(git_bash) if git_bash.exists() else "bash"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                        delete=False) as f:
            f.write("fix: some bug description\n")
            tmp = f.name
        try:
            env = os.environ.copy()
            env["GIT_DIR"] = str(CLAUDE_HOME / ".git")
            result = subprocess.run(
                [bash_cmd, str(hook_path), tmp],
                capture_output=True, text=True, env=env, timeout=10
            )
            # Filter out known WSL noise lines
            stderr_real_errors = [
                line for line in result.stderr.splitlines()
                if line and not line.startswith("wsl:") and
                "<3>WSL" not in line
            ]
            hook_ok = result.returncode == 0 and not stderr_real_errors
            check("commit-msg hook runs without error",
                  hook_ok,
                  f"exit={result.returncode} stderr={'|'.join(stderr_real_errors[:3])}")
        finally:
            os.unlink(tmp)
    else:
        check("commit-msg hook contains Build ID injection logic", False,
              "hook missing")
        check("commit-msg hook runs without error", False, "hook missing")

    # ── 3. settings.json has git commit in allow list ─────────────────────────
    section("settings.json Permissions")
    settings_path = CLAUDE_HOME / "settings.json"
    settings = {}
    if settings_path.exists():
        with open(settings_path) as f:
            settings = json.load(f)

    allow_list = settings.get("permissions", {}).get("allow", [])
    ask_list = settings.get("permissions", {}).get("ask", [])

    check("Bash(git commit:*) in allow list",
          "Bash(git commit:*)" in allow_list,
          "missing from permissions.allow")

    # ── 4. git reset in ask list (not allow) ─────────────────────────────────
    check("Bash(git reset:*) in ask list",
          "Bash(git reset:*)" in ask_list,
          "should be in permissions.ask")

    check("Bash(git reset:*) NOT in allow list",
          "Bash(git reset:*)" not in allow_list,
          "git reset should not be freely allowed")

    # ── 5. keybindings.json has shift+enter → chat:newline ───────────────────
    section("Keybindings")
    kb_path = CLAUDE_HOME / "keybindings.json"
    kb_has_shift_enter = False
    if kb_path.exists():
        with open(kb_path) as f:
            kb = json.load(f)
        for ctx in kb.get("bindings", []):
            bindings = ctx.get("bindings", {})
            if bindings.get("shift+enter") == "chat:newline":
                kb_has_shift_enter = True
                break
    check("keybindings.json: shift+enter → chat:newline",
          kb_has_shift_enter,
          f"not found in {kb_path}")

    # ── 6. ConfigChange hook registered ──────────────────────────────────────
    section("Hook Registrations")
    hooks_section = settings.get("hooks", {})
    config_change_hooks = hooks_section.get("ConfigChange", [])
    config_change_registered = any(
        "config-change.py" in h.get("command", "")
        for entry in config_change_hooks
        for h in entry.get("hooks", [])
    )
    check("ConfigChange: config-change.py registered",
          config_change_registered,
          "hooks.ConfigChange missing config-change.py")

    # ── 7. env-setup.py registered in SessionStart ───────────────────────────
    session_start_hooks = hooks_section.get("SessionStart", [])
    env_setup_registered = any(
        "env-setup.py" in h.get("command", "")
        for entry in session_start_hooks
        for h in entry.get("hooks", [])
    )
    check("SessionStart: env-setup.py registered",
          env_setup_registered,
          "hooks.SessionStart missing env-setup.py")

    # ── 8. /memoryreview skill exists ────────────────────────────────────────
    section("Skills + Scripts")
    skill_path = CLAUDE_HOME / "skills" / "memoryreview" / "SKILL.md"
    check("/memoryreview skill exists (skills/memoryreview/SKILL.md)",
          skill_path.exists(),
          f"not found: {skill_path}")

    # ── 9. memoryreview.py exists and runs ───────────────────────────────────
    mr_path = CLAUDE_HOME / "scripts" / "memoryreview.py"
    mr_exists = mr_path.exists()
    check("scripts/memoryreview.py exists", mr_exists, f"not found: {mr_path}")

    if mr_exists:
        result = subprocess.run(
            [sys.executable, str(mr_path), "help"],
            capture_output=True, text=True, timeout=30
        )
        check("python scripts/memoryreview.py help exits 0",
              result.returncode == 0,
              f"exit={result.returncode} stderr={result.stderr[:200]}")
    else:
        check("python scripts/memoryreview.py help exits 0", False,
              "script missing")

    # ── 10. guards.py has track_plan_rename function ──────────────────────────
    section("Code Checks")
    guards_path = CLAUDE_HOME / "scripts" / "guards.py"
    if guards_path.exists():
        content = guards_path.read_text(encoding="utf-8")
        check("scripts/guards.py has track_plan_rename function",
              "track_plan_rename" in content,
              "function not found in guards.py")
    else:
        check("scripts/guards.py has track_plan_rename function", False,
              f"guards.py not found at {guards_path}")

    # ── 11. compat.py get_claude_home() returns path ending with .claude ──────
    compat_path = CLAUDE_HOME / "scripts" / "compat.py"
    if compat_path.exists():
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, r'" +
             str(CLAUDE_HOME / "scripts") +
             "'); from compat import get_claude_home; p = get_claude_home(); "
             "print(p); assert str(p).endswith('.claude'), f'Got: {p}'"],
            capture_output=True, text=True, timeout=10
        )
        check("compat.py get_claude_home() returns path ending with .claude",
              result.returncode == 0,
              result.stderr.strip()[:200] if result.returncode != 0 else "")
    else:
        check("compat.py get_claude_home() returns path ending with .claude",
              False, f"compat.py not found at {compat_path}")

    # ── 12. CLAUDE.md contains 2.1.49 (upgrade was done) ────────────────────
    section("Version References")
    claude_md = CLAUDE_HOME / "CLAUDE.md"
    if claude_md.exists():
        content = claude_md.read_text(encoding="utf-8")
        check("CLAUDE.md contains '2.1.49'",
              "2.1.49" in content,
              "expected version string not found — upgrade incomplete?")
        check("CLAUDE.md does NOT contain old '2.1.41' only",
              "2.1.41" not in content or "2.1.49" in content,
              "still references 2.1.41 without 2.1.49")
    else:
        check("CLAUDE.md contains '2.1.49'", False, "CLAUDE.md not found")
        check("CLAUDE.md does NOT contain old '2.1.41' only", False, "CLAUDE.md not found")

    # ── 13. README.md has /memoryreview section ───────────────────────────────
    section("README.md Accuracy")
    readme_path = CLAUDE_HOME / "README.md"
    if readme_path.exists():
        readme = readme_path.read_text(encoding="utf-8")
        check("README.md contains '/memoryreview' section",
              "/memoryreview" in readme,
              "no /memoryreview mention in README.md")

        # ── 14. README.md does NOT contain Sonnet 4.5 ────────────────────────
        check("README.md does NOT contain 'Sonnet 4.5'",
              "Sonnet 4.5" not in readme,
              "README.md still references old Sonnet 4.5")
    else:
        check("README.md contains '/memoryreview' section", False,
              "README.md not found")
        check("README.md does NOT contain 'Sonnet 4.5'", False,
              "README.md not found")

    # ── 15. .gitignore contains backups/ ─────────────────────────────────────
    section("Git Configuration")
    gitignore_path = CLAUDE_HOME / ".gitignore"
    if gitignore_path.exists():
        gi_content = gitignore_path.read_text(encoding="utf-8")
        check(".gitignore contains 'backups/'",
              "backups/" in gi_content,
              "backups/ not in .gitignore — backup files may be tracked")
    else:
        check(".gitignore contains 'backups/'", False,
              ".gitignore not found")

    # ── 16. settings.json spinnerTipsOverride has ≥10 tips ───────────────────
    section("Settings Configuration")
    spinner_tips = settings.get("spinnerTipsOverride", {}).get("tips", [])
    check("settings.json spinnerTipsOverride has ≥10 tips",
          len(spinner_tips) >= 10,
          f"only {len(spinner_tips)} tips found (need ≥10)")

    # ── 17. hooks/git.py has teammate git commit blocking logic ───────────────
    section("Teammate Git Commit Guard")
    git_hook_path = CLAUDE_HOME / "hooks" / "git.py"
    if git_hook_path.exists():
        git_hook_content = git_hook_path.read_text(encoding="utf-8")
        has_blocking = (
            "check_teammate_git_commit" in git_hook_content or
            "CLAUDE_CODE_TASK_LIST_ID" in git_hook_content
        )
        check("hooks/git.py has teammate git commit blocking logic",
              has_blocking,
              "check_teammate_git_commit or CLAUDE_CODE_TASK_LIST_ID not found")
    else:
        check("hooks/git.py has teammate git commit blocking logic", False,
              f"git.py not found at {git_hook_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 45}")
    total = PASS + FAIL
    print(f"Results: {PASS}/{total} passed, {FAIL} failed")
    if FAIL == 0:
        print("All checks passed — upgrade is intact.")
    else:
        print(f"WARNING: {FAIL} check(s) failed — review output above.")
    sys.exit(1 if FAIL > 0 else 0)


if __name__ == "__main__":
    main()
