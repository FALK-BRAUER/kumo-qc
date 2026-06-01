#!/usr/bin/env python3
"""Validate YAML well-formedness in .github/workflows/*.yml.

SCOPE: This checks YAML parse-ability ONLY (yaml.safe_load). It does NOT
catch indentation bugs INSIDE multiline shell scripts (run: | blocks) —
those are opaque scalar strings to the YAML parser and remain valid YAML
even when the embedded code is malformed. The #296 root cause was exactly
that class: a python -c block lost internal indentation but yaml.safe_load
still passed. Structural fix: extract embedded code into standalone scripts
(ci_manifest_check.py, build_champion_asis.py, verify_dist_pin.py) so there
is nothing to lose indentation.

Run manually: python scripts/yaml_lint.py
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
        content = path.read_text()
        if not content.strip():
            print(f"  FAIL: {path} — empty file")
            return False
        yaml.safe_load(content)
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

    # Check both .yml and .yaml (GitHub accepts both)
    yml_files = list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml"))
    if not yml_files:
        print("No .yml/.yaml files in .github/workflows/ — skipping")
        return 0

    print(f"Validating {len(yml_files)} workflow file(s) (well-formedness ONLY)...")
    all_ok = True
    for f in sorted(yml_files):
        if not validate_file(f):
            all_ok = False

    if not all_ok:
        print("\nYAML well-formedness check FAILED")
        return 1

    print("\nAll workflow files well-formed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
