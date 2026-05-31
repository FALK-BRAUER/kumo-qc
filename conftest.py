"""Root conftest — put the repo root on sys.path for the test suite.

Tests import via the ``tests`` package (``from tests.harness...``) and the ``cli``
package (``from cli.app import app``). pytest.ini's ``pythonpath = src build`` covers
src/build but not the repo root; adding it here makes ``pytest`` self-contained
(no external ``PYTHONPATH=.`` needed).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
