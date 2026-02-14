#!/usr/bin/env python3
"""
Unified test skill - vitest + pytest integration
Auto-detects framework based on file extension and project config.
"""

import sys
import os
import subprocess
import re
import ast
from pathlib import Path
from typing import List, Dict, Tuple, Optional


def detect_framework(file_path: Optional[str] = None) -> str:
    """
    Auto-detect test framework based on file extension or project config.

    Args:
        file_path: Optional source file path for extension detection

    Returns:
        'vitest' or 'pytest'
    """
    # If file path provided, check extension first
    if file_path:
        ext = Path(file_path).suffix
        if ext in ['.ts', '.tsx', '.js', '.jsx']:
            return 'vitest'
        elif ext == '.py':
            return 'pytest'

    # Fallback to project detection
    if Path('vitest.config.ts').exists() or Path('vite.config.ts').exists():
        return 'vitest'
    elif Path('pyproject.toml').exists() or Path('pytest.ini').exists():
        return 'pytest'

    # Default based on common patterns
    if list(Path('.').glob('**/*.test.ts')):
        return 'vitest'
    elif list(Path('.').glob('**/test_*.py')):
        return 'pytest'

    raise ValueError("Could not detect test framework. Ensure vitest.config.ts or pyproject.toml exists.")


def extract_python_entities(source_path: str) -> Dict[str, List[str]]:
    """
    Extract functions and classes from Python source using AST.

    Returns:
        {'functions': [...], 'classes': [...], 'imports': [...]}
    """
    with open(source_path, 'r', encoding='utf-8') as f:
        source = f.read()

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        print(f"Error parsing Python file: {e}")
        return {'functions': [], 'classes': [], 'imports': []}

    functions = []
    classes = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Skip private functions and test functions
            if not node.name.startswith('_') and not node.name.startswith('test_'):
                functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            if not node.name.startswith('_'):
                classes.append(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            # Track imports for test file generation
            if isinstance(node, ast.ImportFrom):
                imports.append(node.module or '')

    return {
        'functions': functions,
        'classes': classes,
        'imports': imports
    }


def extract_typescript_entities(source_path: str) -> Dict[str, List[str]]:
    """
    Extract functions, classes, and components from TypeScript using regex.
    Simplified approach - no heavy TypeScript parser dependencies.

    Returns:
        {'functions': [...], 'classes': [...], 'components': [...]}
    """
    with open(source_path, 'r', encoding='utf-8') as f:
        source = f.read()

    # Match exported functions: export function name() or export const name = () =>
    function_pattern = r'export\s+(?:async\s+)?(?:function\s+(\w+)|const\s+(\w+)\s*=)'
    functions = [m.group(1) or m.group(2) for m in re.finditer(function_pattern, source)]

    # Match exported classes: export class Name
    class_pattern = r'export\s+class\s+(\w+)'
    classes = [m.group(1) for m in re.finditer(class_pattern, source)]

    # Match React components: export default function ComponentName or const ComponentName = () =>
    component_pattern = r'export\s+default\s+(?:function\s+(\w+)|const\s+(\w+)\s*=)'
    components = [m.group(1) or m.group(2) for m in re.finditer(component_pattern, source)]

    return {
        'functions': functions,
        'classes': classes,
        'components': components
    }


def generate_python_test(source_path: str, entities: Dict[str, List[str]]) -> str:
    """Generate pytest test file content."""
    module_name = Path(source_path).stem
    test_cases = []

    # Generate test for each function
    for func in entities['functions']:
        test_cases.append(f"""
def test_{func}():
    \"\"\"Test {func} basic functionality.\"\"\"
    result = {func}()
    assert result is not None
""")

    # Generate test for each class
    for cls in entities['classes']:
        test_cases.append(f"""
def test_{cls}_instantiation():
    \"\"\"Test {cls} can be instantiated.\"\"\"
    instance = {cls}()
    assert instance is not None
""")

    imports = '\n'.join([f"from {module_name} import {item}"
                         for item in entities['functions'] + entities['classes']])

    return f"""\"\"\"Tests for {module_name} module.\"\"\"

import pytest
{imports}

{''.join(test_cases)}
"""


def generate_typescript_test(source_path: str, entities: Dict[str, List[str]]) -> str:
    """Generate vitest test file content."""
    module_name = Path(source_path).stem
    source_import = f"./{module_name}"

    test_cases = []

    # Generate test for each function
    for func in entities['functions']:
        test_cases.append(f"""
  it('should test {func}', () => {{
    expect({func}).toBeDefined()
  }})
""")

    # Generate test for each class
    for cls in entities['classes']:
        test_cases.append(f"""
  it('should instantiate {cls}', () => {{
    const instance = new {cls}()
    expect(instance).toBeDefined()
  }})
""")

    # Generate test for React components
    for comp in entities['components']:
        test_cases.append(f"""
  it('should render {comp}', () => {{
    expect({comp}).toBeDefined()
  }})
""")

    all_exports = entities['functions'] + entities['classes'] + entities['components']
    imports = ', '.join(all_exports) if all_exports else '*'

    return f"""import {{ describe, it, expect }} from 'vitest'
import {{ {imports} }} from '{source_import}'

describe('{module_name}', () => {{
{''.join(test_cases)}
}})
"""


def cmd_generate(file_path: str) -> int:
    """
    Generate test file for source file.
    Auto-detects vitest or pytest based on file extension.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        return 1

    try:
        framework = detect_framework(file_path)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    print(f"Detected framework: {framework}")

    # Generate test content based on framework
    if framework == 'pytest':
        entities = extract_python_entities(file_path)
        test_content = generate_python_test(file_path, entities)
        test_path = Path(file_path).parent / f"test_{Path(file_path).name}"
    else:  # vitest
        entities = extract_typescript_entities(file_path)
        test_content = generate_typescript_test(file_path, entities)

        # Preserve .tsx extension if source is .tsx
        ext = '.test.tsx' if file_path.endswith('.tsx') else '.test.ts'
        test_path = Path(file_path).with_suffix(ext)

    # Write test file
    test_path.write_text(test_content, encoding='utf-8')

    print(f"\nGenerated test file: {test_path}")
    print(f"Test cases: {len(entities.get('functions', [])) + len(entities.get('classes', [])) + len(entities.get('components', []))}")
    print("\nRun `/test coverage` to verify test coverage.")

    return 0


def cmd_coverage() -> int:
    """Run coverage report using auto-detected framework."""
    try:
        framework = detect_framework()
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    print(f"Running coverage with {framework}...")

    if framework == 'vitest':
        # Check if coverage package is installed
        result = subprocess.run(['npx', 'vitest', '--version'],
                                capture_output=True, text=True)
        if result.returncode != 0:
            print("Error: vitest not found. Install: npm i -D vitest")
            return 1

        # Run vitest coverage
        result = subprocess.run(['npx', 'vitest', 'run', '--coverage'],
                                capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        if 'coverage' not in result.stdout.lower():
            print("\nNote: Coverage plugin may not be installed.")
            print("Install: npm i -D @vitest/coverage-v8")

        return result.returncode

    else:  # pytest
        # Check if pytest is available
        result = subprocess.run(['uv', 'run', 'pytest', '--version'],
                                capture_output=True, text=True)
        if result.returncode != 0:
            print("Error: pytest not found. Install: uv add pytest pytest-cov")
            return 1

        # Run pytest with coverage
        result = subprocess.run(['uv', 'run', 'pytest', '--cov', '--cov-report=term-missing'],
                                capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        return result.returncode


def cmd_mutate(file_path: str) -> int:
    """
    Simple mutation testing - modify source and verify tests catch changes.
    Uses AST manipulation for Python, regex for TypeScript.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        return 1

    try:
        framework = detect_framework(file_path)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    print(f"Running mutation testing on {file_path}...")

    # Read original source
    with open(file_path, 'r', encoding='utf-8') as f:
        original_source = f.read()

    mutations = []

    if framework == 'pytest':
        # Python AST-based mutations
        try:
            tree = ast.parse(original_source)

            class MutationCounter(ast.NodeVisitor):
                def __init__(self):
                    self.count = 0

                def visit_BinOp(self, node):
                    self.count += 1
                    self.generic_visit(node)

                def visit_Compare(self, node):
                    self.count += 1
                    self.generic_visit(node)

            counter = MutationCounter()
            counter.visit(tree)

            print(f"Found {counter.count} potential mutation points (operators)")
            print("Note: Full mutation testing requires running modified code - not implemented in this simple version")

        except SyntaxError as e:
            print(f"Error parsing Python: {e}")
            return 1

    else:  # vitest - regex-based
        # Count potential mutations
        mutations = [
            (r'\+(?!=)', 'Addition to Subtraction'),
            (r'===', 'Strict Equality to Inequality'),
            (r'>', 'Greater Than to Less Than'),
            (r'&&', 'AND to OR'),
        ]

        mutation_count = 0
        for pattern, desc in mutations:
            matches = re.findall(pattern, original_source)
            mutation_count += len(matches)

        print(f"Found {mutation_count} potential mutation points")
        print("Note: Full mutation testing requires running modified code - not implemented in this simple version")

    print("\nMutation testing is a preview feature. For production use, consider:")
    print("- Python: mutmut, cosmic-ray")
    print("- TypeScript: Stryker")

    return 0


def cmd_all() -> int:
    """Run all test suites in sequence."""
    exit_code = 0

    # Run vitest if config exists
    if Path('vitest.config.ts').exists() or Path('vite.config.ts').exists():
        print("=" * 60)
        print("Running TypeScript tests (vitest)...")
        print("=" * 60)
        result = subprocess.run(['npx', 'vitest', 'run'],
                                capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        if result.returncode != 0:
            exit_code = result.returncode

    # Run pytest if config exists
    if Path('pyproject.toml').exists() or Path('pytest.ini').exists():
        print("\n" + "=" * 60)
        print("Running Python tests (pytest)...")
        print("=" * 60)
        result = subprocess.run(['uv', 'run', 'pytest'],
                                capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        if result.returncode != 0:
            exit_code = result.returncode

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    if exit_code == 0:
        print("All tests passed!")
    else:
        print(f"Some tests failed (exit code: {exit_code})")

    return exit_code


def cmd_help() -> int:
    """Show help text."""
    print("""
Unified Test Skill - vitest + pytest integration

Commands:
  /test generate <file>  Generate test file (auto-detect framework)
  /test coverage         Run coverage report
  /test mutate <file>    Mutation testing preview
  /test all              Run all test suites
  /test help             Show this help

Auto-Detection:
  .ts/.tsx files -> vitest
  .py files -> pytest

Examples:
  /test generate src/auth/jwt.ts
  /test coverage
  /test all
""")
    return 0


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        cmd_help()
        return 1

    command = sys.argv[1]

    if command == 'generate':
        if len(sys.argv) < 3:
            print("Error: Missing file path")
            print("Usage: /test generate <file>")
            return 1
        return cmd_generate(sys.argv[2])

    elif command == 'coverage':
        return cmd_coverage()

    elif command == 'mutate':
        if len(sys.argv) < 3:
            print("Error: Missing file path")
            print("Usage: /test mutate <file>")
            return 1
        return cmd_mutate(sys.argv[2])

    elif command == 'all':
        return cmd_all()

    elif command == 'help':
        return cmd_help()

    else:
        print(f"Error: Unknown command: {command}")
        cmd_help()
        return 1


if __name__ == '__main__':
    sys.exit(main())
