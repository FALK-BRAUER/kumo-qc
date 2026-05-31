"""#265 — pin the residual-diff replay constants to the LIVE dist selection-gate.

scripts/residual_parity_diff.py replays the selection gate OFFLINE to classify gap names. Its
floor/prefilter constants MUST match dist/lean_entry.BctEngineAlgorithm — if the engine's floors
change and the replay's don't, the gap classification silently lies. This test asserts they
agree (parsed from the committed dist source — git = source of truth). FAIL-LOUD on drift.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LEAN_ENTRY = _ROOT / "dist" / "lean_entry.py"

import sys

if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import residual_parity_diff as R  # noqa: E402


def _const(name: str) -> float:
    """Parse `NAME: <type> = <number>` from the dist lean_entry source (the live Params)."""
    txt = _LEAN_ENTRY.read_text()
    m = re.search(rf"{name}\s*:\s*\w+\s*=\s*([0-9_]+(?:\.[0-9]+)?)", txt)
    assert m, f"FAIL-LOUD: {name} not found in {_LEAN_ENTRY} — engine moved the constant"
    return float(m.group(1).replace("_", ""))


def test_replay_floors_match_live_engine() -> None:
    assert R.PREFILTER_DV == _const("PREFILTER_DV"), "PREFILTER_DV drifted from engine"
    assert R.MIN_PRICE == _const("MIN_PRICE"), "MIN_PRICE drifted from engine"
    assert R.MIN_AVG_DOLLAR_VOLUME == _const("MIN_AVG_DOLLAR_VOLUME"), "DV floor drifted"
    assert R.ADV_WINDOW == _const("ADV_WINDOW"), "ADV_WINDOW drifted from engine"
    assert R.COARSE_MAX == _const("COARSE_MAX"), "COARSE_MAX drifted from engine"
