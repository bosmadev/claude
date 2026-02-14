---
name: test
description: Unified test framework integration - generate tests, run coverage, mutation testing. Auto-detects vitest (TypeScript) or pytest (Python) based on file extension.
user-invocable: true
context: fork
argument-hint: "[generate <file>|coverage|mutate <file>|all|help]"
when_to_use: Use when generating test files, running test coverage reports, performing mutation testing, or running all test suites sequentially.
---

# Unified Test Skill

## EXECUTE IMMEDIATELY — DO NOT ANALYZE

**CRITICAL: When `/test` is invoked, execute the appropriate workflow below IMMEDIATELY. Do NOT research testing frameworks, do NOT analyze test patterns, do NOT write reports. JUST DO THE STEPS.**

**Output first:** `**SKILL_STARTED:** test`

---

## Subcommand Reference

| Command | Action |
|---------|--------|
| `/test generate <file>` | Generate test file for source file (auto-detect: .ts/.tsx → vitest, .py → pytest) |
| `/test coverage` | Run coverage report (auto-detect: vitest --coverage or pytest --cov) |
| `/test mutate <file>` | Mutation testing via AST manipulation + test run |
| `/test all` | Run all test suites in sequence (vitest → pytest) |
| `/test help` | Show help text |

---

## /test generate <file>

Generate a test file for the specified source file using auto-detected framework.

**Steps:**

1. **Detect file type**
   ```bash
   FILE="$1"
   EXT="${FILE##*.}"
   ```

2. **Read source file**
   ```bash
   # Read the source code
   cat "$FILE"
   ```

3. **Analyze source with AST**
   - TypeScript/TSX: Use regex/pattern matching to extract:
     - Exported functions
     - Exported classes
     - React components
     - Type definitions
   - Python: Use Python `ast` module to extract:
     - Functions (via `ast.FunctionDef`)
     - Classes (via `ast.ClassDef`)
     - Imports

4. **Generate test file**
   - TypeScript/TSX → `<filename>.test.ts` or `<filename>.test.tsx`
   - Python → `test_<filename>.py`

5. **Test template structure:**

   **TypeScript (vitest):**
   ```typescript
   import { describe, it, expect } from 'vitest'
   import { functionName } from './source'

   describe('ModuleName', () => {
     it('should handle basic case', () => {
       expect(functionName()).toBeDefined()
     })
   })
   ```

   **Python (pytest):**
   ```python
   import pytest
   from module import function_name

   def test_function_name():
       """Test basic functionality."""
       result = function_name()
       assert result is not None
   ```

6. **Write test file**
   ```bash
   # Write to appropriate test file location
   ```

7. **Report completion**
   - Show test file path
   - List generated test cases
   - Suggest: "Run `/test coverage` to verify"

---

## /test coverage

Run test coverage report using auto-detected framework.

**Steps:**

1. **Detect project type**
   ```bash
   # Check for vitest.config.ts
   if [ -f "vitest.config.ts" ] || [ -f "vite.config.ts" ]; then
       FRAMEWORK="vitest"
   # Check for pyproject.toml or pytest.ini
   elif [ -f "pyproject.toml" ] || [ -f "pytest.ini" ]; then
       FRAMEWORK="pytest"
   else
       echo "Error: No test framework detected"
       exit 1
   fi
   ```

2. **Run coverage**

   **TypeScript (vitest):**
   ```bash
   npx vitest run --coverage
   ```

   **Python (pytest):**
   ```bash
   uv run pytest --cov --cov-report=term-missing
   ```

3. **Parse and display results**
   - Show coverage percentage
   - Highlight uncovered files
   - Suggest files needing tests

---

## /test mutate <file>

Simple mutation testing - modify source code and verify tests catch changes.

**Steps:**

1. **Read source file**
   ```bash
   cat "$FILE"
   ```

