"""Behavioral FIRE/DECLINE coverage for oracle_helpers.score_symbol (the history-based scorer).

CONTEXT (#246 decision): score_symbol is production code with ZERO importers anywhere
(src/build/dist/tests) — only score_symbol_native is on the live path (imported by
bct_score_full). It is NOT removed here (destructive, HQ-gated); this adds the safe
behavioral test the ticket permits, so the module is not untested production code.

How it's tested: the function imports `QuantConnect.Resolution` lazily and returns None
outside LEAN. The dev venv has no QuantConnect, so we inject a stub module into sys.modules
and drive a fake `algorithm` whose .History() returns a synthetic daily OHLCV DataFrame.
- FIRE: a long, steady, accelerating uptrend that satisfies all 8 BCT conditions -> score 8 / "+++".
- DECLINE (None): insufficient history -> None (the warmup guard).
- DECLINE (bearish): a steady downtrend -> low score, not "+++".
"""
from __future__ import annotations

import sys
import types
from typing import Any

import numpy as np
import pandas as pd
import pytest

from phases.shared.oracle_helpers import score_symbol


@pytest.fixture
def stub_quantconnect() -> Any:
    """Inject a stub `QuantConnect` module exposing Resolution.DAILY so the lazy import
    inside score_symbol succeeds (it returns None otherwise — the 'outside LEAN' guard)."""
    mod = types.ModuleType("QuantConnect")
    resolution = types.SimpleNamespace(DAILY="DAILY", Daily="DAILY")
    mod.Resolution = resolution  # type: ignore[attr-defined]
    sys.modules["QuantConnect"] = mod
    try:
        yield resolution
    finally:
        sys.modules.pop("QuantConnect", None)


class FakeAlgo:
    """Fake LEAN algorithm: .History([sym], bars, res) returns a preset OHLCV frame."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    def History(self, symbols: list[Any], bars: int, resolution: Any) -> pd.DataFrame:
        return self._frame.tail(bars)


def _daily_frame(closes: np.ndarray) -> pd.DataFrame:
    """Build a daily OHLCV frame from a close series. high/low straddle close tightly so the
    Ichimoku midpoints track the trend; volume constant. Business-day DatetimeIndex so the
    W-FRI weekly resample produces clean weekly bars."""
    n = len(closes)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    high = closes * 1.01
    low = closes * 0.99
    return pd.DataFrame(
        {
            "open": closes,
            "high": high,
            "low": low,
            "close": closes,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


# ----------------------------------------------------------------------------------- FIRE


def test_score_symbol_fires_full_score_on_strong_uptrend(stub_quantconnect: Any) -> None:
    """A long uptrend satisfies all 8 BCT conditions -> 8 / '+++'."""
    # 700 daily bars (the scorer fetches _DAILY_BARS=700). A steady up-ramp keeps price above
    # every cloud/Tenkan/Kijun/200MA and the weekly chikou rising. Mild sinusoidal chop keeps
    # Wilder ADX from saturating at 100 (so it is still RISING into the last bar, satisfying
    # cond 7's adx[-1] > adx[-4]); a gentle final acceleration confirms the rise + keeps +DI>-DI.
    t = np.arange(700, dtype=float)
    closes = 50.0 + 0.25 * t + 2.5 * np.sin(t / 6.0)
    closes[-30:] = closes[-30:] + np.linspace(0.0, 8.0, 30)
    algo = FakeAlgo(_daily_frame(closes))

    out = score_symbol(algo, symbol="AAPL")

    assert out is not None
    assert out["score"] == 8
    assert out["rating"] == "+++"
    assert out["conditions"] == [True] * 8


# -------------------------------------------------------------------------- DECLINE (None)


def test_score_symbol_declines_none_on_insufficient_daily_history(stub_quantconnect: Any) -> None:
    """Warmup guard: < 230 daily bars -> None (cannot score)."""
    closes = 50.0 + np.arange(100, dtype=float)  # only 100 bars
    algo = FakeAlgo(_daily_frame(closes))

    assert score_symbol(algo, symbol="AAPL") is None


def test_score_symbol_declines_none_outside_lean() -> None:
    """No stub_quantconnect fixture here: the QuantConnect import fails -> None (outside LEAN)."""
    sys.modules.pop("QuantConnect", None)
    closes = 50.0 + 0.25 * np.arange(700, dtype=float)
    algo = FakeAlgo(_daily_frame(closes))

    assert score_symbol(algo, symbol="AAPL") is None


def test_score_symbol_declines_none_on_empty_history(stub_quantconnect: Any) -> None:
    """Null: an empty History frame -> None (the _fetch_ohlcv empty guard)."""
    algo = FakeAlgo(pd.DataFrame())

    assert score_symbol(algo, symbol="AAPL") is None


# ----------------------------------------------------------------------- DECLINE (bearish)


def test_score_symbol_does_not_fire_full_on_downtrend(stub_quantconnect: Any) -> None:
    """A steady downtrend fails the bullish conditions -> not 8/8, not '+++'."""
    t = np.arange(700, dtype=float)
    closes = 250.0 - 0.25 * t  # monotone decreasing, stays positive
    algo = FakeAlgo(_daily_frame(closes))

    out = score_symbol(algo, symbol="AAPL")

    # May be None if a midpoint is NaN, but if it scores it must NOT be a full bull rating.
    if out is not None:
        assert out["score"] < 8
        assert out["rating"] != "+++"
