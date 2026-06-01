#!/usr/bin/env python3
"""Verify dist/_manifest.json git_commit matches HEAD.

Extracted from pr.yml / nightly.yml to eliminate embedded-code indentation
bug class (#296).
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify dist manifest pins to current HEAD"
    )
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Print warning instead of failing on mismatch (nightly mode)",
    )
    args = parser.parse_args()

    manifest_path = Path("dist/_manifest.json")
    if not manifest_path.exists():
        print("ERROR: dist/_manifest.json not found")
        return 1

    m = json.loads(manifest_path.read_text())
    manifest_commit = m.get("git_commit", "")

    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    head_commit = head_result.stdout.strip()

    if manifest_commit != head_commit:
        msg = (
            f"dist/ is stale — manifest built at {manifest_commit} "
            f"but HEAD is {head_commit}"
        )
        if args.warn_only:
            print(f"WARNING: {msg}")
            print("Run: python -m build.cloud_package strategies.champion_asis")
            return 0
        print(f"ERROR: {msg}")
        print("Run: python -m build.cloud_package strategies.champion_asis")
        return 1

    print(f"dist/ pinned to HEAD: {head_commit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
