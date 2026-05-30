"""
Tests for resistance_support.compute_levels — R/S #146.

Runs unit checks on synthetic frames (deterministic) plus a real-data smoke test
against LEAN daily zips. Run: python algorithm/resistance_support.test.py
(also pytest-compatible: pytest algorithm/resistance_support.test.py)
"""

import io
import os
import zipfile

import pandas as pd

from resistance_support import (
    Levels,
    _cluster_levels,
    _pivot_high_prices,
    _round_numbers,
    compute_levels,
)

DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "data", "equity", "usa", "daily"
)


def _load_lean_daily(ticker: str) -> pd.DataFrame:
    """Load a LEAN daily zip into an OHLCV DataFrame (prices are stored ×10000)."""
    path = os.path.join(DATA_DIR, f"{ticker.lower()}.zip")
    with zipfile.ZipFile(path) as z:
        raw = z.read(z.namelist()[0]).decode()
    rows = []
    for line in raw.strip().splitlines():
        ts, o, h, l, c, v = line.split(",")
        rows.append((ts.split()[0], int(o) / 1e4, int(h) / 1e4,
                     int(l) / 1e4, int(c) / 1e4, int(v)))
    df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    return df.set_index("date").sort_index()


# --- pure-function unit tests ------------------------------------------------

def test_pivot_high_detects_peak():
    high = pd.Series([1, 2, 5, 2, 1, 2, 6, 2, 1.0])
    peaks = _pivot_high_prices(high, span=2)
    assert 5.0 in peaks and 6.0 in peaks


def test_cluster_requires_min_touches():
    # three prices within 1.5% of 100 → one confirmed level; a lone 200 dropped
    prices = [100.0, 100.5, 99.6, 200.0]
    levels = _cluster_levels(prices, tol=0.015, min_touches=3)
    assert len(levels) == 1
    assert abs(levels[0] - 100.03) < 0.5


def test_round_numbers_within_band():
    levels = _round_numbers(ref=185.0, steps=(50.0, 100.0, 200.0), band=0.25)
    # band = [138.75, 231.25] → 150, 200 present; 100 and 250 excluded
    assert 150.0 in levels and 200.0 in levels
    assert 100.0 not in levels and 250.0 not in levels


def test_resistance_above_support_below():
    idx = pd.date_range("2024-01-01", periods=80, freq="D")
    # oscillator 90..110 so pivots cluster around the band edges
    vals = [100 + 10 * ((-1) ** i) for i in range(80)]
    df = pd.DataFrame({
        "open": vals, "high": [v + 1 for v in vals],
        "low": [v - 1 for v in vals], "close": vals,
        "volume": [1_000_000] * 80,
    }, index=idx)
    lv = compute_levels(df, ref_price=100.0)
    assert all(r >= 100.0 for r in lv.resistance)
    assert all(s <= 100.0 for s in lv.support)
    if lv.nearest_resistance is not None:
        assert lv.nearest_resistance >= 100.0
    if lv.nearest_support is not None:
        assert lv.nearest_support <= 100.0


def test_empty_frame_safe():
    assert compute_levels(pd.DataFrame()) == Levels()


# --- real-data smoke test ----------------------------------------------------

def test_real_ticker_smoke():
    for ticker in ("aapl", "msft", "nvda"):
        path = os.path.join(DATA_DIR, f"{ticker}.zip")
        if not os.path.exists(path):
            continue
        df = _load_lean_daily(ticker)
        ref = float(df["close"].iloc[-1])
        lv = compute_levels(df, ref_price=ref, senkou_a=ref * 0.95, senkou_b=ref * 0.92)
        # invariants
        assert lv.nearest_resistance is None or lv.nearest_resistance >= ref
        assert lv.nearest_support is None or lv.nearest_support <= ref
        assert lv.by_source["high_52w"][0] >= lv.by_source["low_52w"][0]
        # 52w high should be a resistance (>= ref typically near highs) or already passed
        print(f"{ticker.upper()} ref={ref:.2f} "
              f"nR={lv.nearest_resistance} nS={lv.nearest_support} "
              f"R={lv.resistance[:3]} S={lv.support[:3]} "
              f"52wH={lv.by_source['high_52w'][0]} HVN={lv.by_source['hvn']}")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        fn()
        passed += 1
        print(f"  ok  {fn.__name__}")
    print(f"\n{passed}/{len(fns)} tests passed")
