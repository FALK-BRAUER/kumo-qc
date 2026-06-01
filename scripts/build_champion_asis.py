#!/usr/bin/env python3
"""Build dist/ for champion_asis and report config_hash.

Extracted from pr.yml / nightly.yml to eliminate embedded-code indentation
bug class (#296).
"""
import sys
from pathlib import Path

# Ensure repo root is on path (CI runs from checkout root; local may not)
repo_root = Path(__file__).parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import build.cloud_package as cp

result = cp.build("strategies.champion_asis")
print(result.config_hash)
