"""#332 warmup-cache — BYTE-PARITY gate for the Ichimoku port against LEAN's OWN golden test data
(~/reference/Lean/Tests/TestData/spy_with_ichimoku.csv). The port must reproduce LEAN's Tenkan /
Kijun / Senkou A / Senkou B exactly (to the golden file's printed precision) — a divergence is the
parity trap and blocks the cache. Skips gracefully if the LEAN source isn't present.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from sweeps.warmup_cache.lean_indicators import ADX, SMA, Delay, Ichimoku, Maximum, Minimum

GOLDEN = Path.home() / "reference/Lean/Tests/TestData/spy_with_ichimoku.csv"
GOLDEN_ADX = Path.home() / "reference/Lean/Tests/TestData/spy_with_adx.txt"
pytestmark = pytest.mark.skipif(not GOLDEN.exists(), reason="LEAN golden test data not present")


def _f(s: str):
    s = (s or "").strip()
    return float(s) if s else None


def test_ichimoku_matches_lean_golden_byte_identical() -> None:
    """Feed the golden Open/High/Low/Close through the port; assert Tenkan/Kijun/Senkou A/Senkou B
    match the golden columns at the file's precision (4 dp) on EVERY row where LEAN has a value."""
    ichi = Ichimoku()  # LEAN defaults 9/26/52, delay 26 — same as the strategy
    rows = list(csv.DictReader(GOLDEN.open()))
    assert len(rows) > 100
    checked = {"tenkan": 0, "kijun": 0, "senkou_a": 0, "senkou_b": 0}
    for row in rows:
        ichi.update(float(row["High"]), float(row["Low"]), float(row["Close"]))
        for port_val, col in (
            (ichi.tenkan, "Tenkan"), (ichi.kijun, "Kijun"),
            (ichi.senkou_a, "Senkou A"), (ichi.senkou_b, "Senkou B"),
        ):
            gold = _f(row[col])
            if gold is None:  # LEAN not ready yet on this row → port should also be NaN/unready
                continue
            assert port_val == pytest.approx(gold, abs=1e-4), (
                f"{col} mismatch on {row['Date']}: port={port_val} golden={gold}")
            checked[col.lower().replace(" ", "_")] += 1
    # we actually validated a meaningful number of ready rows for each line (not vacuously)
    assert all(c > 50 for c in checked.values()), f"too few rows checked: {checked}"


@pytest.mark.skipif(not GOLDEN_ADX.exists(), reason="LEAN golden ADX data not present")
def test_adx_matches_lean_golden() -> None:
    """Feed the golden Open/High/Low/Close through the ADX port (period 14, matching the golden);
    assert +DI / -DI / ADX match LEAN's +DI14 / -DI14 / ADX 14 columns on every ready row."""
    adx = ADX(period=14)
    rows = list(csv.DictReader(GOLDEN_ADX.open()))
    assert len(rows) > 100
    checked = {"pdi": 0, "mdi": 0, "adx": 0}
    for row in rows:
        adx.update(float(row["High"]), float(row["Low"]), float(row["Close"]))
        for port_val, col, key in (
            (adx.plus_di, "+DI14", "pdi"), (adx.minus_di, "-DI14", "mdi"), (adx.adx, "ADX 14", "adx"),
        ):
            gold = _f(row.get(col, ""))
            if gold is None:
                continue
            assert port_val == pytest.approx(gold, abs=1e-3, rel=1e-4), (
                f"{col} mismatch on {row['Date']}: port={port_val} golden={gold}")
            checked[key] += 1
    assert all(c > 50 for c in checked.values()), f"too few ADX rows checked: {checked}"


def test_rolling_primitives() -> None:
    """Maximum/Minimum window semantics + Delay's N-back value."""
    mx, mn = Maximum(3), Minimum(3)
    for v in (5, 3, 8):
        mx.update(v); mn.update(v)
    assert mx.is_ready and mx.value == 8 and mn.value == 3
    mx.update(2); mn.update(2)  # window now [3,8,2]
    assert mx.value == 8 and mn.value == 2

    d = Delay(2)  # value 2 samples ago; ready at 3 samples
    d.update(10); d.update(20)
    assert not d.is_ready
    d.update(30)
    assert d.is_ready and d.value == 10  # 2 back from 30 is 10
    d.update(40)
    assert d.value == 20

    sma = SMA(3)
    for v in (3, 6, 9):
        sma.update(v)
    assert sma.is_ready and sma.value == 6.0  # (3+6+9)/3
    sma.update(12)
    assert sma.value == 9.0  # (6+9+12)/3
