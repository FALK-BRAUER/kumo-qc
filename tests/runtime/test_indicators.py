"""Tests for runtime.indicators — the pure, parity-critical weekly aggregation (#213c).

The manual daily->weekly aggregation is the QC-cloud resample-timeout fix; golden-master it
against pandas resample('W-FRI') so the manual path provably equals the canonical one.
"""
from __future__ import annotations

import pandas as pd

from runtime.indicators import INDICATOR_KEYS, weekly_aggregate, weekly_friday


def _daily(start: str, n: int) -> pd.DataFrame:
    idx = pd.bdate_range(start=start, periods=n)  # business days
    # deterministic varied OHLCV
    return pd.DataFrame({
        "open":  [100.0 + i for i in range(n)],
        "high":  [101.0 + i for i in range(n)],
        "low":   [99.0 + i for i in range(n)],
        "close": [100.5 + i for i in range(n)],
        "volume": [1000 + 10 * i for i in range(n)],
    }, index=idx)


def test_weekly_friday_rule():
    # Mon..Fri map to that week's Friday; Sat/Sun roll to the NEXT Friday.
    assert weekly_friday(pd.Timestamp("2025-06-02")) == pd.Timestamp("2025-06-06")  # Mon->Fri
    assert weekly_friday(pd.Timestamp("2025-06-06")) == pd.Timestamp("2025-06-06")  # Fri->Fri
    assert weekly_friday(pd.Timestamp("2025-06-07")) == pd.Timestamp("2025-06-13")  # Sat->next Fri


def test_weekly_aggregate_matches_pandas_resample_wfri():
    # GOLDEN MASTER: the manual aggregation == resample('W-FRI') agg(first/max/min/last/sum).
    df = _daily("2025-06-02", 20)  # 4 business weeks
    manual = weekly_aggregate(df)
    ref = df.resample("W-FRI").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    assert len(manual) == len(ref)
    for wb, (ts, row) in zip(manual, ref.iterrows()):
        assert wb["friday"] == ts
        assert wb["open"] == row["open"]
        assert wb["high"] == row["high"]
        assert wb["low"] == row["low"]
        assert wb["close"] == row["close"]
        assert wb["volume"] == int(row["volume"])


def test_weekly_aggregate_hand_checked_single_week():
    # Mon-Fri one week -> one weekly bar: open=Mon open, high=max, low=min, close=Fri close.
    df = _daily("2025-06-02", 5)  # Mon..Fri 2025-06-06
    wb = weekly_aggregate(df)
    assert len(wb) == 1
    assert wb[0]["friday"] == pd.Timestamp("2025-06-06")
    assert wb[0]["open"] == 100.0          # Monday open
    assert wb[0]["close"] == 104.5         # Friday close (100.5+4)
    assert wb[0]["high"] == 105.0          # max high (101+4)
    assert wb[0]["low"] == 99.0            # min low (Monday)
    assert wb[0]["volume"] == sum(1000 + 10 * i for i in range(5))


def test_weekly_aggregate_chronological_order():
    df = _daily("2025-06-02", 15)
    wb = weekly_aggregate(df)
    fridays = [w["friday"] for w in wb]
    assert fridays == sorted(fridays)


def test_weekly_aggregate_empty_or_missing_cols():
    assert weekly_aggregate(pd.DataFrame()) == []
    bad = pd.DataFrame({"open": [1.0]}, index=pd.bdate_range("2025-06-02", periods=1))
    assert weekly_aggregate(bad) == []  # missing high/low/close/volume


def test_indicator_keys_contract():
    # The documented qc._indicators[symbol] contract (lifecycle populates these; phases read them).
    # #213f added adx/adx_window/roc13 so the signal reads maintained indicators (no per-bar history).
    assert INDICATOR_KEYS == (
        "d_ichi", "w_ichi", "w_close", "sma200", "adx", "adx_window", "roc13", "consolidator",
    )
