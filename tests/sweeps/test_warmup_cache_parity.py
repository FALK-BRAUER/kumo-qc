"""#332 warmup-cache — BYTE-PARITY gate for the Ichimoku port against LEAN's OWN golden test data
(~/reference/Lean/Tests/TestData/spy_with_ichimoku.csv). The port must reproduce LEAN's Tenkan /
Kijun / Senkou A / Senkou B exactly (to the golden file's printed precision) — a divergence is the
parity trap and blocks the cache. Skips gracefully if the LEAN source isn't present.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

import datetime as dt

from sweeps.warmup_cache.lean_indicators import (
    ADX, SMA, Delay, Ichimoku, Maximum, Minimum, WeeklyIchimokuAsOf, monday_of_week,
)

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


def test_monday_of_week_bucketing() -> None:
    # 2025-06-02 is a Monday; Tue..Fri of that week all bucket to it; next Mon = 06-09.
    mon = dt.date(2025, 6, 2)
    for off in range(5):  # Mon..Fri
        assert monday_of_week(mon + dt.timedelta(days=off)) == mon
    assert monday_of_week(dt.date(2025, 6, 9)) == dt.date(2025, 6, 9)  # next Monday → own week


def test_weekly_asof_no_lookahead_and_boundary_emit() -> None:
    """The as-of weekly close advances ONLY at a week boundary (first trading day of the next week),
    and NEVER exposes the in-progress week (look-ahead). Includes a holiday-short week (no Monday)."""
    w = WeeklyIchimokuAsOf()
    # week A (Mon 06-02 .. Fri 06-06), week B HOLIDAY-SHORT (Mon 06-09 missing → starts Tue 06-10),
    # week C (Mon 06-16 ..). closes chosen distinct per week.
    bars = [
        (dt.date(2025, 6, 2), 10), (dt.date(2025, 6, 3), 11), (dt.date(2025, 6, 6), 12),  # week A, close 12
        (dt.date(2025, 6, 10), 20), (dt.date(2025, 6, 13), 22),                            # week B (holiday Mon), close 22
        (dt.date(2025, 6, 16), 30),                                                         # week C, first day
    ]
    seen_completed = []
    for d, px in bars:
        w.update(d, px, px, px, px)
        seen_completed.append(w.completed_weeks)
    # During week A (3 bars): 0 completed weeks available yet (in-progress, not emitted).
    assert seen_completed[:3] == [0, 0, 0], "in-progress week A leaked as completed (look-ahead)"
    # First bar of week B (Tue 06-10, holiday Mon) → week A emits → 1 completed. Stable within week B.
    assert seen_completed[3] == 1 and seen_completed[4] == 1
    # First bar of week C (06-16) → week B emits → 2 completed.
    assert seen_completed[5] == 2
    # the latest completed weekly close at week C's first day is week B's close (22), NOT week C's (30).
    assert w.w_close(0) == 22.0    # most-recent COMPLETED, never the in-progress week
    assert w.w_close(1) == 12.0    # week A


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
