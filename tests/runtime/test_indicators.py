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
    # #253 added macd/macd_hist_window/vol_sma20/tbounce/daily_consolidator for the entry_selection
    # phase (§4 Gate 2) — ADDITIVE (signal/exit phases don't read them, champion-asis parity intact).
    assert INDICATOR_KEYS == (
        "d_ichi", "w_ichi", "w_close", "sma200", "adx", "adx_window", "roc13", "consolidator",
        "macd", "macd_hist_window", "vol_sma20", "tbounce", "daily_consolidator",
    )


# --- #253 TBounceTracker: the pure C2 degrade-state machine (sessions-below-Tenkan + gap-up). ---


def test_tbounce_sessions_below_tenkan_counts_consecutive():
    from runtime.indicators import TBounceTracker
    t = TBounceTracker()
    t.update(open_=100.0, high=101.0, low=94.0, close=95.0, tenkan=98.0)   # close<tenkan -> 1
    assert t.sessions_below_tenkan == 1
    t.update(open_=95.0, high=96.0, low=93.0, close=94.0, tenkan=98.0)     # below -> 2
    assert t.sessions_below_tenkan == 2
    t.update(open_=94.0, high=100.0, low=94.0, close=99.0, tenkan=98.0)    # close>=tenkan -> reset 0
    assert t.sessions_below_tenkan == 0


def test_tbounce_stores_last_daily_ohlc():
    # HQ #253-P1: C2 reads the latest daily OHLC bar — the tracker stores it.
    from runtime.indicators import TBounceTracker
    t = TBounceTracker()
    assert t.last_close is None  # no bar yet -> phase declines
    t.update(open_=99.6, high=100.2, low=99.5, close=100.0, tenkan=99.7)
    assert (t.last_open, t.last_high, t.last_low, t.last_close) == (99.6, 100.2, 99.5, 100.0)


def test_tbounce_gap_up_fraction():
    from runtime.indicators import TBounceTracker
    t = TBounceTracker()
    t.update(open_=100.0, high=101.0, low=99.0, close=100.0, tenkan=90.0)  # first bar -> gap 0
    assert t.gap_up_frac == 0.0
    t.update(open_=106.0, high=108.0, low=105.0, close=107.0, tenkan=90.0)  # open 106 vs prev 100 -> +6%
    assert abs(t.gap_up_frac - 0.06) < 1e-9


def test_tbounce_gap_down_is_zero():
    from runtime.indicators import TBounceTracker
    t = TBounceTracker()
    t.update(open_=100.0, high=101.0, low=99.0, close=100.0, tenkan=90.0)
    t.update(open_=95.0, high=97.0, low=94.0, close=96.0, tenkan=90.0)     # gap DOWN -> 0.0
    assert t.gap_up_frac == 0.0


def test_tbounce_deterministic_replay():
    from runtime.indicators import TBounceTracker
    bars = [
        (100.0, 101.0, 94.0, 95.0, 98.0),
        (95.0, 100.0, 94.0, 99.0, 98.0),
        (104.0, 106.0, 103.0, 105.0, 100.0),
    ]
    a, b = TBounceTracker(), TBounceTracker()
    for o, h, lo, c, tk in bars:
        a.update(open_=o, high=h, low=lo, close=c, tenkan=tk)
        b.update(open_=o, high=h, low=lo, close=c, tenkan=tk)
    assert (a.sessions_below_tenkan, a.gap_up_frac, a.last_close) == (
        b.sessions_below_tenkan, b.gap_up_frac, b.last_close)
