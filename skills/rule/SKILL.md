---
name: rule
description: Manage behavior rules by directly editing settings.json permissions (replaced /quality rule)
argument-hint: "add | list | remove [pattern] | help"
user-invocable: true
context: fork
---

# Rule Management Skill

When invoked, immediately output: **SKILL_STARTED:** rule

Manage behavior rules through direct `settings.json` permissions editing.

## Commands

| Command | Description |
|---------|-------------|
| `/rule add` | Add a new behavior rule with confirmation |
| `/rule list` | List all current permission rules |
| `/rule remove [pattern]` | Remove a specific rule pattern |
| `/rule help` | Show usage and examples |

## Workflow

### Adding Rules (`/rule add`)

Interactive flow with AskUserQuestion at each step:

1. **Ask for rule type:**
   - AskUserQuestion: "What type of rule do you want to add?"
   - Options:
     - Block bash command (adds to `permissions.deny`)
     - Block file pattern (adds to `permissions.deny`)
     - Require confirmation (adds to `permissions.ask`)

2. **Ask for description:**
   - AskUserQuestion: "Describe the rule in natural language"
   - Examples:
     - "Never use rm -rf"
     - "Always ask before deleting files"
     - "Block curl downloads"

3. **Translate to pattern:**
   - Convert natural language to `settings.json` permission pattern
   - Show the generated pattern to user

4. **Confirm before applying:**
   - AskUserQuestion: "Adding rule to [BLOCK/ASK]: [pattern]. Accept?" [Yes/No]
   - If Yes: Write to settings.json
   - If No: Abort and explain how to try again

5. **Write to settings.json:**
   - Read current `~/.claude/settings.json`
   - Add pattern to appropriate section (`permissions.deny` or `permissions.ask`)
   - Write updated JSON back to file
   - Confirm success

### Listing Rules (`/rule list`)

Display all current permission rules:

```bash
# Read settings.json
python -c "import json; data=json.load(open('~/.claude/settings.json')); print('ALLOW:', data['permissions']['allow']); print('DENY:', data['permissions']['deny']); print('ASK:', data['permissions']['ask'])"
```

Format output as readable table:

| Type | Pattern | Description |
|------|---------|-------------|
| BLOCK | `Bash(rm -rf:*)` | Never allow rm -rf commands |
| ASK | `Bash(curl:*)` | Require confirmation for curl |

### Removing Rules (`/rule remove [pattern]`)

1. If pattern not provided, list all rules and ask which to remove
2. AskUserQuestion: "Remove rule [pattern]? This will immediately update settings.json." [Yes/No]
3. If Yes:
   - Read settings.json
   - Remove pattern from deny/ask lists
   - Write updated JSON
   - Confirm removal
4. If No: Abort

## Translation Examples

### Natural Language → Permission Pattern

| User Input | Rule Type | Generated Pattern |
|------------|-----------|-------------------|
| "Never use rm -rf" | Block | `Bash(rm -rf:*)` |
| "Block recursive deletion" | Block | `Bash(rm -rf:*)` |
| "Always ask before deleting files" | Ask | `Bash(rm:*)`, `Bash(del:*)` |
| "Block curl downloads" | Block | `Bash(curl:*)` |
| "Require confirmation for git push" | Ask | `Bash(git push:*)` |
| "Block force push" | Block | `Bash(git push --force:*)`, `Bash(git push -f:*)` |
| "Never allow file downloads" | Block | `Bash(curl:*)`, `Bash(wget:*)` |

### Pattern Syntax

Permission patterns follow the format: `Tool(command:filter)`

**Components:**
- `Tool`: The tool name (e.g., `Bash`, `Write`, `Edit`)
- `command`: The command or operation (e.g., `rm`, `git push`)
- `filter`: Wildcard pattern (`:*` matches anything)

**Examples:**
- `Bash(rm -rf:*)` - Block all rm -rf commands
- `Bash(git push:*)` - Ask for all git push operations
- `Write` - Block all Write tool usage
- `Bash(curl * | sh:*)` - Block piped curl commands

## Help Command

When user runs `/rule help`:

```
/rule - Manage behavior rules via settings.json

Usage:
  /rule add              Interactive rule creation with confirmation
  /rule list             Display all permission rules
  /rule remove [pattern] Remove a specific rule
  /rule help             Show this help

How It Works:
  Rules are stored directly in ~/.claude/settings.json under permissions:
  - permissions.deny  → Blocked operations (never allowed)
  - permissions.ask   → Confirmation required before execution
  - permissions.allow → Explicitly allowed operations

Rule Types:
  Block bash command    → permissions.deny with Bash() pattern
  Block file pattern    → permissions.deny with file wildcards
  Require confirmation  → permissions.ask with command pattern

Examples:
  /rule add
    → Type: Block bash command
    → Description: "Never use rm -rf"
    → Pattern: Bash(rm -rf:*)
    → Confirm: "Adding rule to BLOCK: Bash(rm -rf:*). Accept?" [Yes]
    → Result: Added to permissions.deny

  /rule list
    → Shows all current allow/deny/ask rules from settings.json

  /rule remove "Bash(rm -rf:*)"
    → Removes the specified pattern after confirmation

Translation Guide:
  "Never [action]"           → permissions.deny
  "Always ask before [action]" → permissions.ask
  "Block [tool]"             → permissions.deny with Tool pattern
  "Require confirmation"      → permissions.ask

Common Patterns:
  Bash(rm -rf:*)              Block recursive deletion
  Bash(curl:*)                Block/ask for curl usage
  Bash(git push --force:*)    Block force push
  Bash(dd:*)                  Block disk operations
  Write                       Block all file writes

Notes:
  - Changes take effect immediately (no restart needed)
  - Patterns use wildcards: * matches anything
  - Multiple patterns can be added for one rule
  - Use /rule list to verify your changes
```