2. **Generate mutations using AST**

   **Python example:**
   ```python
   import ast

   class MutationVisitor(ast.NodeTransformer):
       def visit_BinOp(self, node):
           # Flip operators: + → -, == → !=
           if isinstance(node.op, ast.Add):
               node.op = ast.Sub()
           elif isinstance(node.op, ast.Eq):
               node.op = ast.NotEq()
           return node
   ```

   **TypeScript example:**
   ```python
   import re

   def mutate_operators(code):
       # Simple regex-based mutations
       mutations = [
           (r'\+', '-'),
           (r'===', '!=='),
           (r'>', '<'),
           (r'if \(', 'if (!')
       ]
       return [re.sub(old, new, code, count=1) for old, new in mutations]
   ```

3. **For each mutation:**
   - Create temporary mutated file
   - Run test suite
   - Check if tests fail (mutation caught)
   - Restore original file

4. **Report results:**
   ```
   Mutation Testing Results:
   - Total mutations: 8
   - Caught by tests: 6 (75%)
   - Survived: 2 (25%)

   Survived mutations:
   - Line 42: + → - (no test coverage)
   - Line 58: == → != (weak assertion)
   ```

---

## /test all

Run all test suites in sequence.

**Steps:**

1. **Run TypeScript tests (if vitest.config.ts exists)**
   ```bash
   if [ -f "vitest.config.ts" ] || [ -f "vite.config.ts" ]; then
       echo "Running TypeScript tests..."
       npx vitest run
   fi
   ```

2. **Run Python tests (if pyproject.toml exists)**
   ```bash
   if [ -f "pyproject.toml" ] || [ -f "pytest.ini" ]; then
       echo "Running Python tests..."
       uv run pytest
   fi
   ```

3. **Report summary**
   ```
   Test Results Summary:
   - TypeScript (vitest): 24 passed, 0 failed
   - Python (pytest): 18 passed, 2 skipped
   ```

---

## Auto-Detection Rules

| File Extension | Test Framework | Test File Pattern | Runner Command |
|----------------|----------------|-------------------|----------------|
| `.ts` `.tsx` | vitest | `<name>.test.ts` | `npx vitest run` |
| `.py` | pytest | `test_<name>.py` | `uv run pytest` |

**Project detection:**
- Vitest: Check for `vitest.config.ts`, `vite.config.ts`, or `package.json` with `vitest` dependency
- Pytest: Check for `pyproject.toml`, `pytest.ini`, or `setup.py` with `pytest` dependency

---

## Implementation Notes

The skill is implemented in `skills/test/scripts/test.py` with these functions:

- `cmd_generate(file_path)` — AST analysis + test generation
- `cmd_coverage()` — Detect project type, run coverage tool
- `cmd_mutate(file_path)` — AST mutations + test verification
- `cmd_all()` — Sequential test runner

**AST libraries:**
- Python: Built-in `ast` module for parsing `.py` files
- TypeScript: Regex/pattern matching (no heavy dependencies)

---

## Error Handling

| Error | Action |
|-------|--------|
| No test framework detected | Display error, suggest installing vitest or pytest |
| Source file not found | Display error with file path |
| Test generation fails | Show AST parsing error, suggest manual test creation |
| Coverage tool missing | Install: `npm i -D @vitest/coverage-v8` or `uv add pytest-cov` |
| Mutation testing timeout | Skip slow mutations, report partial results |

---

## Examples

**Generate tests for TypeScript:**
```
/test generate src/auth/jwt.ts
→ Created src/auth/jwt.test.ts with 5 test cases
```

**Run coverage:**
```
/test coverage
→ TypeScript: 87% coverage (24 files)
→ Python: 92% coverage (18 files)
```

**Mutation testing:**
```
/test mutate src/auth/jwt.ts
→ 8 mutations: 6 caught (75%), 2 survived
```

**Run all tests:**
```
/test all
→ vitest: 24 passed
→ pytest: 18 passed, 2 skipped
```

---
