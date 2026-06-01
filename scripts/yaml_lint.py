#!/usr/bin/env python3
"""Validate YAML syntax for workflow files — catch indentation bugs before merge.

Run manually: python scripts/yaml_lint.py
Run via pre-commit: copy to .git/hooks/pre-commit (or use pre-commit framework)
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required — pip install pyyaml")
    sys.exit(1)


def validate_file(path: Path) -> bool:
    try:
        with open(path) as f:
            yaml.safe_load(f)
        print(f"  OK: {path}")
        return True
    except yaml.YAMLError as e:
        print(f"  FAIL: {path}")
        print(f"    {e}")
        return False


def main() -> int:
    workflows_dir = Path(".github/workflows")
    if not workflows_dir.exists():
        print("No .github/workflows/ directory — skipping")
        return 0

    yml_files = list(workflows_dir.glob("*.yml"))
    if not yml_files:
        print("No .yml files in .github/workflows/ — skipping")
        return 0

    print(f"Validating {len(yml_files)} workflow file(s)...")
    all_ok = True
    for f in sorted(yml_files):
        if not validate_file(f):
            all_ok = False

    if not all_ok:
        print("\nYAML validation FAILED — fix syntax errors before committing")
        return 1

    print("\nAll workflow files valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