## Implementation Details

### Read settings.json

```bash
# Python for safe JSON handling (cross-platform)
python -c "
import json
from pathlib import Path

# Validate that settings.json is in user home directory (security)
settings_path = Path.home() / '.claude' / 'settings.json'

# Security check: ensure path is within user's home directory
if not settings_path.resolve().is_relative_to(Path.home()):
    raise ValueError('Security: settings.json must be in user home directory')

with open(settings_path, 'r') as f:
    settings = json.load(f)
print(json.dumps(settings.get('permissions', {}), indent=2))
"
```

**Security validation:** The script verifies that `settings.json` resolves to a path within the user's home directory. This prevents path traversal attacks where a malicious actor could manipulate environment variables or symlinks to point to a system-wide config file.

### Write settings.json

```bash
# Python for atomic JSON updates (cross-platform)
python -c "
import json
import tempfile
import shutil
from pathlib import Path

settings_path = Path.home() / '.claude' / 'settings.json'

# Security check: ensure path is within user's home directory
if not settings_path.resolve().is_relative_to(Path.home()):
    raise ValueError('Security: settings.json must be in user home directory')

with open(settings_path, 'r') as f:
    settings = json.load(f)

# Add to deny list
if 'permissions' not in settings:
    settings['permissions'] = {'deny': [], 'ask': []}
settings['permissions']['deny'].append('Bash(rm -rf:*)')

# Atomic write via tempfile
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', dir=settings_path.parent, delete=False) as tmp:
    json.dump(settings, tmp, indent=2)
    tmp_path = Path(tmp.name)
shutil.move(str(tmp_path), str(settings_path))
"
```

### Remove Pattern

```bash
# Python for safe removal (cross-platform)
python -c "
import json
import tempfile
import shutil
from pathlib import Path

pattern = 'Bash(rm -rf:*)'
settings_path = Path.home() / '.claude' / 'settings.json'

with open(settings_path, 'r') as f:
    settings = json.load(f)

# Remove from deny/ask lists
perms = settings.get('permissions', {})
if pattern in perms.get('deny', []):
    perms['deny'].remove(pattern)
if pattern in perms.get('ask', []):
    perms['ask'].remove(pattern)

# Atomic write
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', dir=settings_path.parent, delete=False) as tmp:
    json.dump(settings, tmp, indent=2)
    tmp_path = Path(tmp.name)
shutil.move(str(tmp_path), str(settings_path))
"
```

## Error Handling

| Error | Action |
|-------|--------|
| settings.json not found | Display error with path, suggest checking installation |
| Invalid JSON | Backup file, report corruption, suggest manual fix |
| Pattern already exists | Show existing rule, ask if user wants to keep or modify |
| Empty pattern | Reject and ask for valid input |
| Invalid permission type | Show valid types (deny/ask/allow) and retry |
| Permission denied writing file | Check file permissions, suggest running with elevated rights |

## Safety Rules

- **Always use AskUserQuestion before writing** to settings.json
- **Show the exact pattern** that will be added/removed
- **Create backup** of settings.json before modifications
- **Validate JSON** after writing to ensure file integrity
- **Never remove** core allow patterns that Claude Code needs
- **Warn user** if they're about to block critical operations

## Migration from /quality rule

Users coming from `/quality rule` should use `/rule add` instead:

```
Old: /quality rule "Never use rm -rf"
New: /rule add
     → Follow interactive prompts
     → Same result, better UX with confirmation
```

## Integration with Permissions System

This skill directly modifies the Claude Code permissions system:

- **Immediate effect**: Changes apply to current session
- **Persistent**: Rules survive restarts
- **Native integration**: Uses built-in permission enforcement
- **No extra files**: No `behavior-rules.json` needed

## Example Session

```
User: /rule add

Skill: What type of rule do you want to add?
  1. Block bash command
  2. Block file pattern
  3. Require confirmation

User: 1

Skill: Describe the rule in natural language

User: Never use rm -rf

Skill: I'll translate this to: Bash(rm -rf:*)

Adding rule to BLOCK: Bash(rm -rf:*). Accept? [Yes/No]

User: Yes

Skill: ✅ Rule added to permissions.deny
Pattern: Bash(rm -rf:*)
Location: ~/.claude/settings.json

The rule is now active and will block all rm -rf commands.
```

## Backup Strategy

Before any modification, create a timestamped backup using Python (cross-platform):

```bash
# Python for cross-platform backup (Windows + Unix)
python -c "
import shutil
from pathlib import Path
from datetime import datetime

settings_path = Path.home() / '.claude' / 'settings.json'

# Security check
if not settings_path.resolve().is_relative_to(Path.home()):
    raise ValueError('Security: settings.json must be in user home directory')

# Create timestamped backup
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
backup_path = settings_path.parent / f'settings.json.backup.{timestamp}'
shutil.copy2(settings_path, backup_path)

# Keep last 5 backups only
backups = sorted(settings_path.parent.glob('settings.json.backup.*'), key=lambda p: p.stat().st_mtime, reverse=True)
for old_backup in backups[5:]:
    old_backup.unlink()

print(f'Backup created: {backup_path}')
"
```

**Cross-platform compatibility:** Uses Python's `Path` and `shutil` instead of Unix commands (`cp`, `ls`, `tail`, `xargs rm`) to work on both Windows and Unix systems.

## Validation

After writing settings.json:

1. Verify JSON is valid (can be parsed)
2. Verify permissions object exists
3. Verify allow/deny/ask arrays exist
4. Verify no duplicate patterns
5. Verify pattern syntax is valid

If validation fails:
- Restore from backup
- Report error to user
- Suggest manual inspection
