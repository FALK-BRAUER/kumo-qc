import pandas as pd
import numpy as np
from phases.shared.oracle_helpers import _mid, _adx_wilder, _resample_weekly, score_symbol_native


def _make_ohlcv(n=300, seed=42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 2, n)
    low = close - rng.uniform(0, 2, n)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": 1_000_000}, index=dates)


def test_mid_returns_series():
    df = _make_ohlcv()
    result = _mid(df["high"], df["low"], 9)
    assert isinstance(result, pd.Series)
    assert len(result) == len(df)


def test_mid_is_between_high_and_low():
    df = _make_ohlcv()
    m = _mid(df["high"], df["low"], 9).dropna()
    assert (m >= df["low"].rolling(9).min().dropna()).all()
    assert (m <= df["high"].rolling(9).max().dropna()).all()


def test_adx_wilder_returns_three_series():
    df = _make_ohlcv()
    adx, plus_di, minus_di = _adx_wilder(df, period=9)
    assert len(adx) == len(df)
    assert len(plus_di) == len(df)
    assert len(minus_di) == len(df)


def test_adx_wilder_values_non_negative():
    df = _make_ohlcv()
    adx, plus_di, minus_di = _adx_wilder(df, period=9)
    assert adx.dropna().ge(0).all()
    assert plus_di.dropna().ge(0).all()
    assert minus_di.dropna().ge(0).all()


def test_resample_weekly_reduces_rows():
    df = _make_ohlcv(n=300)
    weekly = _resample_weekly(df)
    assert len(weekly) < len(df)
    assert "close" in weekly.columns


def test_score_symbol_native_returns_none_when_indicators_not_ready():
    # #213f: score_symbol_native now reads MAINTAINED indicators (no history). Contract:
    # ind is always a dict (bct_score_full guards `if ind is None: continue` before calling);
    # returns None until indicators are ready. Full condition-logic + readiness coverage is in
    # tests/phases/shared/test_score_symbol_native.py. Here: a not-ready d_ichi → None.
    class _NR:  # not-ready indicator
        is_ready = False
    ind = {"d_ichi": _NR(), "w_ichi": _NR(), "w_close": _NR(), "sma200": _NR(),
           "adx": _NR(), "adx_window": _NR(), "roc13": _NR()}
    assert score_symbol_native(algorithm=None, symbol=None, ind=ind) is None


def test_oracle_helpers_importable():
    from phases.shared.oracle_helpers import (
        _mid, _adx_wilder, _resample_weekly, _fetch_ohlcv,
        score_symbol, score_symbol_native, _DAILY_BARS, _WEEKLY_BARS,
    )
    assert callable(score_symbol)
    assert _DAILY_BARS == 700
    assert _WEEKLY_BARS == 130
