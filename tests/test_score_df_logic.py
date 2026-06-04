#!/usr/bin/env python3
"""
test_score_df_logic.py — Unit test for ichimoku score_df logic fidelity.

Validates score_df independently of data source using a hand-crafted fixture
with known properties. Confirms the scoring engine is invoked correctly by
the regenerator (decoupled from the yfinance-vs-parquet source question).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(
    0,
    str(Path(__file__).parent.parent.parent / "kumo-trader" / ".worktrees" / "prod" / "scanner"),
)
from ichimoku import score_df  # noqa: E402


def _make_daily_fixture(
    n_days: int = 400,
    trend: str = "uptrend",
    price_start: float = 100.0,
) -> pd.DataFrame:
    """Build a synthetic daily OHLCV fixture with known BCT properties.
    
    Uses realistic oscillating price action (not pure linear) so ADX and
    Ichimoku conditions behave naturally.
    
    trend: 'uptrend' | 'downtrend' | 'sideways'
    """
    import numpy as np
    
    dates = pd.date_range(end="2026-05-08", periods=n_days, freq="B")
    np.random.seed(42)
    
    if trend == "uptrend":
        # Gradual trend + accelerating last 30 days → ADX rises into 20-100 range
        base = np.linspace(price_start, price_start + 100, n_days - 30)
        accel = np.linspace(base[-1], base[-1] + 30, 30)
        closes = np.concatenate([base, accel])
        closes += np.random.normal(0, 2, n_days)
    elif trend == "downtrend":
        base = np.linspace(price_start, price_start - 80, n_days - 30)
        accel = np.linspace(base[-1], base[-1] - 20, 30)
        closes = np.concatenate([base, accel])
        closes += np.random.normal(0, 2, n_days)
    else:  # sideways
        closes = np.array([price_start + (i % 40 - 20) * 0.3 for i in range(n_days)])
        closes += np.random.normal(0, 1, n_days)
    
    highs = closes + np.abs(np.random.normal(2, 1, n_days))
    lows = closes - np.abs(np.random.normal(1, 0.5, n_days))
    opens = np.roll(closes, 1)
    opens[0] = closes[0]
    volumes = np.full(n_days, 2_000_000)
    
    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    }, index=dates)
    
    return df


def _make_2h_fixture(
    date: str = "2026-05-08",
    n_bars: int = 13,
    trend: str = "uptrend",
    price_start: float = 100.0,
) -> pd.DataFrame:
    """Build a synthetic 2h OHLCV fixture for a single day."""
    start = pd.Timestamp(f"{date} 09:30")
    dates = pd.date_range(start=start, periods=n_bars, freq="2h")
    
    if trend == "uptrend":
        closes = [price_start + i * 0.2 for i in range(n_bars)]
    elif trend == "downtrend":
        closes = [price_start - i * 0.2 for i in range(n_bars)]
    else:
        closes = [price_start + (i % 3 - 1) * 0.1 for i in range(n_bars)]
    
    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    opens = [closes[max(0, i - 1)] for i in range(n_bars)]
    volumes = [100_000 + i * 1_000 for i in range(n_bars)]
    
    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    }, index=dates)
    
    return df


class TestScoreDfLogic:
    """Logic-fidelity tests: score_df on known fixtures → expected ratings."""
    
    def test_strong_uptrend_scores_8_8(self) -> None:
        """A strong, extended uptrend should score 8/8 (all conditions pass)."""
        daily = _make_daily_fixture(n_days=400, trend="uptrend", price_start=200.0)
        h2 = _make_2h_fixture(trend="uptrend", price_start=400.0)
        
        result = score_df(daily, raw_2h=h2)
        
        assert result is not None
        assert result["rating"] == "+++"
        assert result["score"] == 8
        assert result["c1"] == True  # weekly above cloud
        assert result["c2"] == True  # tenkan > kijun
        assert result["c5"] == True  # daily above cloud
        assert result["c6"] == True  # daily above tenkan
        assert result["c8"] == True  # above 200MA
    
    def test_downtrend_scores_low(self) -> None:
        """A downtrend should score poorly (below cloud, below MA200, etc.)."""
        daily = _make_daily_fixture(n_days=400, trend="downtrend", price_start=200.0)
        h2 = _make_2h_fixture(trend="downtrend", price_start=100.0)
        
        result = score_df(daily, raw_2h=h2)
        
        assert result is not None
        assert result["score"] < 4  # Should be weak
        assert result["c5"] == False  # below cloud
        assert result["c8"] == False  # below 200MA
    
    def test_insufficient_history_returns_none(self) -> None:
        """Less than 300 days of history → score_df returns None."""
        daily = _make_daily_fixture(n_days=100)
        
        result = score_df(daily, raw_2h=None)
        
        assert result is None
    
    def test_low_volume_returns_skip(self) -> None:
        """Very low volume → SKIP (scanner pre-filter)."""
        daily = _make_daily_fixture(n_days=400)
        daily["Volume"] = 1_000  # Very low volume
        
        result = score_df(daily, raw_2h=None)
        
        assert result is not None
        assert result.get("rating") == "SKIP" or result.get("score") == -9
    
    def test_no_2h_data_still_scores_daily(self) -> None:
        """Missing 2h data → score_df still computes daily-only conditions."""
        daily = _make_daily_fixture(n_days=400, trend="uptrend", price_start=200.0)
        
        result = score_df(daily, raw_2h=None)
        
        assert result is not None
        assert result["score"] >= 6  # Daily conditions should still pass
    
    def test_price_derivative_sanity(self) -> None:
        """The returned price must be the last daily close."""
        daily = _make_daily_fixture(n_days=400, trend="uptrend", price_start=100.0)
        expected_price = round(daily["Close"].iloc[-1], 2)
        
        result = score_df(daily, raw_2h=None)
        
        assert result is not None
        assert result["price"] == expected_price
    
    def test_adx_is_positive_number(self) -> None:
        """ADX must be a positive number on valid data."""
        daily = _make_daily_fixture(n_days=400, trend="uptrend")
        
        result = score_df(daily, raw_2h=None)
        
        assert result is not None
        assert result["adx"] > 0
        assert isinstance(result["adx"], (int, float))
    
    def test_weekly_conditions_computed(self) -> None:
        """Weekly Ichimoku conditions (c1-c4) are computed and returned."""
        daily = _make_daily_fixture(n_days=400, trend="uptrend")
        
        result = score_df(daily, raw_2h=None)
        
        assert result is not None
        assert "c1" in result
        assert "c2" in result
        assert "c3" in result
        assert "c4" in result
    
    def test_rating_consistency_with_score(self) -> None:
        """Rating must be consistent with score:
        +++ → 8, ++ → 6-7, + → 4-5, = → 2-3, -- → 0-1, --- → 0
        """
        daily = _make_daily_fixture(n_days=400, trend="uptrend")
        
        result = score_df(daily, raw_2h=None)
        
        assert result is not None
        score = result["score"]
        rating = result["rating"]
        
        if rating == "+++":
            assert score == 8
        elif rating == "++":
            assert 6 <= score <= 7
        elif rating == "+":
            assert 4 <= score <= 5
        elif rating == "=":
            assert 2 <= score <= 3
        elif rating in ("--", "---"):
            assert score <= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
