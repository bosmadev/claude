---
name: serena-workflow
context: fork
description: Guide for using Serena semantic code tools effectively. Shows optimal workflows for code exploration, editing, and impact analysis.
user-invocable: true
---

# Serena Workflow Guide

## Tool Selection Matrix

| Task | Serena Tool | Native Alternative | When to Use Serena |
|------|------------|-------------------|-------------------|
| Find function/class | `find_symbol` | Grep | Always prefer Serena |
| File structure | `get_symbols_overview` | Read full file | Always prefer Serena |
| All callers | `find_referencing_symbols` | Grep for name | Always prefer Serena |
| Rename across files | `rename_symbol` | Multi-file Edit | Always prefer Serena |
| Replace function body | `replace_symbol_body` | Edit tool | When replacing entire symbol |
| Insert after symbol | `insert_after_symbol` | Edit tool | When adding new code |
| Regex in files | `search_for_pattern` | Grep | When need code context |
| Read specific lines | - | Edit/Read | When Serena overkill |
| Find string literal | - | Grep | When not a symbol |

## Exploration Workflow

```
1. get_symbols_overview(file)     → See all symbols in file
2. find_symbol(pattern, depth=1)  → Get methods of a class
3. find_symbol(pattern, body=True)→ Read specific method
4. find_referencing_symbols()     → Who calls this?
```

## Editing Workflow

```
1. find_symbol(target, body=True)        → Read current code
2. find_referencing_symbols(target)      → Check impact
3. replace_symbol_body(target, new_code) → Make the edit
4. find_referencing_symbols(target)      → Verify no breakage
```

## Memory Patterns

Use Serena memory for persistent project knowledge:

```
write_memory("architecture", "Key decisions: ...")
write_memory("symbol-map", "Critical symbols and their locations")
read_memory("architecture")  → Recall in new session
```

### When to Write Memory
- After discovering architectural patterns
- When mapping complex symbol relationships
- Before ending a session with unfinished work
- When making decisions that affect future changes

## Reflection Checkpoints

Use these at critical moments:

| Checkpoint | When |
|-----------|------|
| `think_about_collected_information` | After gathering context, before editing |
| `think_about_task_adherence` | Before making changes, verify alignment |
| `think_about_whether_you_are_done` | Before signaling completion |

## Name Path Patterns

Serena uses `name_path` for symbol identification:

```
Foo                  → Class Foo
Foo/__init__         → Constructor of Foo
Foo/bar              → Method bar in class Foo
module/function      → Top-level function in module
```

Use `substring_matching=True` when unsure of exact name.
